#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts" / "install.sh"


def run(command: list[str], *, environment: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        cwd=ROOT,
        env=environment,
        check=True,
        text=True,
        capture_output=True,
    )


def snapshot_tree(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def verify(interpreter: str, expected_version: str) -> str:
    executable = shutil.which(interpreter) if os.sep not in interpreter else interpreter
    if executable is None or not Path(executable).is_file():
        raise RuntimeError(f"Python interpreter not found: {interpreter}")
    executable = str(Path(executable).resolve())
    source_runtime = json.loads(
        subprocess.check_output(
            [executable, "-c", "import json,sys; print(json.dumps(sys.version_info[:2]))"],
            text=True,
        )
    )
    if tuple(source_runtime) < (3, 11):
        raise RuntimeError(f"Python 3.11+ is required, found {source_runtime}")

    with tempfile.TemporaryDirectory(prefix="agentpost-clean-install-") as temporary:
        base = Path(temporary)
        home = base / "home"
        install_dir = base / "install"
        bin_dir = base / "bin"
        runtime = base / "runtime"
        home.mkdir()
        environment = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("AGENTPOST_")
            and key not in {"PYTHON", "PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV"}
        }
        environment.update(
            {
                "HOME": str(home),
                "PYTHON": executable,
                "AGENTPOST_INSTALL_DIR": str(install_dir),
                "AGENTPOST_BIN_DIR": str(bin_dir),
                "AGENTPOST_ROOT": str(runtime),
                "AGENTPOST_SOURCE": str(ROOT),
                "AGENTPOST_CONNECTION_MODE": "manual",
                "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            }
        )

        first = run(["sh", str(INSTALLER)], environment=environment)
        command = bin_dir / "agentpost"
        installed_python = install_dir / "bin" / "python"
        if not command.is_symlink() or command.resolve() != (install_dir / "bin" / "agentpost"):
            raise AssertionError("bootstrap did not create the expected agentpost symlink")
        probe = json.loads(
            run(
                [
                    str(installed_python),
                    "-c",
                    (
                        "import importlib.metadata,json,sys; "
                        "print(json.dumps({'version': importlib.metadata.version('agentpost'), "
                        "'python': list(sys.version_info[:2])}))"
                    ),
                ],
                environment=environment,
            ).stdout
        )
        if probe != {"version": expected_version, "python": source_runtime}:
            raise AssertionError(f"installed runtime mismatch: {probe}")
        for name in ("agents", "bindings"):
            if not (runtime / name).is_dir():
                raise AssertionError(f"bootstrap omitted runtime directory: {name}")
        config = (runtime / "config.toml").read_text(encoding="utf-8")
        if 'connection_mode = "manual"' not in config:
            raise AssertionError("bootstrap did not apply the requested connection mode")
        if "AgentPost installed:" not in first.stdout:
            raise AssertionError("bootstrap did not print its installation receipt")

        project = base / "project"
        exclude = project / ".git" / "info" / "exclude"
        exclude.parent.mkdir(parents=True)
        exclude.write_text("unrelated-pattern\n", encoding="ascii")
        fixture = """
import os
import sys
from agentpost import PostOffice, Profile

office = PostOffice(os.environ["AGENTPOST_ROOT"])
for name in ("sender", "recipient"):
    office.register_profile(Profile(
        name=name,
        display_name=name.title(),
        kind="project",
        summary=f"Clean install fixture {name}",
        projects=(name,),
    ))
office.set_group("fixture-team", ("sender", "recipient"))
office.bind_agent("recipient", "python", sys.argv[1])
office.send("sender", "recipient", "preserve unread")
claimed = office.send("recipient", "sender", "preserve read")
office.claim("sender", claimed.message_id)
"""
        run(
            [str(installed_python), "-c", fixture, str(project)],
            environment=environment,
        )
        runtime_before = snapshot_tree(runtime)
        project_before = snapshot_tree(project)
        required_fragments = (
            "profile.toml",
            "/unread/",
            "/read/",
            "/sent/",
            "bindings/",
            "config.toml",
        )
        paths = tuple(runtime_before)
        for fragment in required_fragments:
            if not any(fragment in path for path in paths):
                raise AssertionError(f"preservation fixture omitted {fragment}")
        if ".agentpost.toml" not in project_before or ".git/info/exclude" not in project_before:
            raise AssertionError("preservation fixture omitted workspace identity state")

        run(["sh", str(INSTALLER)], environment=environment)
        if snapshot_tree(runtime) != runtime_before:
            raise AssertionError("idempotent bootstrap changed durable runtime state")
        if snapshot_tree(project) != project_before:
            raise AssertionError("idempotent bootstrap changed workspace identity state")

    return f"PASS Python {source_runtime[0]}.{source_runtime[1]} clean bootstrap"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("interpreters", nargs="*", default=[sys.executable])
    args = parser.parse_args(argv)
    with (ROOT / "pyproject.toml").open("rb") as handle:
        expected_version = str(tomllib.load(handle)["project"]["version"])
    for interpreter in args.interpreters:
        print(verify(interpreter, expected_version))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
