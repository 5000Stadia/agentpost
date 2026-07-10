from __future__ import annotations

import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


class DocumentationExampleTest(unittest.TestCase):
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
