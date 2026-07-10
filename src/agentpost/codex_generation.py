from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .core import PostOffice


CODEX_PLUGIN_ID = "agentpost@agentpost-local"
CODEX_HOOK_GENERATION = "0.0.3+codex.20260710221500"
CODEX_HOOK_EVENTS = ("session-start", "user-prompt-submit", "stop")


@dataclass(frozen=True)
class CodexGenerationStatus:
    state: str
    installed: str | None
    observed: dict[str, str]
    detail: str

    @property
    def current(self) -> bool:
        return self.state == "current"


def codex_hook_marker(office: PostOffice, agent: str, event: str) -> Path:
    return (
        office.root
        / "agents"
        / agent
        / "adapter"
        / "codex-hooks"
        / f"{event}.json"
    )


def codex_generation_status(
    office: PostOffice,
    agent: str,
    *,
    home: Path | None = None,
) -> CodexGenerationStatus:
    installed, problem = _installed_codex_generation(home or Path.home())
    observed = {
        event: generation
        for event in CODEX_HOOK_EVENTS
        if (
            generation := _observed_codex_generation(
                codex_hook_marker(office, agent, event)
            )
        )
        is not None
    }
    remediation = (
        "approve AgentPost hooks in `/hooks`; rerun `agentpost install codex "
        f"--agent {agent} --project PROJECT` if the cache is stale; reload Codex "
        "if required events remain unobserved"
    )
    if installed is None:
        return CodexGenerationStatus(
            "unknown",
            None,
            observed,
            f"installed Codex generation unknown ({problem}); {remediation}",
        )
    stale = {
        event: generation
        for event, generation in observed.items()
        if generation != installed
    }
    if stale:
        mismatches = ", ".join(
            f"{event}={generation}" for event, generation in sorted(stale.items())
        )
        return CodexGenerationStatus(
            "stale",
            installed,
            observed,
            f"Codex observed stale hooks ({mismatches}), installed {installed}; "
            f"{remediation}",
        )
    missing = [event for event in CODEX_HOOK_EVENTS if event not in observed]
    if missing:
        return CodexGenerationStatus(
            "unobserved",
            installed,
            observed,
            f"Codex generation {installed} has not executed events: "
            f"{', '.join(missing)}; {remediation}",
        )
    return CodexGenerationStatus(
        "current",
        installed,
        observed,
        f"all three hooks observed installed generation {installed}",
    )


def _installed_codex_generation(home: Path) -> tuple[str | None, str]:
    config_path = home / ".codex" / "config.toml"
    try:
        config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        return None, str(exc)
    plugin = config.get("plugins", {}).get(CODEX_PLUGIN_ID, {})
    if plugin.get("enabled") is not True:
        return None, "plugin is not enabled"

    cache = home / ".codex" / "plugins" / "cache" / "agentpost-local" / "agentpost"
    try:
        directories = tuple(path for path in cache.iterdir() if path.is_dir())
    except OSError as exc:
        return None, str(exc)
    if len(directories) != 1:
        return None, f"expected one enabled cache generation, found {len(directories)}"

    candidates: list[str] = []
    for directory in directories:
        manifest = directory / ".codex-plugin" / "plugin.json"
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        version = data.get("version")
        if (
            data.get("name") == "agentpost"
            and isinstance(version, str)
            and version
            and directory.name == version
        ):
            candidates.append(version)
    if len(candidates) != 1:
        return None, "enabled cache generation has a missing or malformed manifest"
    return candidates[0], ""


def _observed_codex_generation(marker: Path) -> str | None:
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    generation = data.get("generation")
    return generation if isinstance(generation, str) and generation else None
