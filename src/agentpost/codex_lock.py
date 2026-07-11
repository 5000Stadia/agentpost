from __future__ import annotations

import fcntl
from pathlib import Path


class CodexPluginLock:
    """Coordinates managed Codex sessions with global plugin replacement."""

    def __init__(self, home: Path | None = None) -> None:
        self.path = (home or Path.home()) / ".codex" / "agentpost-plugin.lock"
        self._handle = None

    def acquire_shared(self) -> bool:
        return self._acquire(fcntl.LOCK_SH)

    def acquire_exclusive(self) -> bool:
        return self._acquire(fcntl.LOCK_EX)

    def _acquire(self, mode: int) -> bool:
        if self._handle is not None:
            return True
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        try:
            fcntl.flock(handle.fileno(), mode | fcntl.LOCK_NB)
        except BlockingIOError:
            handle.close()
            return False
        self._handle = handle
        return True

    def release(self) -> None:
        if self._handle is None:
            return
        try:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        finally:
            self._handle.close()
            self._handle = None
