from __future__ import annotations

import json
import os
import select
import shutil
import subprocess
import tempfile
import time
import tomllib
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

from .codex_generation import (
    CODEX_HOOK_GENERATION,
    CODEX_PLUGIN_ID,
    _installed_codex_generation,
    codex_generation_status,
)
from .codex_lock import CodexPluginLock
from .core import AgentPostError, PostOffice
from .presence import agent_presence
from .routing import identify_agent


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str


CODEX_USER_HOOK_COMMAND = "agentpost internal-codex-hook user-prompt-submit"
CODEX_USER_HOOK = {
    "type": "command",
    "command": CODEX_USER_HOOK_COMMAND,
    "statusMessage": "Checking AgentPost mail",
}


def install(
    office: PostOffice,
    cli: str,
    agent: str,
    project: Path,
    *,
    confirm_codex_sessions_closed: bool = False,
) -> None:
    project = project.expanduser().resolve()
    profile = identify_agent(office, project, cli=cli, agent=agent)
    source = _integration_source(cli)
    hook_snapshot = None
    codex_plan = None
    try:
        if cli == "claude":
            _run(
                ["claude", "plugin", "marketplace", "add", str(source), "--scope", "user"],
                cwd=project,
                allow_already=True,
            )
            _run(
                ["claude", "plugin", "marketplace", "update", "agentpost-local"],
                cwd=project,
            )
            _run(
                [
                    "claude",
                    "plugin",
                    "install",
                    "agentpost@agentpost-local",
                    "--scope",
                    "local",
                ],
                cwd=project,
                allow_already=True,
            )
            _run(
                [
                    "claude",
                    "plugin",
                    "update",
                    "agentpost@agentpost-local",
                    "--scope",
                    "local",
                ],
                cwd=project,
            )
            _run(
                [
                    "claude",
                    "plugin",
                    "enable",
                    "agentpost@agentpost-local",
                    "--scope",
                    "local",
                ],
                cwd=project,
                allow_already=True,
            )
        elif cli == "codex":
            codex_plan = _codex_install_plan(
                confirm_sessions_closed=confirm_codex_sessions_closed,
            )
            hook_snapshot = _snapshot_file(_codex_user_hooks_path())
            _install_codex_user_hook()
            _run(
                ["codex", "plugin", "marketplace", "add", str(source)],
                cwd=project,
                allow_already=True,
            )
            if codex_plan is not None and codex_plan.replace_plugin:
                _run(
                    ["codex", "plugin", "remove", CODEX_PLUGIN_ID],
                    cwd=project,
                    allow_missing=True,
                )
                _run(
                    ["codex", "plugin", "add", CODEX_PLUGIN_ID],
                    cwd=project,
                )
        elif cli == "antigravity":
            _run(
                ["agy", "plugin", "validate", str(source)],
                cwd=project,
            )
            _run(
                ["agy", "plugin", "uninstall", "agentpost"],
                cwd=project,
                allow_missing=True,
            )
            _run(
                ["agy", "plugin", "install", str(source)],
                cwd=project,
            )
        else:
            raise AgentPostError(f"unsupported installer: {cli}")
        office.bind_agent(profile.name, cli, project)
    except Exception:
        if hook_snapshot is not None:
            _restore_file(hook_snapshot)
        raise
    finally:
        if codex_plan is not None:
            codex_plan.release()
    if cli == "codex":
        try:
            print(
                "AgentPost refreshed the Codex plugin and user prompt hook. On first "
                "install, open `/hooks` and trust all three stable AgentPost hooks. "
                "Reload a process that predates the prompt hook, then complete one "
                "prompt to verify the active generation."
            )
        except BrokenPipeError:
            pass


def uninstall(
    cli: str,
    project: Path,
    *,
    confirm_codex_sessions_closed: bool = False,
) -> None:
    project = project.expanduser().resolve()
    plugin_lock = None
    if cli == "codex":
        plugin_lock = _codex_destructive_operation_lock(
            confirm_sessions_closed=confirm_codex_sessions_closed,
        )
    if cli == "claude":
        _run(
            [
                "claude",
                "plugin",
                "uninstall",
                "agentpost@agentpost-local",
                "--scope",
                "local",
                "--keep-data",
            ],
            cwd=project,
            allow_missing=True,
        )
    elif cli == "codex":
        try:
            _remove_codex_user_hook()
            _run(
                ["codex", "plugin", "remove", "agentpost@agentpost-local"],
                cwd=project,
                allow_missing=True,
            )
        finally:
            plugin_lock.release()
    elif cli == "antigravity":
        _run(
            ["agy", "plugin", "uninstall", "agentpost"],
            cwd=project,
            allow_missing=True,
        )
    else:
        raise AgentPostError(f"unsupported installer: {cli}")


def doctor(
    office: PostOffice,
    agent: str,
    project: Path,
    cli: str | None = None,
) -> tuple[Check, ...]:
    project = project.expanduser().resolve()
    checks = [
        Check("runtime", office.root.is_dir(), str(office.root)),
        Check("executable", shutil.which("agentpost") is not None, shutil.which("agentpost") or "not found"),
    ]
    try:
        profile = identify_agent(office, project, cli=cli, agent=agent)
        checks.append(Check("identity", profile.name == agent, f"resolved {profile.name}"))
    except (AgentPostError, OSError, ValueError) as exc:
        checks.append(Check("identity", False, str(exc)))
        return tuple(checks)

    checks.extend(
        (
            Check("mailbox", (office.root / "agents" / agent / "unread").is_dir(), agent),
            Check("project", project.is_dir(), str(project)),
        )
    )
    adapter_cli = _resolve_adapter_cli(office, profile.name, project, cli, profile.cli)
    if adapter_cli == "claude":
        checks.extend(_doctor_claude(project))
    elif adapter_cli == "codex":
        checks.extend(_doctor_codex(office, profile.name, project))
    elif adapter_cli == "python":
        checks.append(
            Check(
                "python-api",
                True,
                "embed agentpost.AgentRuntime and route notifications to the host scheduler",
            )
        )
    elif adapter_cli == "antigravity":
        checks.extend(_doctor_antigravity(project))
    else:
        checks.append(Check("adapter", False, f"unsupported CLI: {adapter_cli}"))
    return tuple(checks)


def armed(office: PostOffice, agent: str) -> tuple[bool, str]:
    value = agent_presence(office, agent)
    detail = value.detail
    if _agent_uses_codex(office, agent):
        generation = codex_generation_status(office, agent)
        if not generation.current:
            detail = f"{detail}; {generation.detail}"
    return value.active and value.healthy and value.wake_capable, detail


def _resolve_adapter_cli(
    office: PostOffice,
    agent: str,
    project: Path,
    requested: str | None,
    hint: str | None,
) -> str:
    if requested is not None:
        return requested
    matches = {
        binding.cli
        for binding in office.list_bindings()
        if binding.agent == agent and Path(binding.project) == project
    }
    if len(matches) == 1:
        return matches.pop()
    if hint is not None:
        return hint
    if matches:
        raise AgentPostError(
            f"multiple adapters are connected for {agent} at {project}; pass --cli"
        )
    raise AgentPostError(
        f"no adapter is connected for {agent} at {project}; pass --cli"
    )


def _doctor_claude(project: Path) -> tuple[Check, ...]:
    try:
        expected_version = _claude_plugin_version()
        result = subprocess.run(
            ["claude", "plugin", "list", "--json"],
            cwd=project,
            check=True,
            text=True,
            capture_output=True,
        )
        plugins = json.loads(result.stdout)
        matches = [
            item
            for item in plugins
            if item.get("id") == "agentpost@agentpost-local"
            and item.get("projectPath")
            and Path(item["projectPath"]).resolve() == project
        ]
        current = next(
            (
                item
                for item in matches
                if item.get("enabled") is True
                and item.get("version") == expected_version
            ),
            None,
        )
        if current is not None:
            detail = current.get("installPath", f"version {expected_version}")
            return (Check("claude-plugin", True, detail),)
        if not matches:
            detail = "not installed for this project"
        elif not any(item.get("enabled") is True for item in matches):
            detail = "installed but disabled for this project"
        else:
            versions = ", ".join(
                sorted({str(item.get("version", "unknown")) for item in matches})
            )
            detail = (
                f"stale version {versions}; expected {expected_version}; "
                "run agentpost install claude and restart Claude Code"
            )
        return (Check("claude-plugin", False, detail),)
    except (
        AgentPostError,
        OSError,
        subprocess.CalledProcessError,
        json.JSONDecodeError,
    ) as exc:
        return (Check("claude-plugin", False, str(exc)),)


def _claude_plugin_version() -> str:
    try:
        bundle = json.loads(
            files("agentpost").joinpath("data/integrations.json").read_text(
                encoding="utf-8"
            )
        )
        manifest = json.loads(
            bundle["claude/agentpost/.claude-plugin/plugin.json"]
        )
        version = manifest["version"]
    except (KeyError, OSError, TypeError, json.JSONDecodeError) as exc:
        raise AgentPostError(
            "packaged Claude integration version is unavailable"
        ) from exc
    if not isinstance(version, str) or not version:
        raise AgentPostError("packaged Claude integration version is invalid")
    return version


def _doctor_codex(
    office: PostOffice,
    agent: str,
    project: Path,
) -> tuple[Check, ...]:
    config_path = Path.home() / ".codex" / "config.toml"
    try:
        data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        return (Check("codex-config", False, str(exc)),)
    plugin = data.get("plugins", {}).get(CODEX_PLUGIN_ID, {})
    try:
        hooks = _list_codex_hooks(project)
        trusted_events, problems = _trusted_agentpost_hooks(hooks)
        trust_detail = f"{len(trusted_events)}/3 hooks trusted"
        if problems:
            trust_detail += "; " + ", ".join(problems)
    except AgentPostError as exc:
        trusted_events = set()
        trust_detail = str(exc)
    generation = codex_generation_status(office, agent)
    return (
        Check("codex-plugin", plugin.get("enabled") is True, "enabled" if plugin else "not installed"),
        Check(
            "codex-hook-trust",
            len(trusted_events) == 3,
            trust_detail
            + ("" if len(trusted_events) == 3 else "; open `/hooks` and trust all AgentPost hooks"),
        ),
        Check("codex-node", shutil.which("node") is not None, shutil.which("node") or "not found"),
        Check("codex-generation", generation.current, generation.detail),
    )


def _list_codex_hooks(project: Path, timeout: float = 5.0) -> list[dict]:
    executable = shutil.which("codex")
    if executable is None:
        raise AgentPostError("codex executable not found")
    try:
        process = subprocess.Popen(
            [executable, "app-server"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
    except OSError as exc:
        raise AgentPostError(f"cannot start Codex app server: {exc}") from exc
    try:
        _codex_app_server_send(
            process,
            {
                "method": "initialize",
                "id": 1,
                "params": {
                    "clientInfo": {
                        "name": "agentpost-doctor",
                        "title": "AgentPost Doctor",
                        "version": "0.0.17",
                    },
                    "capabilities": {
                        "experimentalApi": True,
                        "requestAttestation": False,
                        "optOutNotificationMethods": [],
                    },
                },
            },
        )
        _codex_app_server_response(process, 1, timeout)
        _codex_app_server_send(process, {"method": "initialized", "params": {}})
        _codex_app_server_send(
            process,
            {
                "method": "hooks/list",
                "id": 2,
                "params": {"cwds": [str(project.resolve())]},
            },
        )
        response = _codex_app_server_response(process, 2, timeout)
        if "error" in response:
            raise AgentPostError(f"Codex hooks/list failed: {response['error']}")
        records = response.get("result", {}).get("data", [])
        if not isinstance(records, list) or len(records) != 1:
            raise AgentPostError("Codex hooks/list returned an invalid workspace result")
        hooks = records[0].get("hooks", {})
        if not isinstance(hooks, list):
            raise AgentPostError("Codex hooks/list returned an invalid hook list")
        return [hook for hook in hooks if isinstance(hook, dict)]
    finally:
        process.terminate()
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=1)


def _codex_app_server_send(process: subprocess.Popen, message: dict) -> None:
    if process.stdin is None:
        raise AgentPostError("Codex app server stdin is unavailable")
    try:
        process.stdin.write(json.dumps(message) + "\n")
        process.stdin.flush()
    except (BrokenPipeError, OSError) as exc:
        raise AgentPostError(f"Codex app server closed unexpectedly: {exc}") from exc


def _codex_app_server_response(
    process: subprocess.Popen,
    request_id: int,
    timeout: float,
) -> dict:
    if process.stdout is None:
        raise AgentPostError("Codex app server stdout is unavailable")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        readable, _, _ = select.select([process.stdout], [], [], remaining)
        if not readable:
            break
        line = process.stdout.readline()
        if not line:
            break
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(message, dict) and message.get("id") == request_id:
            return message
    raise AgentPostError(f"Codex app server timed out waiting for request {request_id}")


def _trusted_agentpost_hooks(hooks: list[dict]) -> tuple[set[str], list[str]]:
    expected = {
        "userPromptSubmit": (None, CODEX_USER_HOOK_COMMAND),
        "sessionStart": (CODEX_PLUGIN_ID, "agentpost internal-codex-hook session-start"),
        "stop": (CODEX_PLUGIN_ID, "agentpost internal-codex-hook stop"),
    }
    trusted: set[str] = set()
    problems: list[str] = []
    for event, (plugin_id, command) in expected.items():
        matches = [
            hook
            for hook in hooks
            if hook.get("eventName") == event
            and hook.get("pluginId") == plugin_id
            and hook.get("command") == command
        ]
        if not matches:
            problems.append(f"{event} missing")
        elif any(
            hook.get("enabled") is True and hook.get("trustStatus") == "trusted"
            for hook in matches
        ):
            trusted.add(event)
        else:
            problems.append(f"{event} not trusted")
    return trusted, problems


def _agent_uses_codex(office: PostOffice, agent: str) -> bool:
    try:
        profile = office.load_profile(agent)
    except (AgentPostError, OSError, ValueError):
        return False
    if profile.cli == "codex":
        return True
    return any(
        binding.agent == agent and binding.cli == "codex"
        for binding in office.list_bindings()
    )


def _install_codex_user_hook(home: Path | None = None) -> None:
    path = _codex_user_hooks_path(home)
    data = _read_codex_user_hooks(path)
    hooks = data.setdefault("hooks", {})
    groups = hooks.setdefault("UserPromptSubmit", [])
    if not isinstance(groups, list):
        raise AgentPostError(f"invalid UserPromptSubmit groups in {path}")

    found = False
    for group in groups:
        if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
            raise AgentPostError(f"invalid UserPromptSubmit hook group in {path}")
        handlers = []
        for handler in group["hooks"]:
            if not isinstance(handler, dict):
                raise AgentPostError(f"invalid UserPromptSubmit handler in {path}")
            if _is_agentpost_user_hook(handler):
                if not found:
                    handlers.append(dict(CODEX_USER_HOOK))
                    found = True
            else:
                handlers.append(handler)
        group["hooks"] = handlers
    if not found:
        groups.append({"hooks": [dict(CODEX_USER_HOOK)]})
    _atomic_json_file(path, data)


def _remove_codex_user_hook(home: Path | None = None) -> None:
    path = _codex_user_hooks_path(home)
    if not path.exists():
        return
    data = _read_codex_user_hooks(path)
    hooks = data.get("hooks", {})
    groups = hooks.get("UserPromptSubmit", [])
    if not isinstance(groups, list):
        raise AgentPostError(f"invalid UserPromptSubmit groups in {path}")
    retained = []
    for group in groups:
        if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
            raise AgentPostError(f"invalid UserPromptSubmit hook group in {path}")
        handlers = [
            handler
            for handler in group["hooks"]
            if not (isinstance(handler, dict) and _is_agentpost_user_hook(handler))
        ]
        if handlers:
            retained.append({**group, "hooks": handlers})
    if retained:
        hooks["UserPromptSubmit"] = retained
    else:
        hooks.pop("UserPromptSubmit", None)
    _atomic_json_file(path, data)


def _codex_user_hooks_path(home: Path | None = None) -> Path:
    return (home or Path.home()) / ".codex" / "hooks.json"


def _read_codex_user_hooks(path: Path) -> dict:
    if not path.exists():
        return {"hooks": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AgentPostError(f"cannot read Codex user hooks {path}: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("hooks", {}), dict):
        raise AgentPostError(f"invalid Codex user hooks document: {path}")
    return data


def _is_agentpost_user_hook(handler: dict) -> bool:
    command = handler.get("command")
    return isinstance(command, str) and command.startswith(
        "agentpost internal-codex-hook user-prompt-submit"
    )


def _atomic_json_file(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}-")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _snapshot_file(path: Path) -> tuple[Path, bytes | None]:
    return path, path.read_bytes() if path.exists() else None


def _restore_file(snapshot: tuple[Path, bytes | None]) -> None:
    path, contents = snapshot
    if contents is None:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}-")
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(contents)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


@dataclass
class _CodexInstallPlan:
    replace_plugin: bool
    lock: CodexPluginLock | None = None

    def release(self) -> None:
        if self.lock is not None:
            self.lock.release()


@dataclass(frozen=True)
class _CodexInstallState:
    kind: str
    generation: str | None
    detail: str


def _codex_install_state(home: Path) -> _CodexInstallState:
    config_path = home / ".codex/config.toml"
    try:
        config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        config = {}
    except (OSError, tomllib.TOMLDecodeError) as exc:
        return _CodexInstallState("ambiguous", None, f"Codex config: {exc}")
    plugins = config.get("plugins", {})
    if not isinstance(plugins, dict):
        return _CodexInstallState(
            "ambiguous", None, "Codex config: plugins is not a table"
        )
    has_plugin_entry = CODEX_PLUGIN_ID in plugins
    if has_plugin_entry and not isinstance(plugins[CODEX_PLUGIN_ID], dict):
        return _CodexInstallState(
            "ambiguous", None, "Codex config: AgentPost plugin entry is not a table"
        )

    cache = home / ".codex/plugins/cache/agentpost-local/agentpost"
    try:
        entries = tuple(cache.iterdir())
    except FileNotFoundError:
        entries = ()
    except OSError as exc:
        return _CodexInstallState("ambiguous", None, f"Codex cache: {exc}")
    if not has_plugin_entry and not entries:
        return _CodexInstallState(
            "absent", None, "no existing AgentPost Codex plugin state"
        )

    installed, problem = _installed_codex_generation(home)
    if installed == CODEX_HOOK_GENERATION:
        return _CodexInstallState(
            "current", installed, f"installed generation {installed}"
        )
    if installed is not None:
        return _CodexInstallState(
            "upgrade", installed, f"installed generation {installed}"
        )
    return _CodexInstallState(
        "ambiguous",
        None,
        f"ambiguous AgentPost Codex installation: {problem}",
    )


def _require_codex_replacement_acknowledgement(
    state: _CodexInstallState,
    *,
    confirm_sessions_closed: bool,
) -> None:
    if state.kind == "absent":
        return
    if os.environ.get("CODEX_THREAD_ID"):
        raise AgentPostError(
            "Codex plugin replacement cannot run inside a Codex thread; close all "
            f"Codex sessions and run it from a terminal (installed state: {state.detail})"
        )
    if not confirm_sessions_closed:
        raise AgentPostError(
            "Codex plugin replacement requires confirmation that every unmanaged "
            "Codex session is closed; rerun from a terminal with "
            f"--confirm-codex-sessions-closed (installed state: {state.detail})"
        )


def _codex_destructive_operation_lock(
    *,
    confirm_sessions_closed: bool,
    home: Path | None = None,
) -> CodexPluginLock:
    if os.environ.get("CODEX_THREAD_ID"):
        raise AgentPostError(
            "Codex plugin removal cannot run inside a Codex thread; close all "
            "Codex sessions and run it from a terminal"
        )
    if not confirm_sessions_closed:
        raise AgentPostError(
            "Codex plugin removal requires confirmation that every unmanaged "
            "Codex session is closed; rerun from a terminal with "
            "--confirm-codex-sessions-closed"
        )
    lock = CodexPluginLock(home or Path.home())
    if lock.acquire_exclusive():
        return lock
    raise AgentPostError(
        "Codex plugin removal is blocked by a managed Codex session; close all "
        "Codex sessions and retry from a terminal"
    )


def _codex_install_plan(
    *,
    confirm_sessions_closed: bool,
    home: Path | None = None,
) -> _CodexInstallPlan:
    home = home or Path.home()
    state = _codex_install_state(home)
    if state.kind == "current":
        lock = CodexPluginLock(home)
        if not lock.acquire_shared():
            raise AgentPostError(
                "Codex plugin state is changing; retry the install after it completes"
            )
        locked_state = _codex_install_state(home)
        if locked_state.kind == "current":
            return _CodexInstallPlan(False, lock)
        lock.release()
        state = locked_state

    _require_codex_replacement_acknowledgement(
        state,
        confirm_sessions_closed=confirm_sessions_closed,
    )
    lock = CodexPluginLock(home)
    if not lock.acquire_exclusive():
        raise AgentPostError(
            "Codex plugin replacement is blocked by a managed Codex session; close "
            "all Codex sessions and retry from a terminal"
        )
    try:
        locked_state = _codex_install_state(home)
        if locked_state.kind == "current":
            lock.release()
            return _codex_install_plan(
                confirm_sessions_closed=confirm_sessions_closed,
                home=home,
            )
        _require_codex_replacement_acknowledgement(
            locked_state,
            confirm_sessions_closed=confirm_sessions_closed,
        )
    except Exception:
        lock.release()
        raise
    return _CodexInstallPlan(True, lock)


def _doctor_antigravity(project: Path) -> tuple[Check, ...]:
    executable = shutil.which("agy")
    if executable is None:
        return (Check("antigravity-cli", False, "agy not found"),)
    try:
        version = subprocess.run(
            ["agy", "--version"],
            cwd=project,
            check=True,
            text=True,
            capture_output=True,
        ).stdout.strip()
        plugin_output = subprocess.run(
            ["agy", "plugin", "list"],
            cwd=project,
            check=True,
            text=True,
            capture_output=True,
        ).stdout
        plugins = json.loads(plugin_output)
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        return (Check("antigravity-cli", False, str(exc)),)
    installed = any(
        item.get("name") == "agentpost" for item in plugins.get("imports", [])
    )
    return (
        Check("antigravity-cli", True, version or executable),
        Check(
            "antigravity-plugin",
            installed,
            "installed" if installed else "not installed",
        ),
        Check(
            "antigravity-capability",
            True,
            "lifecycle catch-up; already-idle external wake unsupported",
        ),
    )


def _integration_source(cli: str) -> Path:
    repository = Path(__file__).resolve().parents[2]
    source = repository / "integrations" / cli
    if source.is_dir():
        return source
    try:
        bundle = json.loads(
            files("agentpost").joinpath("data/integrations.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise AgentPostError("packaged integration templates are unavailable") from exc
    destination = Path.home() / ".local" / "share" / "agentpost" / "integrations" / cli
    prefix = f"{cli}/"
    selected = {name[len(prefix):]: content for name, content in bundle.items() if name.startswith(prefix)}
    if not selected:
        raise AgentPostError(f"packaged integration templates are missing for {cli}")
    if destination.exists():
        shutil.rmtree(destination)
    for relative, content in selected.items():
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists() or target.read_text(encoding="utf-8") != content:
            target.write_text(content, encoding="utf-8")
    return destination


def _run(
    command: list[str],
    *,
    cwd: Path,
    allow_already: bool = False,
    allow_missing: bool = False,
) -> None:
    try:
        result = subprocess.run(command, cwd=cwd, text=True, capture_output=True)
    except FileNotFoundError as exc:
        raise AgentPostError(f"required CLI not found: {command[0]}") from exc
    if result.returncode == 0:
        if result.stdout.strip():
            print(result.stdout.strip())
        return
    detail = (result.stderr or result.stdout).strip()
    lowered = detail.lower()
    if allow_already and ("already" in lowered or "exists" in lowered):
        return
    if allow_missing and ("not installed" in lowered or "not found" in lowered):
        return
    raise AgentPostError(f"{' '.join(command)} failed: {detail}")
