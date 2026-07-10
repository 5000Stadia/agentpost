from __future__ import annotations

import json
import shutil
import subprocess
import tomllib
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

from .core import AgentPostError, PostOffice
from .presence import agent_presence
from .routing import identify_agent


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str


def install(office: PostOffice, cli: str, agent: str, project: Path) -> None:
    project = project.expanduser().resolve()
    profile = identify_agent(office, project, cli=cli, agent=agent)
    office.bind_agent(profile.name, cli, project)
    source = _integration_source(cli)
    if cli == "claude":
        _run(
            ["claude", "plugin", "marketplace", "add", str(source), "--scope", "user"],
            cwd=project,
            allow_already=True,
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
    elif cli == "codex":
        _run(
            ["codex", "plugin", "marketplace", "add", str(source)],
            cwd=project,
            allow_already=True,
        )
        _run(
            ["codex", "plugin", "add", "agentpost@agentpost-local"],
            cwd=project,
            allow_already=True,
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


def uninstall(cli: str, project: Path) -> None:
    project = project.expanduser().resolve()
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
        _run(
            ["codex", "plugin", "remove", "agentpost@agentpost-local"],
            cwd=project,
            allow_missing=True,
        )
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
    if profile.cli == "claude":
        checks.extend(_doctor_claude(project))
    elif profile.cli == "codex":
        checks.extend(_doctor_codex())
    elif profile.cli == "python":
        checks.append(
            Check(
                "python-api",
                True,
                "embed agentpost.AgentRuntime and route notifications to the host scheduler",
            )
        )
    elif profile.cli == "antigravity":
        checks.extend(_doctor_antigravity(project))
    else:
        checks.append(Check("adapter", False, f"unsupported CLI: {profile.cli}"))
    return tuple(checks)


def armed(office: PostOffice, agent: str) -> tuple[bool, str]:
    profile = office.load_profile(agent)
    if profile.cli == "antigravity":
        return (
            False,
            "Antigravity lifecycle catch-up only; already-idle external wake unsupported",
        )
    value = agent_presence(office, agent)
    return value.active and value.healthy, value.detail


def _doctor_claude(project: Path) -> tuple[Check, ...]:
    try:
        result = subprocess.run(
            ["claude", "plugin", "list", "--json"],
            cwd=project,
            check=True,
            text=True,
            capture_output=True,
        )
        plugins = json.loads(result.stdout)
        matches = [item for item in plugins if item.get("id") == "agentpost@agentpost-local"]
        enabled = any(item.get("enabled") for item in matches)
        detail = matches[0].get("installPath", "installed") if matches else "not installed"
        return (Check("claude-plugin", enabled, detail),)
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        return (Check("claude-plugin", False, str(exc)),)


def _doctor_codex() -> tuple[Check, ...]:
    config_path = Path.home() / ".codex" / "config.toml"
    try:
        data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        return (Check("codex-config", False, str(exc)),)
    plugin = data.get("plugins", {}).get("agentpost@agentpost-local", {})
    hooks = data.get("hooks", {}).get("state", {})
    trusted = {
        key
        for key, value in hooks.items()
        if key.startswith("agentpost@agentpost-local:") and value.get("trusted_hash")
    }
    return (
        Check("codex-plugin", plugin.get("enabled") is True, "enabled" if plugin else "not installed"),
        Check("codex-hook-trust", len(trusted) >= 2, f"{len(trusted)}/2 hook records trusted"),
        Check("codex-node", shutil.which("node") is not None, shutil.which("node") or "not found"),
    )


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
