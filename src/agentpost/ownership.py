from __future__ import annotations

import fcntl
import hashlib
import json
import os
import signal
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
        session_digest: str | None = None,
    ) -> None:
        office.load_profile(agent)
        self.office = office
        self.agent = agent
        self.adapter = adapter
        self.instance_id = instance_id or uuid.uuid4().hex
        self.cwd = str(Path(cwd or Path.cwd()).expanduser().resolve())
        self.session_digest = session_digest
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
        self.office.load_profile(self.agent)
        try:
            handle = self.lock_path.open("a+b")
        except FileNotFoundError as exc:
            raise AgentPostError(
                f"mailbox {self.agent} is not initialized for consumer ownership"
            ) from exc
        flags = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
        try:
            fcntl.flock(handle.fileno(), flags)
        except BlockingIOError:
            handle.close()
            return False
        try:
            self.office.load_profile(self.agent)
            mailbox = self.office.root / "agents" / self.agent / "unread"
            if not mailbox.is_dir():
                raise AgentPostError(
                    f"mailbox {self.agent} was removed before the consumer "
                    "lease could be acquired"
                )
        except Exception:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()
            raise
        self._handle = handle
        owner = {
            "version": 1,
            "instance_id": self.instance_id,
            "adapter": self.adapter,
            "pid": os.getpid(),
            "cwd": self.cwd,
            "acquired_at": time.time(),
        }
        if self.session_digest:
            owner["session_digest"] = self.session_digest
        _atomic_json(self.owner_path, owner)
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
            if consumer_process_state(owner_pid) in {"T", "t"}:
                instance_id = owner.get("instance_id", "?")
                raise AgentPostError(
                    f"mailbox {self.agent} has a suspended inbound consumer: "
                    f"{owner.get('adapter', 'unknown')} pid {owner_pid or '?'} "
                    f"instance {instance_id}; it is offline but still holds the "
                    "inbound lease. If that session was intentionally closed, run "
                    f"`agentpost consumer-stop {self.agent} --instance "
                    f"{instance_id}` and retry the original launcher. Do not create "
                    f"{_next_parallel_name(self.office, self.agent)} for this condition"
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


def consumer_process_state(pid: object) -> str | None:
    """Return the Linux process state used for lease diagnostics."""
    try:
        parsed = int(pid)
        stat = Path(f"/proc/{parsed}/stat").read_text(encoding="ascii")
        fields = stat[stat.rfind(")") + 2 :].split()
        return fields[0]
    except (TypeError, ValueError, OSError, IndexError):
        return None


def consumer_lock_held(lock_path: Path) -> bool:
    """Probe an existing consumer lock without changing its owner document."""
    try:
        handle = lock_path.open("rb")
    except OSError:
        return False
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        return False
    finally:
        handle.close()


def stop_managed_consumer(
    office: PostOffice,
    agent: str,
    instance_id: str,
    *,
    timeout: float = 10.0,
) -> dict:
    """Gracefully stop one exact AgentPost-managed CLI consumer."""
    if not instance_id:
        raise AgentPostError("consumer-stop requires the full owner instance ID")
    probe = ConsumerLease(office, agent, "consumer-stop")
    owner = probe.current_owner()
    if not owner:
        raise AgentPostError(f"mailbox {agent} has no recorded inbound consumer")
    current_instance = str(owner.get("instance_id", ""))
    if current_instance != instance_id:
        raise AgentPostError(
            f"mailbox {agent} is owned by instance {current_instance or '?'}, not "
            f"the requested instance {instance_id}; refusing to stop a replacement "
            "consumer"
        )
    if not consumer_lock_held(probe.lock_path):
        raise AgentPostError(
            f"mailbox {agent} has no held inbound consumer lease; the owner record "
            "is stale and no process was signaled"
        )
    adapter = str(owner.get("adapter", ""))
    if adapter not in {"antigravity", "codex"}:
        raise AgentPostError(
            f"consumer-stop supports AgentPost-managed Codex and Antigravity "
            f"launchers; {agent} is owned by {adapter or 'an unknown adapter'}"
        )
    try:
        pid = int(owner["pid"])
    except (KeyError, TypeError, ValueError) as exc:
        raise AgentPostError(
            f"mailbox {agent} owner has no valid PID; no process was signaled"
        ) from exc
    if not _is_managed_launcher(pid, agent, adapter):
        raise AgentPostError(
            f"refusing to signal pid {pid}: it is not a verified AgentPost-managed "
            f"{adapter} launcher for {agent}"
        )

    # Revalidate immediately before signaling so a newly acquired instance
    # cannot be stopped by a stale terminal instruction.
    if probe.current_owner().get("instance_id") != instance_id:
        raise AgentPostError(
            f"mailbox {agent} changed owners during recovery; no process was signaled"
        )
    stopped = consumer_process_state(pid) in {"T", "t"}
    try:
        os.kill(pid, signal.SIGINT)
        if stopped:
            os.kill(pid, signal.SIGCONT)
    except ProcessLookupError as exc:
        raise AgentPostError(
            f"consumer pid {pid} exited before recovery; retry after checking "
            f"`agentpost status {agent}`"
        ) from exc
    except PermissionError as exc:
        raise AgentPostError(f"permission denied while stopping consumer pid {pid}") from exc

    deadline = time.monotonic() + timeout
    marker = office.root / "agents" / agent / "adapter" / "codex-bridge.active"
    while time.monotonic() < deadline:
        marker_clear = adapter != "codex" or not marker.exists()
        if marker_clear and not consumer_lock_held(probe.lock_path):
            return owner
        time.sleep(0.05)
    raise AgentPostError(
        f"managed {adapter} consumer pid {pid} did not release mailbox {agent} "
        f"within {timeout:g} seconds; it was not force-killed"
    )


def _is_managed_launcher(pid: int, agent: str, adapter: str) -> bool:
    argv = _process_argv(pid)
    try:
        adapter_index = argv.index(adapter)
        agent_index = argv.index("--agent", adapter_index + 1)
    except ValueError:
        return False
    if agent_index + 1 >= len(argv) or argv[agent_index + 1] != agent:
        return False
    prefix = argv[:adapter_index]
    return any(Path(item).name == "agentpost" for item in prefix)


def codex_session_digest(session_id: str) -> str:
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()


def find_managed_codex_thread(
    office: PostOffice,
    session_digest: str,
    *,
    exclude_agent: str | None = None,
) -> tuple[str, dict] | None:
    """Find a verified live Codex owner for one durable thread digest."""
    if not office.agents_dir.is_dir():
        return None
    for mailbox in sorted(office.agents_dir.iterdir(), key=lambda path: path.name):
        if not mailbox.is_dir() or mailbox.name == exclude_agent:
            continue
        adapter_dir = mailbox / "adapter"
        lock_path = adapter_dir / "consumer.lock"
        if not consumer_lock_held(lock_path):
            continue
        try:
            owner = json.loads(
                (adapter_dir / "consumer.json").read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(owner, dict) or owner.get("adapter") != "codex":
            continue
        try:
            owner_pid = int(owner["pid"])
        except (KeyError, TypeError, ValueError):
            continue
        if not _is_managed_launcher(owner_pid, mailbox.name, "codex"):
            continue
        digest = owner.get("session_digest")
        if not digest:
            digest = _managed_codex_digest_from_argv(owner_pid)
        if digest == session_digest:
            return mailbox.name, owner
    return None


def _managed_codex_digest_from_argv(pid: int) -> str | None:
    argv = _process_argv(pid)
    try:
        command_index = argv.index("codex")
    except ValueError:
        return None
    tail = argv[command_index + 1 :]
    try:
        resume_index = next(
            index for index, value in enumerate(tail) if value in {"fork", "resume"}
        )
    except StopIteration:
        return None
    for value in tail[resume_index + 1 :]:
        if not value.startswith("-"):
            return codex_session_digest(value)
    return None


def _process_argv(pid: int) -> list[str]:
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return []
    return [
        item.decode("utf-8", errors="surrogateescape")
        for item in raw.split(b"\0")
        if item
    ]


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
