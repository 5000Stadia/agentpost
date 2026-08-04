from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .core import PostOffice


CODEX_PLUGIN_ID = "agentpost@agentpost-local"
CODEX_HOOK_GENERATION = "0.0.7+codex.20260804015728"
CODEX_HOOK_EVENTS = ("session-start", "user-prompt-submit", "stop")
CODEX_STABLE_DISPATCH_MIN_RELEASE = (0, 0, 3)
_CODEX_GENERATION_RE = re.compile(
    r"^(\d+)\.(\d+)\.(\d+)(?:\+codex\.(\d{14}))?$"
)


@dataclass(frozen=True)
class CodexGenerationStatus:
    state: str
    installed: str | None
    observed: dict[str, str]
    detail: str

    @property
    def current(self) -> bool:
        return self.state == "current"


def codex_generation_release(generation: str) -> tuple[int, int, int] | None:
    match = _CODEX_GENERATION_RE.fullmatch(generation)
    if match is None:
        return None
    return tuple(int(value) for value in match.groups()[:3])


def codex_newer_generation_is_compatible(
    installed: str,
    expected: str,
) -> bool:
    installed_release = codex_generation_release(installed)
    expected_release = codex_generation_release(expected)
    if installed_release is None or expected_release is None:
        return False
    if (
        installed_release[:2] != expected_release[:2]
        or expected_release < CODEX_STABLE_DISPATCH_MIN_RELEASE
    ):
        return False
    if installed_release > expected_release:
        return True
    if installed_release != expected_release:
        return False
    installed_match = _CODEX_GENERATION_RE.fullmatch(installed)
    expected_match = _CODEX_GENERATION_RE.fullmatch(expected)
    installed_stamp = installed_match.group(4) if installed_match else None
    expected_stamp = expected_match.group(4) if expected_match else None
    return bool(
        installed_stamp
        and expected_stamp
        and installed_stamp > expected_stamp
    )


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
