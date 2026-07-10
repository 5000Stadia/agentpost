from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from agentpost import (  # noqa: E402
    PostOffice,
    Profile,
    ask,
    panel_status,
    wait_for_panel,
)


def profile(name: str) -> Profile:
    return Profile(
        name=name,
        display_name=name.upper(),
        cli="codex" if name == "cx" else "claude",
        kind="project",
        summary=f"Agent {name}",
        projects=(name,),
    )


class PanelTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.office = PostOffice(Path(self.temp.name) / "post")
        for name in ("cx", "k", "pb", "c"):
            self.office.register_profile(profile(name))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_panel_counts_each_responder_once_and_preserves_duplicates(self) -> None:
        root = ask(self.office, "cx", ("k", "pb", "c"), "Opinions?")
        self.office.reply("k", root.message_id, "K answer")
        self.office.reply("k", root.message_id, "K correction")
        self.office.reply("pb", root.message_id, "PB answer")

        status = panel_status(self.office, "cx", root.message_id, quorum=2)
        self.assertTrue(status.complete)
        self.assertEqual(status.answered, ("k", "pb"))
        self.assertEqual(status.pending, ("c",))
        self.assertEqual(len(status.duplicates), 1)
        self.assertEqual(len(status.responses), 3)
        self.assertEqual(len(self.office.list_messages("cx", "unread")), 3)

    def test_error_is_terminal_and_counts_toward_quorum(self) -> None:
        root = ask(self.office, "cx", ("k", "pb"), "Opinions?")
        self.office.send(
            "k",
            "cx",
            "Provider unavailable",
            kind="error",
            in_reply_to=root.message_id,
        )
        status = panel_status(self.office, "cx", root.message_id, quorum=1)
        self.assertTrue(status.complete)
        self.assertEqual(status.errors, ("k",))
        self.assertEqual(status.pending, ("pb",))

    def test_timeout_is_non_destructive_and_late_answer_is_visible(self) -> None:
        root = ask(self.office, "cx", ("k",), "Answer later?")
        status = wait_for_panel(
            self.office,
            "cx",
            root.message_id,
            timeout=0.01,
            poll_interval=0.001,
        )
        self.assertFalse(status.complete)
        self.assertEqual(status.pending, ("k",))
        self.assertEqual(len(self.office.list_messages("k", "unread")), 1)

        self.office.reply("k", root.message_id, "Late answer")
        late = panel_status(self.office, "cx", root.message_id)
        self.assertTrue(late.complete)
        self.assertEqual(late.answered, ("k",))

    def test_invalid_quorum_is_rejected(self) -> None:
        root = ask(self.office, "cx", ("k",), "Question?")
        with self.assertRaises(ValueError):
            panel_status(self.office, "cx", root.message_id, quorum=2)


if __name__ == "__main__":
    unittest.main()
