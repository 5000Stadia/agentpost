from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass

from .core import AgentPostError, PostOffice


HEARTBEAT_INTERVAL_SECONDS = 1.0
PRESENCE_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True)
class Presence:
    state: str
    detail: str
    updated_at: float | None = None
    healthy: bool = True
    adapter: str | None = None
    instance_id: str | None = None
    wake_capable: bool = False

    @property
    def active(self) -> bool:
        return self.state != "offline"


def agent_presence(office: PostOffice, agent: str) -> Presence:
    try:
        profile = office.load_profile(agent)
    except AgentPostError:
        raise
    except OSError as exc:
        raise AgentPostError(f"unknown agent: {agent}") from exc

    adapter_dir = office.root / "agents" / agent / "adapter"
    owner = _consumer_owner(adapter_dir)
    probes = (
        _claude_presence(adapter_dir),
        _codex_presence(adapter_dir),
        _python_presence(adapter_dir),
        _antigravity_presence(adapter_dir),
    )
    active = [item for item in probes if item.active and _matches_owner(item, owner)]
    if not active:
        connected = sorted(
            {
                binding.cli
                for binding in office.list_bindings()
                if binding.agent == agent
            }
            | ({profile.cli} if profile.cli else set())
        )
        detail = "no live mailbox consumer"
        if connected:
            detail += f"; connected adapters: {', '.join(connected)}"
        return Presence("offline", detail)

    working = [item for item in active if item.state == "working"]
    selected = max(
        working or active,
        key=lambda item: item.updated_at if item.updated_at is not None else 0.0,
    )
    if len(active) == 1:
        return selected
    adapters = ", ".join(sorted(item.adapter or "unknown" for item in active))
    return Presence(
        selected.state,
        f"{selected.detail}; live adapters: {adapters}",
        selected.updated_at,
        healthy=all(item.healthy for item in active),
        adapter=selected.adapter,
        instance_id=selected.instance_id,
        wake_capable=any(item.wake_capable and item.healthy for item in active),
    )


def _claude_presence(adapter) -> Presence:
    live = []
    cutoff = time.time() - PRESENCE_TIMEOUT_SECONDS
    for marker in sorted(adapter.glob("claude-monitor-*.json")):
        try:
            value = json.loads(marker.read_text(encoding="utf-8"))
            pid = int(value["pid"])
            updated_at = float(value["updated_at"])
            state = str(value.get("state", "idle"))
            instance_id = value.get("instance_id")
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            continue
        if updated_at >= cutoff and _pid_alive(pid):
            live.append((state, updated_at, pid, instance_id))
    if not live:
        return Presence("offline", "Claude monitor is not live", adapter="claude")
    working = [item for item in live if item[0] in {"busy", "working"}]
    state, updated_at, pid, instance_id = max(working or live, key=lambda item: item[1])
    resolved = "working" if state in {"busy", "working"} else "idle"
    detail = f"Claude monitor pid {pid}"
    if instance_id:
        detail += f" instance {str(instance_id)[:8]}"
    return Presence(
        resolved,
        detail,
        updated_at,
        adapter="claude",
        instance_id=instance_id,
        wake_capable=True,
    )


def _codex_presence(adapter) -> Presence:
    marker = adapter / "codex-bridge.active"
    try:
        raw = marker.read_text(encoding="utf-8").strip()
    except OSError:
        raw = ""
    try:
        value = json.loads(raw)
        pid = int(value["pid"])
        updated_at = float(value["updated_at"])
        state = str(value.get("state", "idle"))
        instance_id = value.get("instance_id")
        fresh = updated_at >= time.time() - PRESENCE_TIMEOUT_SECONDS
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        try:
            pid = int(raw)
        except ValueError:
            pid = 0
        try:
            updated_at = marker.stat().st_mtime
        except OSError:
            updated_at = None
        state = "idle"
        instance_id = None
        fresh = bool(
            updated_at is not None
            and updated_at >= time.time() - PRESENCE_TIMEOUT_SECONDS
        )
    if not (fresh and _pid_alive(pid)):
        return Presence("offline", "Codex bridge is not live", adapter="codex")
    resolved = "working" if state in {"busy", "working"} else "idle"
    detail = f"Codex app-server bridge pid {pid}"
    if instance_id:
        detail += f" instance {str(instance_id)[:8]}"
    return Presence(
        resolved,
        detail,
        updated_at,
        adapter="codex",
        instance_id=instance_id,
        wake_capable=True,
    )


def _python_presence(adapter) -> Presence:
    live = []
    cutoff = time.time() - PRESENCE_TIMEOUT_SECONDS
    for marker in sorted(adapter.glob("python-runtime-*.json")):
        try:
            value = json.loads(marker.read_text(encoding="utf-8"))
            pid = int(value["pid"])
            updated_at = float(value["updated_at"])
            state = str(value.get("state", "idle"))
            exhausted = tuple(value.get("callback_exhausted", ()))
            instance_id = value.get("instance_id")
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            continue
        if updated_at >= cutoff and _pid_alive(pid):
            live.append((state, updated_at, pid, exhausted, instance_id))
    if not live:
        return Presence("offline", "Python runtime is not attached", adapter="python")
    working = [item for item in live if item[0] == "working"]
    state, updated_at, pid, exhausted, instance_id = max(
        working or live, key=lambda item: item[1]
    )
    detail = f"Python runtime pid {pid}"
    if instance_id:
        detail += f" instance {str(instance_id)[:8]}"
    if exhausted:
        detail += f"; callback exhausted for {len(exhausted)} unread message(s)"
    return Presence(
        state,
        detail,
        updated_at,
        healthy=not exhausted,
        adapter="python",
        instance_id=instance_id,
        wake_capable=True,
    )


def _antigravity_presence(adapter) -> Presence:
    marker = adapter / "antigravity-hook.active"
    try:
        value = json.loads(marker.read_text(encoding="utf-8"))
        updated_at = float(value["updated_at"])
        state = str(value.get("state", "idle"))
        instance_id = value.get("instance_id")
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return Presence("offline", "Antigravity hook is not live", adapter="antigravity")
    if updated_at < time.time() - PRESENCE_TIMEOUT_SECONDS:
        return Presence(
            "offline",
            "Antigravity hook is not live",
            updated_at,
            adapter="antigravity",
            instance_id=instance_id,
        )
    resolved = "working" if state == "working" else "idle"
    detail = "Antigravity lifecycle hook"
    if instance_id:
        detail += f" instance {str(instance_id)[:8]}"
    return Presence(
        resolved,
        detail,
        updated_at,
        adapter="antigravity",
        instance_id=instance_id,
        wake_capable=False,
    )


def _consumer_owner(adapter) -> dict:
    try:
        value = json.loads((adapter / "consumer.json").read_text(encoding="utf-8"))
        pid = int(value["pid"])
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return {}
    return value if _pid_alive(pid) else {}


def _matches_owner(presence: Presence, owner: dict) -> bool:
    if not owner:
        return True
    owner_instance = owner.get("instance_id")
    if presence.instance_id is not None:
        return presence.instance_id == owner_instance
    return presence.adapter == owner.get("adapter")


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False
