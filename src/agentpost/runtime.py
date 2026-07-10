from __future__ import annotations

import fcntl
import json
import logging
import os
import queue
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

from .adapters import MailboxWatcher
from .channel import AgentChannel
from .core import AgentPostError, MessageRecord, PostOffice


logger = logging.getLogger(__name__)


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
    ) -> None:
        if interval <= 0:
            raise ValueError("interval must be positive")
        self.office = PostOffice(root)
        self.profile = self.office.load_profile(agent)
        self.agent = agent
        self.channel = AgentChannel(agent, office=self.office)
        self.on_mail = on_mail
        self.interval = interval
        self._watcher = MailboxWatcher(self.office, agent, interval=interval)
        self._state = "idle"
        self._active_work = 0
        self._state_lock = threading.Lock()
        self._heartbeat_lock = threading.Lock()
        self._deferred: list[MessageRecord] = []
        self._batches: queue.Queue[tuple[Notification, ...]] = queue.Queue()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock_handle = None
        adapter = self.office.root / "agents" / agent / "adapter"
        self._marker = adapter / f"python-runtime-{os.getpid()}-{uuid.uuid4().hex}.json"
        self._owner_lock = adapter / "python-runtime.lock"

    @property
    def state(self) -> str:
        with self._state_lock:
            return self._state

    def start(self) -> AgentRuntime:
        if self._thread is not None and self._thread.is_alive():
            return self
        self._acquire_owner()
        self._stop.clear()
        self._wake.clear()
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
        if self._thread is not None:
            self._thread.join(timeout=max(2.0, self.interval * 4))
        self._marker.unlink(missing_ok=True)
        if self._lock_handle is not None:
            fcntl.flock(self._lock_handle.fileno(), fcntl.LOCK_UN)
            self._lock_handle.close()
            self._lock_handle = None

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
        return self._batches.get(timeout=timeout)

    def __enter__(self) -> AgentRuntime:
        return self.start()

    def __exit__(self, *_exc) -> None:
        self.close()

    def _run(self) -> None:
        last_heartbeat = 0.0
        try:
            while not self._stop.is_set():
                now = time.time()
                if now - last_heartbeat >= 1.0:
                    self._write_heartbeat()
                    last_heartbeat = now
                self._surface(self._watcher.pending())
                self._wake.wait(self.interval)
                self._wake.clear()
        finally:
            self._marker.unlink(missing_ok=True)

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
            try:
                self.on_mail(batch)
            except Exception:  # noqa: BLE001 - host callback failures are logged, not fatal
                logger.exception("AgentPost callback failed for %s", self.agent)

    def _acquire_owner(self) -> None:
        self._owner_lock.parent.mkdir(parents=True, exist_ok=True)
        handle = self._owner_lock.open("a+b")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            handle.close()
            raise AgentPostError(
                f"a Python AgentPost runtime already owns mailbox {self.agent}"
            ) from exc
        self._lock_handle = handle

    def _require_started(self) -> None:
        if self._thread is None or not self._thread.is_alive():
            raise AgentPostError("Python AgentPost runtime is not started")

    def _write_heartbeat(self) -> None:
        with self._heartbeat_lock:
            _atomic_json(
                self._marker,
                {
                    "pid": os.getpid(),
                    "updated_at": time.time(),
                    "state": self.state,
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
