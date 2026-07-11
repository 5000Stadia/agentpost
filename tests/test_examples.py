from __future__ import annotations

import os
import base64
import hashlib
import json
import select
import shlex
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agentpost.codex_generation import CODEX_HOOK_GENERATION  # noqa: E402
from agentpost import PostOffice, Profile  # noqa: E402
from agentpost.installer import _claude_plugin_version  # noqa: E402


class DocumentationExampleTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
    def test_codex_bridge_batches_all_startup_unread_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "post"
            project = base / "shared-project"
            project.mkdir()
            office = PostOffice(root)
            for name in ("c", "cr"):
                office.register_profile(
                    Profile(
                        name=name,
                        display_name=name.upper(),
                        cli="codex",
                        kind="role",
                        summary=f"Role {name}",
                        roles=("review",),
                        project_roots=(str(project),),
                    )
                )
            message_ids = [
                office.send("c", "cr", f"queued-{index}").message_id
                for index in range(3)
            ]
            startup_attention = office.request_notification(
                "c", "cr", message_ids[0], notify="immediate"
            )

            bin_dir = base / "bin"
            bin_dir.mkdir()
            agentpost = bin_dir / "agentpost"
            agentpost.write_text(
                "#!/bin/sh\nexec "
                + shlex.quote(sys.executable)
                + " -c 'from agentpost.cli import main; raise SystemExit(main())' \"$@\"\n",
                encoding="ascii",
            )
            agentpost.chmod(0o755)
            environment = os.environ.copy()
            environment["AGENTPOST_ROOT"] = str(root)
            environment["AGENTPOST_AGENT"] = "cr"
            environment["PYTHONPATH"] = str(ROOT / "src")
            environment["PATH"] = str(bin_dir) + os.pathsep + environment.get("PATH", "")

            listener = socket.socket()
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            listener.settimeout(5)
            port = listener.getsockname()[1]
            bridge = ROOT / "src/agentpost/data/codex_bridge.mjs"
            process = subprocess.Popen(
                [
                    "node",
                    str(bridge),
                    "--url",
                    f"ws://127.0.0.1:{port}",
                    "--agent",
                    "cr",
                    "--root",
                    str(root),
                    "--cwd",
                    str(project),
                    "--log",
                    str(base / "bridge.log"),
                    "--presence",
                    str(base / "presence.json"),
                    "--owner-pid",
                    str(os.getpid()),
                    "--instance-id",
                    "startup-batch-test",
                ],
                cwd=project,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            connection = None
            try:
                connection, _ = listener.accept()
                connection.settimeout(5)
                request = b""
                while b"\r\n\r\n" not in request:
                    request += connection.recv(4096)
                headers = request.decode("ascii").split("\r\n")
                key = next(
                    line.split(":", 1)[1].strip()
                    for line in headers
                    if line.lower().startswith("sec-websocket-key:")
                )
                accept = base64.b64encode(
                    hashlib.sha1(
                        (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")
                    ).digest()
                ).decode("ascii")
                connection.sendall(
                    (
                        "HTTP/1.1 101 Switching Protocols\r\n"
                        "Upgrade: websocket\r\n"
                        "Connection: Upgrade\r\n"
                        f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
                    ).encode("ascii")
                )

                def receive_exact(size: int) -> bytes:
                    data = b""
                    while len(data) < size:
                        data += connection.recv(size - len(data))
                    return data

                def receive_json() -> dict:
                    first, second = receive_exact(2)
                    length = second & 0x7F
                    if length == 126:
                        length = struct.unpack("!H", receive_exact(2))[0]
                    elif length == 127:
                        length = struct.unpack("!Q", receive_exact(8))[0]
                    mask = receive_exact(4) if second & 0x80 else b""
                    payload = receive_exact(length)
                    if mask:
                        payload = bytes(value ^ mask[i % 4] for i, value in enumerate(payload))
                    self.assertEqual(first & 0x0F, 1)
                    return json.loads(payload)

                def send_json(value: dict) -> None:
                    payload = json.dumps(value).encode("utf-8")
                    if len(payload) < 126:
                        header = bytes((0x81, len(payload)))
                    else:
                        header = bytes((0x81, 126)) + struct.pack("!H", len(payload))
                    connection.sendall(header + payload)

                turn = None
                deadline = time.monotonic() + 10
                while turn is None and time.monotonic() < deadline:
                    message = receive_json()
                    if message.get("method") == "initialize":
                        send_json({"id": message["id"], "result": {}})
                    elif message.get("method") == "thread/loaded/list":
                        send_json({"id": message["id"], "result": {"data": ["thread-1"]}})
                    elif message.get("method") == "turn/start":
                        turn = message
                        send_json({"id": message["id"], "result": {"turn": {"id": "turn-1"}}})
                self.assertIsNotNone(turn)
                instruction = turn["params"]["input"][0]["text"]
                for message_id in message_ids:
                    self.assertEqual(instruction.count(message_id), 1)
                deadline = time.monotonic() + 5
                while startup_attention.path.exists() and time.monotonic() < deadline:
                    time.sleep(0.05)
                self.assertFalse(startup_attention.path.exists())

                def assert_no_turn_start(duration: float) -> None:
                    deadline = time.monotonic() + duration
                    while time.monotonic() < deadline:
                        ready, _, _ = select.select([connection], [], [], 0.05)
                        if not ready:
                            continue
                        message = receive_json()
                        self.assertNotEqual(message.get("method"), "turn/start")

                send_json(
                    {
                        "method": "turn/completed",
                        "params": {"threadId": "thread-1", "turn": {"id": "turn-1"}},
                    }
                )
                assert_no_turn_start(0.5)

                send_json(
                    {
                        "method": "turn/started",
                        "params": {
                            "threadId": "thread-1",
                            "turn": {"id": "user-turn"},
                        },
                    }
                )
                deferred = office.send("c", "cr", "deferred base", notify="idle")
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    log = (base / "bridge.log").read_text(encoding="utf-8")
                    if "deferred-idle" in log and deferred.message_id in log:
                        break
                    time.sleep(0.05)
                else:
                    self.fail("base delivery was not deferred while the turn was active")

                request_attention = office.request_notification(
                    "c", "cr", deferred.message_id, notify="immediate"
                )
                steer = None
                deadline = time.monotonic() + 5
                while steer is None and time.monotonic() < deadline:
                    message = receive_json()
                    if message.get("method") == "turn/steer":
                        steer = message
                        send_json({"id": message["id"], "result": {}})
                self.assertIsNotNone(steer)
                self.assertEqual(
                    steer["params"]["input"][0]["text"].count(deferred.message_id),
                    1,
                )
                deadline = time.monotonic() + 5
                while request_attention.path.exists() and time.monotonic() < deadline:
                    time.sleep(0.05)
                self.assertFalse(request_attention.path.exists())
                send_json(
                    {
                        "method": "turn/completed",
                        "params": {"threadId": "thread-1", "turn": {"id": "user-turn"}},
                    }
                )
                assert_no_turn_start(0.75)
            finally:
                if connection is not None:
                    connection.close()
                listener.close()
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
                for stream in (process.stdout, process.stderr):
                    if stream is not None:
                        stream.close()

    @unittest.skipUnless(shutil.which("codex"), "Codex CLI is not installed")
    def test_real_codex_tool_subprocess_inherits_explicit_role(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "post"
            project = base / "shared-project"
            project.mkdir()
            office = PostOffice(root)
            for name in ("c", "cr"):
                office.register_profile(
                    Profile(
                        name=name,
                        display_name=name.upper(),
                        cli="codex",
                        kind="role",
                        summary=f"Role {name}",
                        roles=("review",),
                        project_roots=(str(project),),
                    )
                )
                office.bind_agent(name, "codex", project)

            environment = os.environ.copy()
            environment["AGENTPOST_AGENT"] = "cr"
            environment["AGENTPOST_ROOT"] = str(root)
            source_path = str(ROOT / "src")
            environment["PYTHONPATH"] = os.pathsep.join(
                part for part in (source_path, environment.get("PYTHONPATH", "")) if part
            )
            process = subprocess.Popen(
                ["codex", "app-server", "--stdio"],
                cwd=project,
                env=environment,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            def request(request_id: int, method: str, params: dict) -> dict:
                assert process.stdin is not None
                assert process.stdout is not None
                process.stdin.write(
                    json.dumps({"id": request_id, "method": method, "params": params})
                    + "\n"
                )
                process.stdin.flush()
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    ready, _, _ = select.select([process.stdout], [], [], 0.1)
                    if not ready:
                        continue
                    message = json.loads(process.stdout.readline())
                    if message.get("id") == request_id:
                        return message
                self.fail(f"Codex app-server request timed out: {method}")

            try:
                initialized = request(
                    1,
                    "initialize",
                    {
                        "clientInfo": {
                            "name": "agentpost-test",
                            "title": "AgentPost Test",
                            "version": "0",
                        },
                        "capabilities": {"experimentalApi": True},
                    },
                )
                self.assertNotIn("error", initialized)
                assert process.stdin is not None
                process.stdin.write(json.dumps({"method": "initialized", "params": {}}) + "\n")
                process.stdin.flush()
                result = request(
                    2,
                    "command/exec",
                    {
                        "command": [
                            sys.executable,
                            "-c",
                            "from agentpost.cli import main; main()",
                            "identify",
                            "--cwd",
                            str(project),
                        ],
                        "cwd": str(project),
                        "timeoutMs": 5000,
                    },
                )
                self.assertNotIn("error", result)
                self.assertEqual(result["result"]["exitCode"], 0)
                self.assertEqual(result["result"]["stdout"].strip(), "cr")
            finally:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
                for stream in (process.stdin, process.stdout, process.stderr):
                    if stream is not None:
                        stream.close()

    @unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
    def test_codex_bridge_accepts_launcher_argument_names(self) -> None:
        bridge = ROOT / "src" / "agentpost" / "data" / "codex_bridge.mjs"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = subprocess.run(
                [
                    "node",
                    str(bridge),
                    "--url",
                    "ws://127.0.0.1:1",
                    "--agent",
                    "cx",
                    "--root",
                    str(root / "post"),
                    "--cwd",
                    str(root),
                    "--log",
                    str(root / "bridge.log"),
                    "--presence",
                    str(root / "presence.json"),
                    "--owner-pid",
                    "1",
                    "--instance-id",
                    "test-instance",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                timeout=5,
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("app-server connection failed", result.stderr)
        self.assertNotIn("missing --ownerPid", result.stderr)
        self.assertNotIn("missing --instanceId", result.stderr)

    def test_codex_hooks_share_the_manifest_generation(self) -> None:
        plugin_root = ROOT / "integrations" / "codex" / "plugins" / "agentpost"
        manifest = json.loads(
            (plugin_root / ".codex-plugin" / "plugin.json").read_text(
                encoding="utf-8"
            )
        )
        hooks = json.loads(
            (plugin_root / "hooks" / "hooks.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            set(hooks["hooks"]),
            {"SessionStart", "Stop"},
        )
        commands = [
            hook["command"]
            for groups in hooks["hooks"].values()
            for group in groups
            for hook in group["hooks"]
        ]
        self.assertEqual(len(commands), 2)
        self.assertEqual(
            set(commands),
            {
                "agentpost internal-codex-hook session-start",
                "agentpost internal-codex-hook stop",
            },
        )
        self.assertEqual(CODEX_HOOK_GENERATION, manifest["version"])

    def test_claude_plugin_generation_matches_doctor_and_package(self) -> None:
        claude_root = ROOT / "integrations" / "claude"
        marketplace = json.loads(
            (claude_root / ".claude-plugin" / "marketplace.json").read_text(
                encoding="utf-8"
            )
        )
        manifest = json.loads(
            (
                claude_root
                / "agentpost"
                / ".claude-plugin"
                / "plugin.json"
            ).read_text(encoding="utf-8")
        )
        packaged = json.loads(
            (ROOT / "src" / "agentpost" / "data" / "integrations.json").read_text(
                encoding="utf-8"
            )
        )
        packaged_manifest = json.loads(
            packaged["claude/agentpost/.claude-plugin/plugin.json"]
        )
        self.assertEqual(
            {
                marketplace["metadata"]["version"],
                marketplace["plugins"][0]["version"],
                manifest["version"],
                packaged_manifest["version"],
            },
            {_claude_plugin_version()},
        )

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
