from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass

from .core import AgentPostError, PostOffice


@dataclass(frozen=True)
class Presence:
    state: str
    detail: str
    updated_at: float | None = None
    healthy: bool = True

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
    adapter = office.root / "agents" / agent / "adapter"
    if profile.cli == "claude":
        return _claude_presence(adapter)
    if profile.cli == "codex":
        return _codex_presence(adapter)
    if profile.cli == "python":
        return _python_presence(adapter)
    if profile.cli == "antigravity":
        return _antigravity_presence(adapter)
    return Presence("offline", f"no native presence probe for {profile.cli}")


def _claude_presence(adapter) -> Presence:
    live = []
    cutoff = time.time() - 3.0
    for marker in sorted(adapter.glob("claude-monitor-*.json")):
        try:
            value = json.loads(marker.read_text(encoding="utf-8"))
            pid = int(value["pid"])
            updated_at = float(value["updated_at"])
            state = str(value.get("state", "idle"))
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            continue
        if updated_at >= cutoff and _pid_alive(pid):
            live.append((state, updated_at, pid))
    if not live:
        return Presence("offline", "Claude catch-up only; restart or reload the project session")
    working = [item for item in live if item[0] in {"busy", "working"}]
    state, updated_at, pid = max(working or live, key=lambda item: item[1])
    resolved = "working" if state in {"busy", "working"} else "idle"
    return Presence(resolved, f"Claude monitor pid {pid}", updated_at)


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
        fresh = updated_at >= time.time() - 3.0
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        try:
            pid = int(raw)
        except ValueError:
            pid = 0
        updated_at = None
        state = "idle"
        fresh = True
    if not (fresh and _pid_alive(pid)):
        return Presence(
            "offline",
            "Codex catch-up only; launch with `agentpost codex --agent NAME`",
        )
    resolved = "working" if state in {"busy", "working"} else "idle"
    return Presence(resolved, f"Codex app-server bridge pid {pid}", updated_at)


def _python_presence(adapter) -> Presence:
    live = []
    cutoff = time.time() - 3.0
    for marker in sorted(adapter.glob("python-runtime-*.json")):
        try:
            value = json.loads(marker.read_text(encoding="utf-8"))
            pid = int(value["pid"])
            updated_at = float(value["updated_at"])
            state = str(value.get("state", "idle"))
            exhausted = tuple(value.get("callback_exhausted", ()))
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            continue
        if updated_at >= cutoff and _pid_alive(pid):
            live.append((state, updated_at, pid, exhausted))
    if not live:
        return Presence(
            "offline",
            "Python runtime not attached; embed `agentpost.AgentRuntime`",
        )
    working = [item for item in live if item[0] == "working"]
    state, updated_at, pid, exhausted = max(working or live, key=lambda item: item[1])
    detail = f"Python runtime pid {pid}"
    if exhausted:
        detail += f"; callback exhausted for {len(exhausted)} unread message(s)"
    return Presence(state, detail, updated_at, healthy=not exhausted)


def _antigravity_presence(adapter) -> Presence:
    marker = adapter / "antigravity-hook.active"
    try:
        value = json.loads(marker.read_text(encoding="utf-8"))
        updated_at = float(value["updated_at"])
        state = str(value.get("state", "idle"))
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return Presence(
            "offline",
            "Antigravity catch-up only; start or prompt the project session",
        )
    if updated_at < time.time() - 3.0:
        return Presence(
            "offline",
            "Antigravity catch-up only; start or prompt the project session",
            updated_at,
        )
    resolved = "working" if state == "working" else "idle"
    return Presence(resolved, "Antigravity lifecycle hook", updated_at)


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False
