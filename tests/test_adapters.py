from __future__ import annotations

import sys
import tempfile
import time
import unittest
import json
import os
import subprocess
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from agentpost import (  # noqa: E402
    BoundaryBell,
    MailboxWatcher,
    PostOffice,
    Profile,
    RecordingBell,
)
from agentpost.native import (  # noqa: E402
    antigravity_hook,
    antigravity_launch,
    _claude_boundary_state,
    _codex_bridge_marker,
    _codex_remote_command,
    claude_boundary,
    codex_hook,
    codex_snapshot,
)
from agentpost.codex_generation import (  # noqa: E402
    _installed_codex_generation,
    codex_generation_status,
    codex_hook_marker,
)
from agentpost.installer import (  # noqa: E402
    CODEX_USER_HOOK_COMMAND,
    _claude_plugin_version,
    _doctor_claude,
    _install_codex_user_hook,
    _integration_source,
    _remove_codex_user_hook,
    _trusted_agentpost_hooks,
    armed,
    doctor,
    install,
)
from agentpost.presence import agent_presence  # noqa: E402
from agentpost.ownership import ConsumerLease  # noqa: E402


def profile(name: str) -> Profile:
    return Profile(
        name=name,
        display_name=name.upper(),
        cli="codex" if name == "cx" else "claude",
        kind="project",
        summary=f"Agent {name}",
        projects=(name,),
    )


class AdapterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "post"
        self.agentpost_environment = {
            name: os.environ.pop(name, None)
            for name in ("AGENTPOST_AGENT", "AGENTPOST_ROOT")
        }

    def tearDown(self) -> None:
        for name, value in self.agentpost_environment.items():
            os.environ.pop(name, None)
            if value is not None:
                os.environ[name] = value
        self.temp.cleanup()

    def office(self, notifier=None) -> PostOffice:
        office = PostOffice(self.root, notifier=notifier)
        if not office.list_profiles():
            office.register_profile(profile("cx"))
            office.register_profile(profile("k"))
        return office

    def test_delivery_invokes_bell_after_durable_commit(self) -> None:
        bell = RecordingBell()
        office = self.office(bell)
        result = office.send("cx", "k", "urgent", notify="immediate")
        self.assertTrue(result.recipient_path.exists())
        self.assertTrue(result.sent_path.exists())
        self.assertEqual(
            bell.notifications,
            [("k", result.message_id, "immediate")],
        )

    def test_consumer_lease_is_shared_across_adapter_types(self) -> None:
        office = self.office()
        claude = ConsumerLease(office, "k", "claude")
        python = ConsumerLease(office, "k", "python")
        self.assertTrue(claude.acquire())
        self.assertFalse(python.acquire())
        self.assertEqual(python.current_owner()["adapter"], "claude")
        claude.release()
        self.assertTrue(python.acquire())
        python.release()

    def test_mailboxes_cold_start_independently_in_any_first_agent_order(self) -> None:
        office = self.office()
        for name in ("pb", "c"):
            office.register_profile(profile(name))
        agents = ("k", "pb", "c", "cx")
        adapters = {
            "k": "claude",
            "pb": "claude",
            "c": "claude",
            "cx": "codex",
        }
        messages = {
            name: office.send(
                "cx" if name != "cx" else "k",
                name,
                f"queued for {name}",
            )
            for name in agents
        }

        # No consumer is needed for durable delivery. Every possible first
        # member can then own its mailbox, and distinct mailboxes can all be
        # live at once because ownership is mailbox-local rather than global.
        for first in agents:
            order = (first, *(name for name in agents if name != first))
            leases = [ConsumerLease(office, name, adapters[name]) for name in order]
            try:
                self.assertTrue(all(lease.acquire() for lease in leases))
                self.assertEqual(
                    {lease.current_owner()["adapter"] for lease in leases},
                    {"claude", "codex"},
                )
            finally:
                for lease in reversed(leases):
                    lease.release()

        for name in agents:
            pending = MailboxWatcher(office, name).pending()
            self.assertEqual(
                [item.letter.message_id for item in pending],
                [messages[name].message_id],
            )
            self.assertEqual(len(office.list_messages(name, "unread")), 1)

    def test_consumer_lease_excludes_a_separate_process(self) -> None:
        office = self.office()
        owner = ConsumerLease(office, "k", "claude")
        self.assertTrue(owner.acquire())
        source = Path(__file__).parents[1] / "src"
        script = """
from agentpost import PostOffice
from agentpost.ownership import ConsumerLease
import sys
lease = ConsumerLease(PostOffice(sys.argv[1]), "k", "codex")
print("acquired" if lease.acquire() else "blocked")
lease.release()
"""
        try:
            result = subprocess.run(
                [sys.executable, "-c", script, str(self.root)],
                env={**os.environ, "PYTHONPATH": str(source)},
                check=True,
                text=True,
                capture_output=True,
            )
        finally:
            owner.release()
        self.assertEqual(result.stdout.strip(), "blocked")

    def test_notification_failure_does_not_undo_delivery(self) -> None:
        class BrokenBell:
            def notify(self, agent, message_id, mode):
                raise RuntimeError("bell unavailable")

        office = self.office(BrokenBell())
        result = office.send("cx", "k", "durable")
        self.assertEqual(result.notification_error, "bell unavailable")
        self.assertTrue(result.recipient_path.exists())
        self.assertEqual(len(office.list_messages("k", "unread")), 1)

    def test_watcher_catches_up_without_claiming_or_repeating(self) -> None:
        office = self.office()
        first = office.send("cx", "k", "first")
        watcher = MailboxWatcher(office, "k", interval=0.01)
        self.assertEqual(
            [record.letter.message_id for record in watcher.pending()],
            [first.message_id],
        )
        self.assertEqual(watcher.pending(), ())
        self.assertEqual(len(office.list_messages("k", "unread")), 1)

        second = office.send("cx", "k", "second")
        self.assertEqual(
            [record.letter.message_id for record in watcher.pending()],
            [second.message_id],
        )

        restarted = MailboxWatcher(office, "k", interval=0.01)
        self.assertEqual(
            [record.letter.message_id for record in restarted.pending()],
            [first.message_id, second.message_id],
        )

    def test_idle_waits_for_completion_while_immediate_surfaces(self) -> None:
        bell = BoundaryBell()
        office = self.office(bell)
        bell.on_turn_start("k")
        idle = office.send("cx", "k", "later", notify="idle")
        immediate = office.send("cx", "k", "now", notify="immediate")
        self.assertEqual(
            bell.surfaced,
            [("k", immediate.message_id, "immediate")],
        )
        bell.on_turn_complete("k")
        self.assertEqual(
            bell.surfaced,
            [
                ("k", immediate.message_id, "immediate"),
                ("k", idle.message_id, "idle"),
            ],
        )

    def test_claude_delayed_idle_remains_busy_until_grace_period(self) -> None:
        office = self.office()
        with patch.dict(
            "os.environ",
            {"AGENTPOST_ROOT": str(self.root), "AGENTPOST_AGENT": "k"},
            clear=False,
        ):
            with redirect_stdout(StringIO()):
                claude_boundary("idle", delay=0.05)
            self.assertEqual(_claude_boundary_state(office, "k"), "busy")
            time.sleep(0.07)
            self.assertEqual(_claude_boundary_state(office, "k"), "idle")

    def test_claude_monitor_starts_without_plugin_data(self) -> None:
        office = self.office()
        source = Path(__file__).parents[1] / "src"
        environment = {
            **os.environ,
            "AGENTPOST_ROOT": str(self.root),
            "AGENTPOST_AGENT": "k",
            "PYTHONPATH": str(source),
        }
        environment.pop("CLAUDE_PLUGIN_DATA", None)
        process = subprocess.Popen(
            [sys.executable, "-m", "agentpost", "internal-claude-monitor"],
            cwd=Path(self.temp.name),
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        marker = None
        deadline = time.monotonic() + 3
        try:
            while time.monotonic() < deadline:
                matches = tuple(
                    (self.root / "agents" / "k" / "adapter").glob(
                        "claude-monitor-*.json"
                    )
                )
                if matches:
                    marker = matches[0]
                    break
                if process.poll() is not None:
                    break
                time.sleep(0.05)
            self.assertIsNone(process.poll())
            self.assertIsNotNone(marker)
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=3)

    def test_unbound_claude_monitor_exits_cleanly(self) -> None:
        self.office()
        source = Path(__file__).parents[1] / "src"
        environment = {
            **os.environ,
            "AGENTPOST_ROOT": str(self.root),
            "PYTHONPATH": str(source),
        }
        environment.pop("AGENTPOST_AGENT", None)
        environment.pop("CLAUDE_PLUGIN_DATA", None)
        result = subprocess.run(
            [sys.executable, "-m", "agentpost", "internal-claude-monitor"],
            cwd=Path(self.temp.name),
            env=environment,
            text=True,
            capture_output=True,
            timeout=3,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "")

    def test_claude_doctor_requires_current_enabled_project_entry(self) -> None:
        project = Path(self.temp.name) / "current"
        project.mkdir()
        plugin_list = [
            {
                "id": "agentpost@agentpost-local",
                "version": "0.0.5",
                "enabled": True,
                "projectPath": str(Path(self.temp.name) / "other"),
            },
            {
                "id": "agentpost@agentpost-local",
                "version": "0.0.4",
                "enabled": True,
                "projectPath": str(project),
            },
        ]
        completed = subprocess.CompletedProcess(
            args=["claude", "plugin", "list", "--json"],
            returncode=0,
            stdout=json.dumps(plugin_list),
            stderr="",
        )
        with patch("agentpost.installer.subprocess.run", return_value=completed):
            stale = _doctor_claude(project)[0]
        self.assertFalse(stale.ok)
        self.assertIn("stale version 0.0.4", stale.detail)

        plugin_list[1]["version"] = "0.0.5"
        completed.stdout = json.dumps(plugin_list)
        with patch("agentpost.installer.subprocess.run", return_value=completed):
            current = _doctor_claude(project)[0]
        self.assertTrue(current.ok)
        self.assertEqual(_claude_plugin_version(), "0.0.5")

    def test_codex_snapshot_is_machine_readable_and_non_claiming(self) -> None:
        office = self.office()
        sent = office.send("cx", "k", "later", notify="idle")
        output = StringIO()
        with redirect_stdout(output):
            codex_snapshot(office, "k")
        self.assertEqual(
            json.loads(output.getvalue()),
            [{"message_id": sent.message_id, "notify": "idle"}],
        )
        self.assertEqual(len(office.list_messages("k", "unread")), 1)

    def test_codex_remote_command_places_remote_after_subcommand(self) -> None:
        self.assertEqual(
            _codex_remote_command("ws://local", ["resume", "--last"]),
            ["codex", "resume", "--remote", "ws://local", "--last"],
        )
        self.assertEqual(
            _codex_remote_command("ws://local", ["--model", "gpt-5"]),
            ["codex", "--remote", "ws://local", "--model", "gpt-5"],
        )

    def test_codex_fallback_hook_is_suppressed_by_live_bridge_marker(self) -> None:
        office = self.office()
        project = Path(self.temp.name) / "cx-project"
        project.mkdir()
        office.register_profile(
            Profile(
                name="cx",
                display_name="CX",
                cli="codex",
                kind="project",
                summary="Agent cx",
                projects=("cx",),
                project_roots=(str(project),),
            )
        )
        marker = _codex_bridge_marker(office, "cx")
        marker.write_text("123\n", encoding="ascii")
        event = StringIO(json.dumps({"cwd": str(project)}))
        output = StringIO()
        with patch.dict("os.environ", {"AGENTPOST_ROOT": str(self.root)}, clear=False):
            with patch("sys.stdin", event), redirect_stdout(output):
                self.assertEqual(codex_hook("stop", "generation-2"), 0)
        self.assertEqual(output.getvalue().strip(), "{}")
        self.assertEqual(len(office.list_messages("cx", "unread")), 0)
        observed = json.loads(codex_hook_marker(office, "cx", "stop").read_text())
        self.assertEqual(observed["generation"], "generation-2")

    def test_codex_user_prompt_hook_injects_without_claiming(self) -> None:
        office = self.office()
        project = Path(self.temp.name) / "cx-project"
        project.mkdir()
        office.register_profile(
            Profile(
                name="cx",
                display_name="CX",
                cli="codex",
                kind="project",
                summary="Agent cx",
                projects=("cx",),
                project_roots=(str(project),),
            )
        )
        sent = office.send("k", "cx", "review this")
        event = StringIO(json.dumps({"cwd": str(project), "session_id": "session-1"}))
        output = StringIO()
        with patch.dict("os.environ", {"AGENTPOST_ROOT": str(self.root)}, clear=False):
            with patch("sys.stdin", event), redirect_stdout(output):
                self.assertEqual(
                    codex_hook("user-prompt-submit", "generation-3"),
                    0,
                )
        result = json.loads(output.getvalue())
        hook_output = result["hookSpecificOutput"]
        self.assertEqual(hook_output["hookEventName"], "UserPromptSubmit")
        self.assertIn(sent.message_id, hook_output["additionalContext"])
        self.assertEqual(len(office.list_messages("cx", "unread")), 1)
        observed = json.loads(
            codex_hook_marker(office, "cx", "user-prompt-submit").read_text()
        )
        self.assertEqual(observed["session_id"], "session-1")
        self.assertEqual(observed["event"], "user-prompt-submit")

    def test_codex_hook_stamps_before_bridge_environment_suppression(self) -> None:
        office = self.office()
        project = Path(self.temp.name) / "cx-project"
        project.mkdir()
        office.register_profile(
            Profile(
                name="cx",
                display_name="CX",
                cli="codex",
                kind="project",
                summary="Agent cx",
                projects=("cx",),
                project_roots=(str(project),),
            )
        )
        event = StringIO(json.dumps({"cwd": str(project)}))
        output = StringIO()
        environment = {
            "AGENTPOST_ROOT": str(self.root),
            "AGENTPOST_CODEX_BRIDGE": "1",
        }
        with patch.dict("os.environ", environment, clear=False):
            with patch("sys.stdin", event), redirect_stdout(output):
                codex_hook("session-start", "managed-generation")
        self.assertEqual(json.loads(output.getvalue()), {})
        observed = json.loads(
            codex_hook_marker(office, "cx", "session-start").read_text()
        )
        self.assertEqual(observed["generation"], "managed-generation")

    def test_codex_hook_stamps_when_consumer_lease_is_held(self) -> None:
        office = self.office()
        project = Path(self.temp.name) / "cx-project"
        project.mkdir()
        office.register_profile(
            Profile(
                name="cx",
                display_name="CX",
                cli="codex",
                kind="project",
                summary="Agent cx",
                projects=("cx",),
                project_roots=(str(project),),
            )
        )
        owner = ConsumerLease(office, "cx", "codex")
        self.assertTrue(owner.acquire())
        try:
            event = StringIO(json.dumps({"cwd": str(project)}))
            output = StringIO()
            with patch.dict("os.environ", {"AGENTPOST_ROOT": str(self.root)}, clear=False):
                with patch("sys.stdin", event), redirect_stdout(output):
                    codex_hook("stop", "lease-generation")
        finally:
            owner.release()
        self.assertEqual(json.loads(output.getvalue()), {})
        observed = json.loads(codex_hook_marker(office, "cx", "stop").read_text())
        self.assertEqual(observed["generation"], "lease-generation")

    def test_codex_generation_status_is_current_stale_and_unobserved(self) -> None:
        office = self.office()
        home = Path(self.temp.name) / "home"
        self._write_codex_install(home, "generation-1")
        unobserved = codex_generation_status(office, "cx", home=home)
        self.assertEqual(unobserved.state, "unobserved")
        self._write_codex_observation(office, "stop", "generation-0")
        stale = codex_generation_status(office, "cx", home=home)
        self.assertEqual(stale.state, "stale")
        for event in ("session-start", "user-prompt-submit", "stop"):
            self._write_codex_observation(office, event, "generation-1")
        current = codex_generation_status(office, "cx", home=home)
        self.assertTrue(current.current)

    def _write_codex_observation(
        self,
        office: PostOffice,
        event: str,
        generation: str,
    ) -> None:
        marker = codex_hook_marker(office, "cx", event)
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps({"generation": generation}), encoding="utf-8")

    def test_multiple_codex_cache_generations_are_unknown(self) -> None:
        home = Path(self.temp.name) / "home"
        self._write_codex_install(home, "generation-1")
        self._write_codex_cache(home, "generation-2")
        generation, problem = _installed_codex_generation(home)
        self.assertIsNone(generation)
        self.assertIn("found 2", problem)

    def test_malformed_codex_cache_generation_is_unknown(self) -> None:
        home = Path(self.temp.name) / "home"
        config = home / ".codex" / "config.toml"
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(
            '[plugins."agentpost@agentpost-local"]\nenabled = true\n',
            encoding="utf-8",
        )
        malformed = (
            home
            / ".codex/plugins/cache/agentpost-local/agentpost/generation-1"
            / ".codex-plugin/plugin.json"
        )
        malformed.parent.mkdir(parents=True, exist_ok=True)
        malformed.write_text("not json", encoding="utf-8")
        generation, problem = _installed_codex_generation(home)
        self.assertIsNone(generation)
        self.assertIn("malformed", problem)

    def _write_codex_install(self, home: Path, generation: str) -> None:
        config = home / ".codex" / "config.toml"
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(
            '[plugins."agentpost@agentpost-local"]\nenabled = true\n',
            encoding="utf-8",
        )
        self._write_codex_cache(home, generation)

    def _write_codex_cache(self, home: Path, generation: str) -> None:
        manifest = (
            home
            / ".codex"
            / "plugins"
            / "cache"
            / "agentpost-local"
            / "agentpost"
            / generation
            / ".codex-plugin"
            / "plugin.json"
        )
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(
            json.dumps({"name": "agentpost", "version": generation}),
            encoding="utf-8",
        )

    def test_armed_state_distinguishes_live_and_catchup_only_adapters(self) -> None:
        office = self.office()
        self.assertFalse(armed(office, "cx")[0])
        _codex_bridge_marker(office, "cx").write_text(
            f"{os.getpid()}\n", encoding="ascii"
        )
        self.assertTrue(armed(office, "cx")[0])

        marker = self.root / "agents" / "k" / "adapter" / "claude-monitor-test.json"
        marker.write_text(
            json.dumps({"pid": os.getpid(), "updated_at": time.time()}),
            encoding="utf-8",
        )
        self.assertTrue(armed(office, "k")[0])
        marker.write_text(
            json.dumps({"pid": os.getpid(), "updated_at": 0}),
            encoding="utf-8",
        )
        self.assertFalse(armed(office, "k")[0])

    def test_presence_distinguishes_offline_idle_and_working(self) -> None:
        office = self.office()
        self.assertEqual(agent_presence(office, "cx").state, "offline")
        marker = _codex_bridge_marker(office, "cx")
        marker.write_text(
            json.dumps(
                {"pid": os.getpid(), "updated_at": time.time(), "state": "idle"}
            ),
            encoding="utf-8",
        )
        self.assertEqual(agent_presence(office, "cx").state, "idle")
        marker.write_text(
            json.dumps(
                {"pid": os.getpid(), "updated_at": time.time(), "state": "working"}
            ),
            encoding="utf-8",
        )
        self.assertEqual(agent_presence(office, "cx").state, "working")

    def test_legacy_codex_pid_marker_expires_by_file_age(self) -> None:
        office = self.office()
        marker = _codex_bridge_marker(office, "cx")
        marker.write_text(f"{os.getpid()}\n", encoding="ascii")
        self.assertEqual(agent_presence(office, "cx").state, "idle")
        os.utime(marker, (0, 0))
        self.assertEqual(agent_presence(office, "cx").state, "offline")

    def test_install_records_project_binding(self) -> None:
        office = self.office()
        project = Path(self.temp.name) / "project"
        project.mkdir()
        home = Path(self.temp.name) / "home"
        with patch("agentpost.installer._integration_source", return_value=project):
            with patch("agentpost.installer.Path.home", return_value=home):
                with patch("agentpost.installer._run"):
                    with redirect_stdout(StringIO()):
                        install(office, "codex", "cx", project)
        binding = office.list_bindings()[0]
        self.assertEqual((binding.agent, binding.cli), ("cx", "codex"))
        self.assertEqual(binding.project, str(project.resolve()))

    def test_codex_install_re_registers_hooks_on_every_generation(self) -> None:
        office = self.office()
        project = Path(self.temp.name) / "project"
        project.mkdir()
        home = Path(self.temp.name) / "home"
        with patch("agentpost.installer._integration_source", return_value=project):
            with patch("agentpost.installer.Path.home", return_value=home):
                with patch("agentpost.installer._run") as run:
                    with redirect_stdout(StringIO()):
                        install(office, "codex", "cx", project)
        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual(
            commands[-2:],
            [
                ["codex", "plugin", "remove", "agentpost@agentpost-local"],
                ["codex", "plugin", "add", "agentpost@agentpost-local"],
            ],
        )
        user_hooks = json.loads((home / ".codex/hooks.json").read_text())
        command = user_hooks["hooks"]["UserPromptSubmit"][0]["hooks"][0][
            "command"
        ]
        self.assertEqual(command, CODEX_USER_HOOK_COMMAND)

    def test_codex_user_hook_merge_and_uninstall_preserve_unrelated_hooks(self) -> None:
        home = Path(self.temp.name) / "home"
        hooks_path = home / ".codex/hooks.json"
        hooks_path.parent.mkdir(parents=True)
        unrelated = {"type": "command", "command": "example prompt hook"}
        hooks_path.write_text(
            json.dumps(
                {
                    "description": "keep me",
                    "hooks": {
                        "UserPromptSubmit": [{"hooks": [unrelated]}],
                        "Stop": [{"hooks": [{"command": "example stop"}]}],
                    },
                }
            ),
            encoding="utf-8",
        )
        _install_codex_user_hook(home)
        _install_codex_user_hook(home)
        installed = json.loads(hooks_path.read_text())
        prompt_handlers = [
            handler
            for group in installed["hooks"]["UserPromptSubmit"]
            for handler in group["hooks"]
        ]
        self.assertEqual(
            sum(handler.get("command") == CODEX_USER_HOOK_COMMAND for handler in prompt_handlers),
            1,
        )
        self.assertIn(unrelated, prompt_handlers)
        _remove_codex_user_hook(home)
        removed = json.loads(hooks_path.read_text())
        self.assertEqual(
            removed["hooks"]["UserPromptSubmit"],
            [{"hooks": [unrelated]}],
        )
        self.assertIn("Stop", removed["hooks"])
        self.assertEqual(removed["description"], "keep me")

    def test_codex_hook_trust_requires_current_discovered_hooks(self) -> None:
        hooks = [
            {
                "eventName": "userPromptSubmit",
                "pluginId": None,
                "command": CODEX_USER_HOOK_COMMAND,
                "enabled": True,
                "trustStatus": "trusted",
            },
            {
                "eventName": "sessionStart",
                "pluginId": "agentpost@agentpost-local",
                "command": "agentpost internal-codex-hook session-start",
                "enabled": True,
                "trustStatus": "trusted",
            },
            {
                "eventName": "stop",
                "pluginId": "agentpost@agentpost-local",
                "command": "agentpost internal-codex-hook stop",
                "enabled": True,
                "trustStatus": "trusted",
            },
        ]
        trusted, problems = _trusted_agentpost_hooks(hooks)
        self.assertEqual(trusted, {"userPromptSubmit", "sessionStart", "stop"})
        self.assertEqual(problems, [])

        hooks[1]["trustStatus"] = "untrusted"
        hooks.pop()
        trusted, problems = _trusted_agentpost_hooks(hooks)
        self.assertEqual(trusted, {"userPromptSubmit"})
        self.assertEqual(
            problems,
            ["sessionStart not trusted", "stop missing"],
        )

    def test_claude_install_refreshes_and_enables_an_existing_plugin(self) -> None:
        office = self.office()
        project = Path(self.temp.name) / "claude-project"
        project.mkdir()
        with patch("agentpost.installer._integration_source", return_value=project):
            with patch("agentpost.installer._run") as run:
                install(office, "claude", "k", project)
        commands = [call.args[0] for call in run.call_args_list]
        self.assertIn(
            ["claude", "plugin", "marketplace", "update", "agentpost-local"],
            commands,
        )
        self.assertIn(
            [
                "claude",
                "plugin",
                "update",
                "agentpost@agentpost-local",
                "--scope",
                "local",
            ],
            commands,
        )
        self.assertIn(
            [
                "claude",
                "plugin",
                "enable",
                "agentpost@agentpost-local",
                "--scope",
                "local",
            ],
            commands,
        )

    def test_antigravity_hooks_inject_each_unread_id_once_without_claiming(self) -> None:
        office = self.office()
        project = Path(self.temp.name) / "antigravity-project"
        project.mkdir()
        office.register_profile(
            Profile(
                name="ag",
                display_name="Antigravity",
                cli="antigravity",
                kind="project",
                summary="Antigravity integration test",
                projects=("antigravity-test",),
                project_roots=(str(project),),
            )
        )
        first = office.send("cx", "ag", "first")
        event = {
            "conversationId": "conversation-1",
            "workspacePaths": [str(project)],
        }

        output = StringIO()
        with patch.dict("os.environ", {"AGENTPOST_ROOT": str(self.root)}, clear=False):
            with patch("sys.stdin", StringIO(json.dumps(event))), redirect_stdout(output):
                self.assertEqual(antigravity_hook("pre-invocation"), 0)
        injected = json.loads(output.getvalue())
        self.assertIn(first.message_id, injected["injectSteps"][0]["ephemeralMessage"])
        self.assertEqual(len(office.list_messages("ag", "unread")), 1)
        self.assertEqual(agent_presence(office, "ag").state, "working")

        output = StringIO()
        with patch.dict("os.environ", {"AGENTPOST_ROOT": str(self.root)}, clear=False):
            with patch("sys.stdin", StringIO(json.dumps(event))), redirect_stdout(output):
                antigravity_hook("pre-invocation")
        self.assertEqual(json.loads(output.getvalue()), {"injectSteps": []})

        second = office.send("cx", "ag", "second")
        stop_event = {**event, "fullyIdle": True}
        output = StringIO()
        with patch.dict("os.environ", {"AGENTPOST_ROOT": str(self.root)}, clear=False):
            with patch("sys.stdin", StringIO(json.dumps(stop_event))), redirect_stdout(output):
                antigravity_hook("stop")
        stopped = json.loads(output.getvalue())
        self.assertEqual(stopped["decision"], "continue")
        self.assertIn(second.message_id, stopped["reason"])
        self.assertNotIn(first.message_id, stopped["reason"])
        self.assertEqual(len(office.list_messages("ag", "unread")), 2)
        self.assertEqual(agent_presence(office, "ag").state, "idle")
        self.assertFalse(armed(office, "ag")[0])

    def test_antigravity_install_validates_plugin_and_records_binding(self) -> None:
        office = self.office()
        project = Path(self.temp.name) / "antigravity-project"
        project.mkdir()
        office.register_profile(
            Profile(
                name="ag",
                display_name="Antigravity",
                cli="antigravity",
                kind="project",
                summary="Antigravity integration test",
                projects=("antigravity-test",),
                project_roots=(str(project),),
            )
        )
        with patch("agentpost.installer._integration_source", return_value=project):
            with patch("agentpost.installer._run") as run:
                install(office, "antigravity", "ag", project)
        self.assertEqual(
            [call.args[0] for call in run.call_args_list],
            [
                ["agy", "plugin", "validate", str(project)],
                ["agy", "plugin", "uninstall", "agentpost"],
                ["agy", "plugin", "install", str(project)],
            ],
        )
        binding = office.list_bindings()[0]
        self.assertEqual((binding.agent, binding.cli), ("ag", "antigravity"))
        self.assertEqual(binding.project, str(project.resolve()))

    def test_antigravity_launcher_sets_the_per_process_mailbox(self) -> None:
        office = self.office()
        project = Path(self.temp.name) / "shared-project"
        project.mkdir()
        office.register_profile(
            Profile(
                name="ag",
                display_name="Antigravity",
                cli="antigravity",
                kind="project",
                summary="Antigravity integration test",
                projects=("shared",),
                project_roots=(str(project),),
            )
        )
        office.bind_agent("ag", "antigravity", project)
        with patch("agentpost.native.subprocess.call", return_value=0) as call:
            self.assertEqual(
                antigravity_launch(office, project, ["--model", "auto"], agent="ag"),
                0,
            )
        command = call.call_args.args[0]
        environment = call.call_args.kwargs["env"]
        self.assertEqual(command, ["agy", "--model", "auto"])
        self.assertEqual(environment["AGENTPOST_AGENT"], "ag")

    def test_packaged_integration_replaces_its_generated_cache(self) -> None:
        home = Path(self.temp.name) / "home"
        destination = home / ".local/share/agentpost/integrations/antigravity"
        stale = destination / "removed/component.json"
        stale.parent.mkdir(parents=True)
        stale.write_text("obsolete", encoding="utf-8")
        fake_module = Path(self.temp.name) / "installed/agentpost/installer.py"
        with patch("agentpost.installer.__file__", str(fake_module)):
            with patch("agentpost.installer.Path.home", return_value=home):
                resolved = _integration_source("antigravity")
        self.assertEqual(resolved, destination)
        self.assertFalse(stale.exists())
        self.assertTrue((destination / "hooks.json").is_file())

    def test_doctor_honors_explicit_agent_in_a_shared_workspace(self) -> None:
        office = self.office()
        project = Path(self.temp.name) / "shared-project"
        project.mkdir()
        for name in ("first", "second"):
            office.register_profile(
                Profile(
                    name=name,
                    display_name=name.title(),
                    cli="antigravity",
                    kind="role",
                    summary=f"Role {name}",
                    roles=("review",),
                )
            )
            office.bind_agent(name, "antigravity", project)
        with patch("agentpost.installer._doctor_antigravity", return_value=()):
            checks = doctor(office, "second", project, cli="antigravity")
        identity = next(check for check in checks if check.name == "identity")
        self.assertTrue(identity.ok)
        self.assertEqual(identity.detail, "resolved second")

if __name__ == "__main__":
    unittest.main()
