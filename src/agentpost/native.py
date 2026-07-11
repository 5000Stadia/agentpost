from __future__ import annotations

import hashlib
import json
import os
import select
import socket
import subprocess
import sys
import tempfile
import time
from importlib.resources import files
from pathlib import Path

from .adapters import MailboxWatcher
from .codex_generation import CODEX_HOOK_GENERATION, codex_hook_marker
from .core import AgentPostError, PostOffice
from .ownership import ConsumerLease
from .presence import HEARTBEAT_INTERVAL_SECONDS
from .routing import identify_agent


def claude_boundary(state: str, delay: float = 0.0) -> int:
    if state not in {"busy", "idle"}:
        raise ValueError(f"invalid Claude boundary state: {state}")
    if delay < 0:
        raise ValueError("boundary delay must not be negative")
    data_dir = Path(os.environ["CLAUDE_PLUGIN_DATA"])
    data_dir.mkdir(parents=True, exist_ok=True)
    destination = data_dir / "boundary.json"
    descriptor, temporary = tempfile.mkstemp(dir=data_dir, prefix=".boundary-")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump({"state": state, "not_before": time.time() + delay}, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)
    print("{}")
    return 0


def claude_monitor() -> int:
    office = PostOffice(_runtime_root())
    profile = identify_agent(
        office,
        Path.cwd(),
        cli="claude",
        agent=os.environ.get("AGENTPOST_AGENT"),
    )
    watcher = MailboxWatcher(office, profile.name, interval=0.2)
    lease = ConsumerLease(office, profile.name, "claude")
    marker = (
        office.root
        / "agents"
        / profile.name
        / "adapter"
        / f"claude-monitor-{os.getpid()}-{lease.instance_id}.json"
    )
    deferred = []
    last_heartbeat = 0.0
    try:
        while True:
            if not lease.acquired:
                if not lease.acquire():
                    time.sleep(watcher.interval)
                    continue
            now = time.time()
            state = _claude_boundary_state()
            if now - last_heartbeat >= HEARTBEAT_INTERVAL_SECONDS:
                _atomic_json(
                    marker,
                    {
                        "pid": os.getpid(),
                        "updated_at": now,
                        "state": state,
                        "instance_id": lease.instance_id,
                        "adapter": "claude",
                    },
                )
                last_heartbeat = now
            for record in watcher.pending():
                if record.letter.notify == "idle" and state == "busy":
                    deferred.append(record)
                else:
                    _emit_claude(record)
            if state == "idle" and deferred:
                for record in deferred:
                    _emit_claude(record)
                deferred.clear()
            time.sleep(watcher.interval)
    finally:
        marker.unlink(missing_ok=True)
        lease.release()


def codex_hook(event_name: str, generation: str | None = None) -> int:
    if event_name not in {"session-start", "user-prompt-submit", "stop"}:
        raise ValueError(f"invalid Codex hook event: {event_name}")
    event = json.load(sys.stdin)
    office = PostOffice(_runtime_root())
    try:
        profile = identify_agent(
            office,
            event.get("cwd", Path.cwd()),
            cli="codex",
            agent=os.environ.get("AGENTPOST_AGENT"),
        )
    except (AgentPostError, OSError, ValueError):
        print("{}")
        return 0
    _atomic_json(
        codex_hook_marker(office, profile.name, event_name),
        {
            "adapter": "codex-hook",
            "generation": generation or CODEX_HOOK_GENERATION,
            "event": event_name,
            "observed_at": time.time(),
            "session_id": str(event.get("session_id", event.get("sessionId", ""))),
            "cwd": str(event.get("cwd", Path.cwd())),
        },
    )
    if os.environ.get("AGENTPOST_CODEX_BRIDGE") == "1":
        print("{}")
        return 0
    lease = ConsumerLease(office, profile.name, "codex-hook")
    if not lease.acquire():
        print("{}")
        return 0
    try:
        if _codex_bridge_marker(office, profile.name).exists():
            print("{}")
            return 0
        unread = office.list_messages(profile.name, "unread")
        if not unread:
            print("{}")
            return 0
        pointers = ", ".join(record.letter.message_id for record in unread)
        instruction = (
            f"AgentPost has {len(unread)} unread message(s) for {profile.name}: "
            f"{pointers}. Inspect with agentpost list/read, claim each only when "
            "starting it, process the work, reply by Message-ID, and give the user "
            "a short synopsis."
        )
        hook_event_names = {
            "session-start": "SessionStart",
            "user-prompt-submit": "UserPromptSubmit",
        }
        if event_name in hook_event_names:
            print(
                json.dumps(
                    {
                        "hookSpecificOutput": {
                            "hookEventName": hook_event_names[event_name],
                            "additionalContext": instruction,
                        }
                    }
                )
            )
        elif not event.get("stop_hook_active", False):
            print(json.dumps({"decision": "block", "reason": instruction}))
        else:
            print("{}")
        return 0
    finally:
        lease.release()


def codex_snapshot(office: PostOffice, agent: str) -> int:
    records = office.list_messages(agent, "unread")
    print(
        json.dumps(
            [
                {
                    "message_id": record.letter.message_id,
                    "notify": record.letter.notify,
                }
                for record in records
            ]
        )
    )
    return 0


def antigravity_hook(event_name: str) -> int:
    if event_name not in {"pre-invocation", "stop"}:
        raise ValueError(f"invalid Antigravity hook event: {event_name}")
    event = json.load(sys.stdin)
    office = PostOffice(_runtime_root())
    profile = _antigravity_profile(office, event)
    if profile is None:
        print(_antigravity_empty_output(event_name))
        return 0

    inherited_instance = os.environ.get("AGENTPOST_CONSUMER_INSTANCE")
    lease = ConsumerLease(
        office,
        profile.name,
        "antigravity-hook",
        instance_id=inherited_instance,
    )
    owner = lease.current_owner()
    inherited = bool(
        inherited_instance and owner.get("instance_id") == inherited_instance
    )
    if not inherited and not lease.acquire():
        print(_antigravity_empty_output(event_name))
        return 0

    try:
        fully_idle = event_name == "stop" and bool(event.get("fullyIdle", True))
        state = "idle" if fully_idle else "working"
        _atomic_json(
            _antigravity_presence_marker(office, profile.name),
            {
                "conversation_id": str(event.get("conversationId", "")),
                "updated_at": time.time(),
                "state": state,
                "instance_id": inherited_instance or lease.instance_id,
                "adapter": "antigravity",
            },
        )
        if event_name == "stop" and not fully_idle:
            print(json.dumps({"decision": "stop"}))
            return 0

        unread = office.list_messages(profile.name, "unread")
        ledger_path = _antigravity_ledger(office, profile.name, event)
        notified = _antigravity_notified(ledger_path)
        pending = [record for record in unread if record.letter.message_id not in notified]
        if not pending:
            print(_antigravity_empty_output(event_name))
            return 0

        notified.update(record.letter.message_id for record in pending)
        _atomic_json(ledger_path, {"notified": sorted(notified)})
        instruction = _antigravity_instruction(profile.name, pending)
        if event_name == "pre-invocation":
            print(json.dumps({"injectSteps": [{"ephemeralMessage": instruction}]}))
        else:
            print(json.dumps({"decision": "continue", "reason": instruction}))
        return 0
    finally:
        if not inherited:
            lease.release()


def codex_launch(
    office: PostOffice,
    cwd: Path,
    codex_args: list[str],
    *,
    agent: str | None = None,
) -> int:
    profile = identify_agent(
        office,
        cwd,
        cli="codex",
        agent=agent or os.environ.get("AGENTPOST_AGENT"),
    )
    lease = ConsumerLease(office, profile.name, "codex", cwd=cwd)
    lease.require()
    marker = _codex_bridge_marker(office, profile.name)
    marker.parent.mkdir(parents=True, exist_ok=True)
    _atomic_json(
        marker,
        {
            "pid": os.getpid(),
            "updated_at": time.time(),
            "state": "idle",
            "instance_id": lease.instance_id,
            "adapter": "codex",
        },
    )
    port = _free_loopback_port()
    url = f"ws://127.0.0.1:{port}"
    server = None
    bridge = None
    try:
        server = subprocess.Popen(
            ["codex", "app-server", "--listen", url],
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        _wait_for_app_server(server, port)
        bridge_script = files("agentpost").joinpath("data/codex_bridge.mjs")
        bridge = subprocess.Popen(
            [
                "node",
                os.fspath(bridge_script),
                "--url",
                url,
                "--agent",
                profile.name,
                "--root",
                os.fspath(office.root),
                "--cwd",
                os.fspath(cwd),
                "--log",
                os.fspath(
                    office.root / "agents" / profile.name / "adapter" / "codex-bridge.log"
                ),
                "--presence",
                os.fspath(marker),
                "--owner-pid",
                str(os.getpid()),
                "--instance-id",
                lease.instance_id,
            ],
            cwd=cwd,
        )
        time.sleep(0.1)
        if bridge.poll() is not None:
            raise AgentPostError(
                f"Codex mailbox bridge exited during startup with status "
                f"{bridge.returncode}"
            )
        command = _codex_remote_command(url, codex_args)
        environment = os.environ.copy()
        environment["AGENTPOST_CODEX_BRIDGE"] = "1"
        environment["AGENTPOST_AGENT"] = profile.name
        try:
            return subprocess.call(command, cwd=cwd, env=environment)
        except KeyboardInterrupt:
            return 130
    except FileNotFoundError as exc:
        raise AgentPostError(f"Codex adapter dependency not found: {exc.filename}") from exc
    finally:
        if bridge is not None:
            _terminate(bridge)
        if server is not None:
            _terminate(server)
        marker.unlink(missing_ok=True)
        lease.release()


def claude_launch(
    office: PostOffice,
    cwd: Path,
    claude_args: list[str],
    *,
    agent: str,
) -> int:
    profile = identify_agent(office, cwd, cli="claude", agent=agent)
    environment = os.environ.copy()
    environment["AGENTPOST_AGENT"] = profile.name
    try:
        return subprocess.call(["claude", *claude_args], cwd=cwd, env=environment)
    except FileNotFoundError as exc:
        raise AgentPostError("Claude CLI not found") from exc


def antigravity_launch(
    office: PostOffice,
    cwd: Path,
    antigravity_args: list[str],
    *,
    agent: str,
) -> int:
    profile = identify_agent(office, cwd, cli="antigravity", agent=agent)
    lease = ConsumerLease(office, profile.name, "antigravity", cwd=cwd)
    lease.require()
    environment = os.environ.copy()
    environment["AGENTPOST_AGENT"] = profile.name
    environment["AGENTPOST_CONSUMER_INSTANCE"] = lease.instance_id
    try:
        return subprocess.call(["agy", *antigravity_args], cwd=cwd, env=environment)
    except FileNotFoundError as exc:
        raise AgentPostError("Antigravity CLI not found") from exc
    finally:
        lease.release()


def _codex_remote_command(url: str, args: list[str]) -> list[str]:
    if args and args[0] in {"resume", "fork"}:
        return ["codex", args[0], "--remote", url, *args[1:]]
    return ["codex", "--remote", url, *args]


def _codex_bridge_marker(office: PostOffice, agent: str) -> Path:
    return office.root / "agents" / agent / "adapter" / "codex-bridge.active"


def _antigravity_profile(office: PostOffice, event: dict):
    override = os.environ.get("AGENTPOST_AGENT")
    workspaces = event.get("workspacePaths") or [Path.cwd()]
    ordered = sorted(
        (Path(item) for item in workspaces),
        key=lambda item: len(item.parts),
        reverse=True,
    )
    for workspace in ordered:
        try:
            return identify_agent(
                office,
                workspace,
                cli="antigravity",
                agent=override,
            )
        except (AgentPostError, OSError, ValueError):
            continue
    return None


def _antigravity_ledger(office: PostOffice, agent: str, event: dict) -> Path:
    conversation = str(event.get("conversationId", "unknown"))
    token = hashlib.sha256(conversation.encode("utf-8")).hexdigest()[:20]
    return office.root / "agents" / agent / "adapter" / f"antigravity-{token}.json"


def _antigravity_notified(path: Path) -> set[str]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return {str(item) for item in value.get("notified", [])}
    except (OSError, TypeError, AttributeError, json.JSONDecodeError):
        return set()


def _antigravity_presence_marker(office: PostOffice, agent: str) -> Path:
    return office.root / "agents" / agent / "adapter" / "antigravity-hook.active"


def _antigravity_empty_output(event_name: str) -> str:
    if event_name == "pre-invocation":
        return json.dumps({"injectSteps": []})
    return json.dumps({"decision": "stop"})


def _antigravity_instruction(agent: str, records: list) -> str:
    pointers = ", ".join(record.letter.message_id for record in records)
    return (
        f"AgentPost has {len(records)} unread message(s) for {agent}: {pointers}. "
        "Use the agentpost skill. Inspect exactly these IDs, claim each only when "
        "starting its work, reply by Message-ID, and give the user a short synopsis."
    )


def _free_loopback_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _wait_for_app_server(process: subprocess.Popen, port: int) -> None:
    deadline = time.monotonic() + 10
    captured = []
    while time.monotonic() < deadline:
        if process.poll() is not None:
            remainder = process.stdout.read() if process.stdout else ""
            detail = "".join((*captured, remainder)).strip()
            raise AgentPostError(f"Codex app-server exited during startup: {detail}")
        if process.stdout and select.select([process.stdout], [], [], 0.05)[0]:
            line = process.stdout.readline()
            captured.append(line)
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                return
        except OSError:
            pass
    raise AgentPostError("Codex app-server did not become ready within 10 seconds")


def _terminate(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3)


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


def _runtime_root() -> Path:
    return Path(os.environ.get("AGENTPOST_ROOT", "~/.agentpost")).expanduser()


def _claude_boundary_state() -> str:
    path = Path(os.environ["CLAUDE_PLUGIN_DATA"]) / "boundary.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        value = data.get("state")
        not_before = float(data.get("not_before", 0.0))
    except (FileNotFoundError, OSError, ValueError):
        return "idle"
    if value == "idle" and time.time() < not_before:
        return "busy"
    return value if value in {"busy", "idle"} else "idle"


def _emit_claude(record) -> None:
    letter = record.letter
    print(
        f"AgentPost {letter.notify} mail {letter.message_id} from "
        f"{letter.from_agent}. Process exactly this Message-ID with the "
        "agentpost skill; do not inspect unrelated unread mail.",
        flush=True,
    )
