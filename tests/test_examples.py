from __future__ import annotations

import os
import json
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


class DocumentationExampleTest(unittest.TestCase):
    def test_bootstrap_installer_is_valid_posix_shell(self) -> None:
        subprocess.run(
            ["sh", "-n", str(ROOT / "scripts" / "install.sh")],
            cwd=ROOT,
            check=True,
        )

    def test_antigravity_plugin_uses_the_shared_skill_and_valid_hooks(self) -> None:
        shared = ROOT / "integrations" / "shared" / "agentpost" / "SKILL.md"
        generated = (
            ROOT
            / "integrations"
            / "antigravity"
            / "skills"
            / "agentpost"
            / "SKILL.md"
        )
        self.assertEqual(
            generated.read_text(encoding="utf-8"),
            shared.read_text(encoding="utf-8"),
        )
        plugin = json.loads(
            (ROOT / "integrations" / "antigravity" / "plugin.json").read_text(
                encoding="utf-8"
            )
        )
        hooks = json.loads(
            (ROOT / "integrations" / "antigravity" / "hooks.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(plugin["name"], "agentpost")
        self.assertIn("PreInvocation", hooks["agentpost"])
        self.assertIn("Stop", hooks["agentpost"])

    def test_two_agent_quickstart_smoke(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            wrapper = Path(temporary) / "agentpost"
            wrapper.write_text(
                "#!/usr/bin/env bash\n"
                f"exec {shlex.quote(sys.executable)} -m agentpost.cli \"$@\"\n",
                encoding="utf-8",
            )
            wrapper.chmod(0o755)
            environment = os.environ.copy()
            environment["AGENTPOST_BIN"] = str(wrapper)
            environment["PYTHONPATH"] = str(ROOT / "src")
            result = subprocess.run(
                [str(ROOT / "scripts" / "smoke_two_agents.sh")],
                cwd=ROOT,
                env=environment,
                text=True,
                capture_output=True,
                check=True,
            )
        self.assertIn("TWO-AGENT-SMOKE\tPASS", result.stdout)


if __name__ == "__main__":
    unittest.main()
