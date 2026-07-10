from __future__ import annotations

import asyncio
import json
import logging
import os
import queue
import tempfile
import threading
import time
import uuid
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

from .adapters import MailboxWatcher
from .channel import AgentChannel
from .core import AgentPostError, MessageRecord, PostOffice
from .ownership import ConsumerLease
from .presence import HEARTBEAT_INTERVAL_SECONDS


logger = logging.getLogger(__name__)
_CLOSED = object()


@dataclass(frozen=True)
class Notification:
    message_id: str
    from_agent: str
    kind: str
    notify: str
    path: Path


class AgentRuntime:
    """CLI-neutral mailbox presence and wake adapter for Python agent systems.

    The runtime never calls a model and never claims mail. It emits committed
    Message-IDs to an application callback/queue; the host decides how those
    events enter its own scheduler and when work begins.
    """

    def __init__(
        self,
        agent: str,
        *,
        root: str | Path = "~/.agentpost",
        on_mail: Callable[[tuple[Notification, ...]], None] | None = None,
        interval: float = 0.25,
        max_callback_attempts: int = 8,
    ) -> None:
        if interval <= 0:
            raise ValueError("interval must be positive")
        if max_callback_attempts <= 0:
            raise ValueError("max_callback_attempts must be positive")
        self.office = PostOffice(root)
        self.profile = self.office.load_profile(agent)
        self.agent = agent
        self.channel = AgentChannel(agent, office=self.office)
        self.on_mail = on_mail
        self.interval = interval
        self.max_callback_attempts = max_callback_attempts
        self._watcher = MailboxWatcher(self.office, agent, interval=interval)
        self._state = "idle"
        self._active_work = 0
        self._state_lock = threading.Lock()
        self._heartbeat_lock = threading.Lock()
        self._deferred: list[MessageRecord] = []
        self._batches: queue.Queue[tuple[Notification, ...] | object] = queue.Queue()
        self._callback_pending: deque[tuple[Notification, ...]] = deque()
        self._callback_attempt = 0
        self._callback_retry_at = 0.0
        self._callback_exhausted: frozenset[str] = frozenset()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        adapter = self.office.root / "agents" / agent / "adapter"
        instance_id = uuid.uuid4().hex
        self._marker = adapter / f"python-runtime-{os.getpid()}-{instance_id}.json"
        self._lease = ConsumerLease(
            self.office,
            agent,
            "python",
            instance_id=instance_id,
        )

    @property
    def state(self) -> str:
        with self._state_lock:
            return self._state

    def start(self) -> AgentRuntime:
        if self._thread is not None and self._thread.is_alive():
            return self
        self._stop.clear()
        self._wake.clear()
        if self._lease.acquire():
            self._write_heartbeat()
        self._thread = threading.Thread(
            target=self._run,
            name=f"agentpost-{self.agent}",
            daemon=True,
        )
        self._thread.start()
        return self

    def close(self) -> None:
        self._stop.set()
        self._wake.set()
        self._batches.put(_CLOSED)
        if self._thread is not None:
            self._thread.join(timeout=max(2.0, self.interval * 4))
        self._marker.unlink(missing_ok=True)
        self._lease.release()

    def set_state(self, state: str) -> None:
        self._require_started()
        if state not in {"working", "idle"}:
            raise ValueError(f"invalid runtime state: {state}")
        with self._state_lock:
            self._state = state
            self._active_work = 1 if state == "working" else 0
        self._write_heartbeat()
        self._wake.set()

    def begin_work(self) -> None:
        self._require_started()
        with self._state_lock:
            self._active_work += 1
            self._state = "working"
        self._write_heartbeat()
        self._wake.set()

    def end_work(self) -> None:
        self._require_started()
        with self._state_lock:
            if self._active_work == 0:
                raise RuntimeError("end_work called without matching begin_work")
            self._active_work -= 1
            if self._active_work == 0:
                self._state = "idle"
        self._write_heartbeat()
        self._wake.set()

    @contextmanager
    def turn(self) -> Iterator[None]:
        self.begin_work()
        try:
            yield
        finally:
            self.end_work()

    def get(self, timeout: float | None = None) -> tuple[Notification, ...]:
        """Return the next surfaced notification batch from the runtime queue."""
        while True:
            item = self._batches.get(timeout=timeout)
            if isinstance(item, tuple):
                return item
            if self._stop.is_set():
                self._batches.put(_CLOSED)
                raise AgentPostError("Python AgentPost runtime is closed")

    async def get_async(self, timeout: float | None = None) -> tuple[Notification, ...]:
        """Await the next batch without indefinitely occupying a worker thread."""
        if timeout is not None and timeout < 0:
            raise ValueError("timeout must be non-negative")
        if timeout == 0:
            return self.get(timeout=0)
        loop = asyncio.get_running_loop()
        deadline = None if timeout is None else loop.time() + timeout
        while True:
            remaining = None if deadline is None else deadline - loop.time()
            if remaining is not None and remaining <= 0:
                raise queue.Empty
            wait = 0.25 if remaining is None else min(0.25, remaining)
            try:
                return await asyncio.to_thread(self.get, wait)
            except queue.Empty:
                await asyncio.sleep(0)

    def unread(self) -> tuple[Notification, ...]:
        """Return a side-effect-free snapshot for host reconciliation."""
        return tuple(
            _notification(record)
            for record in self.office.list_messages(self.agent, "unread")
        )

    def __enter__(self) -> AgentRuntime:
        return self.start()

    def __exit__(self, *_exc) -> None:
        self.close()

    async def __aenter__(self) -> AgentRuntime:
        return self.start()

    async def __aexit__(self, *_exc) -> None:
        await asyncio.to_thread(self.close)

    def _run(self) -> None:
        last_heartbeat = 0.0
        try:
            while not self._stop.is_set():
                if not self._lease.acquired:
                    if not self._lease.acquire():
                        self._wake.wait(self.interval)
                        self._wake.clear()
                        continue
                    self._write_heartbeat()
                now = time.time()
                if now - last_heartbeat >= HEARTBEAT_INTERVAL_SECONDS:
                    self._write_heartbeat()
                    last_heartbeat = now
                self._prune_callback_exhaustion()
                self._flush_callback()
                self._surface(self._watcher.pending())
                self._wake.wait(self.interval)
                self._wake.clear()
        finally:
            self._marker.unlink(missing_ok=True)
            self._lease.release()

    def _surface(self, fresh: tuple[MessageRecord, ...]) -> None:
        ready = []
        state = self.state
        for record in fresh:
            if state == "working" and record.letter.notify == "idle":
                self._deferred.append(record)
            else:
                ready.append(record)
        if state == "idle" and self._deferred:
            ready = [*self._deferred, *ready]
            self._deferred.clear()
        if not ready:
            return
        batch = tuple(_notification(record) for record in ready)
        self._batches.put(batch)
        if self.on_mail is not None:
            self._callback_pending.append(batch)
            self._flush_callback()

    def _flush_callback(self) -> None:
        if self.on_mail is None or not self._callback_pending:
            return
        now = time.monotonic()
        if now < self._callback_retry_at:
            return
        while self._callback_pending:
            batch = self._callback_pending[0]
            if self._callback_attempt:
                unread = {
                    record.letter.message_id
                    for record in self.office.list_messages(self.agent, "unread")
                }
                batch = tuple(item for item in batch if item.message_id in unread)
                if not batch:
                    self._callback_pending.popleft()
                    self._callback_attempt = 0
                    self._callback_retry_at = 0.0
                    continue
                self._callback_pending[0] = batch
            try:
                self.on_mail(batch)
            except Exception:  # noqa: BLE001 - host callback failures are logged, not fatal
                self._callback_attempt += 1
                if self._callback_attempt >= self.max_callback_attempts:
                    exhausted = tuple(item.message_id for item in batch)
                    self._callback_exhausted = self._callback_exhausted.union(exhausted)
                    self._callback_pending.popleft()
                    self._callback_attempt = 0
                    self._callback_retry_at = 0.0
                    logger.exception(
                        "AgentPost callback exhausted for %s after %d attempts: %s",
                        self.agent,
                        self.max_callback_attempts,
                        ", ".join(exhausted),
                    )
                    self._write_heartbeat()
                    continue
                delay = min(
                    30.0,
                    max(self.interval, 0.1)
                    * (2 ** min(self._callback_attempt - 1, 8)),
                )
                self._callback_retry_at = now + delay
                logger.exception(
                    "AgentPost callback failed for %s; retrying in %.2fs",
                    self.agent,
                    delay,
                )
                return
            self._callback_pending.popleft()
            self._callback_attempt = 0
            self._callback_retry_at = 0.0

    def _prune_callback_exhaustion(self) -> None:
        if not self._callback_exhausted:
            return
        unread = {item.message_id for item in self.unread()}
        remaining = self._callback_exhausted.intersection(unread)
        if remaining != self._callback_exhausted:
            self._callback_exhausted = frozenset(remaining)
            self._write_heartbeat()

    def _require_started(self) -> None:
        if self._thread is None or not self._thread.is_alive():
            raise AgentPostError("Python AgentPost runtime is not started")

    def _write_heartbeat(self) -> None:
        if not self._lease.acquired:
            return
        with self._heartbeat_lock:
            _atomic_json(
                self._marker,
                {
                    "pid": os.getpid(),
                    "updated_at": time.time(),
                    "state": self.state,
                    "instance_id": self._lease.instance_id,
                    "adapter": "python",
                    "callback_exhausted": sorted(self._callback_exhausted),
                },
            )


def _notification(record: MessageRecord) -> Notification:
    letter = record.letter
    return Notification(
        message_id=letter.message_id,
        from_agent=letter.from_agent,
        kind=letter.kind,
        notify=letter.notify,
        path=record.path,
    )


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}-")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
