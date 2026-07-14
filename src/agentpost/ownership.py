from __future__ import annotations

import fcntl
import json
import os
import tempfile
import time
import uuid
from pathlib import Path

from .core import AgentPostError, PostOffice


class ConsumerLease:
    """Exclusive inbound-consumer ownership for one durable mailbox."""

    def __init__(
        self,
        office: PostOffice,
        agent: str,
        adapter: str,
        *,
        instance_id: str | None = None,
        cwd: str | Path | None = None,
    ) -> None:
        office.load_profile(agent)
        self.office = office
        self.agent = agent
        self.adapter = adapter
        self.instance_id = instance_id or uuid.uuid4().hex
        self.cwd = str(Path(cwd or Path.cwd()).expanduser().resolve())
        directory = office.root / "agents" / agent / "adapter"
        self.lock_path = directory / "consumer.lock"
        self.owner_path = directory / "consumer.json"
        self._handle = None

    @property
    def acquired(self) -> bool:
        return self._handle is not None

    def acquire(self, *, blocking: bool = False) -> bool:
        if self.acquired:
            return True
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.lock_path.open("a+b")
        flags = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
        try:
            fcntl.flock(handle.fileno(), flags)
        except BlockingIOError:
            handle.close()
            return False
        self._handle = handle
        _atomic_json(
            self.owner_path,
            {
                "version": 1,
                "instance_id": self.instance_id,
                "adapter": self.adapter,
                "pid": os.getpid(),
                "cwd": self.cwd,
                "acquired_at": time.time(),
            },
        )
        return True

    def require(self) -> None:
        if self.acquire():
            return
        owner = self.current_owner()
        detail = "another live instance"
        if owner:
            owner_pid = owner.get("pid")
            if owner.get("adapter") == "codex" and _is_process_ancestor(owner_pid):
                raise AgentPostError(
                    f"mailbox {self.agent} is already owned by this Codex session's "
                    f"parent bridge (PID {owner_pid}, instance "
                    f"{owner.get('instance_id', '?')}); do not launch or join it again; "
                    "continue in the existing session"
                )
            detail = (
                f"{owner.get('adapter', 'unknown')} pid {owner.get('pid', '?')} "
                f"instance {owner.get('instance_id', '?')}"
            )
            if owner.get("adapter") == "codex":
                detail += (
                    "; if this command is running inside that managed Codex session, "
                    "continue there instead of launching a nested copy"
                )
        parallel_name = _next_parallel_name(self.office, self.agent)
        raise AgentPostError(
            f"mailbox {self.agent} already has an inbound consumer: {detail}; "
            f"ask the user whether to create a separate identity `{parallel_name}`; "
            "do not create it without explicit approval"
        )

    def release(self) -> None:
        if self._handle is None:
            return
        try:
            owner = self.current_owner()
            if owner.get("instance_id") == self.instance_id:
                self.owner_path.unlink(missing_ok=True)
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        finally:
            self._handle.close()
            self._handle = None

    def current_owner(self) -> dict:
        try:
            value = json.loads(self.owner_path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def __enter__(self) -> ConsumerLease:
        self.require()
        return self

    def __exit__(self, *_exc) -> None:
        self.release()


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}-")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _next_parallel_name(office: PostOffice, name: str) -> str:
    existing = set()
    if office.agents_dir.is_dir():
        existing = {
            path.name for path in office.agents_dir.iterdir() if path.is_dir()
        }
    number = 2
    while True:
        suffix = str(number)
        candidate = f"{name[: 64 - len(suffix)]}{suffix}"
        if candidate not in existing:
            return candidate
        number += 1


def _is_process_ancestor(ancestor_pid: object, descendant_pid: int | None = None) -> bool:
    """Best-effort Linux ancestry check used only to improve lease diagnostics."""
    try:
        ancestor = int(ancestor_pid)
        current = int(descendant_pid or os.getpid())
    except (TypeError, ValueError):
        return False
    while current > 1:
        if current == ancestor:
            return True
        try:
            stat = Path(f"/proc/{current}/stat").read_text(encoding="ascii")
            fields = stat[stat.rfind(")") + 2 :].split()
            current = int(fields[1])
        except (OSError, ValueError, IndexError):
            return False
    return current == ancestor
