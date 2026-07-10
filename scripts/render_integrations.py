#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "integrations" / "shared" / "agentpost" / "SKILL.md"
TARGETS = (
    ROOT
    / "integrations"
    / "claude"
    / "agentpost"
    / "skills"
    / "agentpost"
    / "SKILL.md",
    ROOT
    / "integrations"
    / "codex"
    / "plugins"
    / "agentpost"
    / "skills"
    / "agentpost"
    / "SKILL.md",
    ROOT
    / "integrations"
    / "antigravity"
    / "skills"
    / "agentpost"
    / "SKILL.md",
)


def main() -> None:
    for target in TARGETS:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(SOURCE, target)
    bundle = {}
    for cli in ("antigravity", "claude", "codex"):
        root = ROOT / "integrations" / cli
        for path in sorted(root.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                relative = path.relative_to(ROOT / "integrations")
                bundle[str(relative)] = path.read_text(encoding="utf-8")
    destination = ROOT / "src" / "agentpost" / "data" / "integrations.json"
    destination.write_text(
        json.dumps(bundle, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
