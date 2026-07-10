from __future__ import annotations

import queue
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from agentpost import AgentPostError, AgentRuntime, PostOffice, Profile, agent_presence  # noqa: E402


class PythonRuntimeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "post"
        self.office = PostOffice(self.root)
        self.office.register_profile(
            Profile(
                name="app",
                display_name="Application",
                cli="python",
                kind="project",
                summary="Embedded Python agent",
                projects=("application",),
            )
        )
        self.office.register_profile(
            Profile(
                name="cx",
                display_name="CX",
                cli="codex",
                kind="specialist",
                summary="Reviewer",
                specialties=("review",),
            )
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_runtime_presence_and_attention_boundaries(self) -> None:
        callbacks = queue.Queue()
        runtime = AgentRuntime(
            "app",
            root=self.root,
            on_mail=callbacks.put,
            interval=0.01,
        )
        with runtime:
            self.assertEqual(agent_presence(self.office, "app").state, "idle")
            runtime.set_state("working")
            idle = self.office.send("cx", "app", "later", notify="idle")
            immediate = self.office.send("cx", "app", "now", notify="immediate")

            first = runtime.get(timeout=1)
            self.assertEqual([item.message_id for item in first], [immediate.message_id])
            self.assertEqual(callbacks.get(timeout=1), first)
            self.assertEqual(agent_presence(self.office, "app").state, "working")

            runtime.set_state("idle")
            second = runtime.get(timeout=1)
            self.assertEqual([item.message_id for item in second], [idle.message_id])
            self.assertEqual(callbacks.get(timeout=1), second)
            self.assertEqual(len(self.office.list_messages("app", "unread")), 2)
        self.assertEqual(agent_presence(self.office, "app").state, "offline")

    def test_runtime_start_catches_up_and_never_claims(self) -> None:
        sent = self.office.send("cx", "app", "queued while offline")
        with AgentRuntime("app", root=self.root, interval=0.01) as runtime:
            batch = runtime.get(timeout=1)
            self.assertEqual(batch[0].message_id, sent.message_id)
            self.assertEqual(len(self.office.list_messages("app", "unread")), 1)

    def test_one_python_runtime_owns_a_mailbox(self) -> None:
        first = AgentRuntime("app", root=self.root, interval=0.01).start()
        try:
            second = AgentRuntime("app", root=self.root, interval=0.01)
            with self.assertRaises(AgentPostError):
                second.start()
        finally:
            first.close()

    def test_nested_turns_remain_working_until_all_complete(self) -> None:
        with AgentRuntime("app", root=self.root, interval=0.01) as runtime:
            with runtime.turn():
                self.assertEqual(runtime.state, "working")
                with runtime.turn():
                    self.assertEqual(runtime.state, "working")
                self.assertEqual(runtime.state, "working")
            self.assertEqual(runtime.state, "idle")

    def test_unstarted_runtime_cannot_advertise_presence(self) -> None:
        runtime = AgentRuntime("app", root=self.root, interval=0.01)
        with self.assertRaises(AgentPostError):
            runtime.set_state("working")
        self.assertEqual(agent_presence(self.office, "app").state, "offline")


if __name__ == "__main__":
    unittest.main()
