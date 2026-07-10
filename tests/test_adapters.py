from __future__ import annotations

import sys
import tempfile
import time
import unittest
import json
import os
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
from agentpost.installer import armed, install  # noqa: E402
from agentpost.presence import agent_presence  # noqa: E402


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

    def tearDown(self) -> None:
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
        data_dir = Path(self.temp.name) / "claude-data"
        with patch.dict("os.environ", {"CLAUDE_PLUGIN_DATA": str(data_dir)}):
            with redirect_stdout(StringIO()):
                claude_boundary("idle", delay=0.05)
            self.assertEqual(_claude_boundary_state(), "busy")
            time.sleep(0.07)
            self.assertEqual(_claude_boundary_state(), "idle")

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
                self.assertEqual(codex_hook("stop"), 0)
        self.assertEqual(output.getvalue().strip(), "{}")
        self.assertEqual(len(office.list_messages("cx", "unread")), 0)

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

    def test_install_records_project_binding(self) -> None:
        office = self.office()
        project = Path(self.temp.name) / "project"
        project.mkdir()
        with patch("agentpost.installer._integration_source", return_value=project):
            with patch("agentpost.installer._run"):
                install(office, "codex", "cx", project)
        binding = office.list_bindings()[0]
        self.assertEqual((binding.agent, binding.cli), ("cx", "codex"))
        self.assertEqual(binding.project, str(project.resolve()))

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


if __name__ == "__main__":
    unittest.main()
