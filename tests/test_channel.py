from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from agentpost import AgentChannel, PostOffice, Profile  # noqa: E402


class AgentChannelTest(unittest.TestCase):
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
                summary="Application orchestrator",
                projects=("application",),
            )
        )
        self.office.register_profile(
            Profile(
                name="pb",
                display_name="Pattern Buffer",
                cli="claude",
                kind="project",
                summary="Persistent world state",
                projects=("pattern-buffer",),
                handles=("world state storage",),
            )
        )
        self.channel = AgentChannel("Application", office=self.office)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_directory_and_resolution_include_offline_identity(self) -> None:
        identities = {identity.name: identity for identity in self.channel.identities()}
        self.assertEqual(identities["pb"].presence, "offline")
        self.assertEqual(self.channel.resolve("Pattern Buffer")[0].name, "pb")

    def test_message_uses_bound_sender_and_human_address(self) -> None:
        result = self.channel.message("world state storage", "Please review this.")
        letter = self.office.read("pb", result.message_id).letter
        self.assertEqual(letter.from_agent, "app")
        self.assertEqual(letter.kind, "letter")

    def test_question_uses_question_kind_and_immediate_default(self) -> None:
        result = self.channel.question("PB", "Does this retain provenance?")
        letter = self.office.read("pb", result.message_id).letter
        self.assertEqual(letter.kind, "question")
        self.assertEqual(letter.notify, "immediate")

    def test_named_group_expands_without_at_prefix(self) -> None:
        self.office.register_profile(
            Profile(
                name="reviewer",
                display_name="Reviewer",
                cli="codex",
                kind="specialist",
                summary="Code reviewer",
                roles=("reviewer",),
            )
        )
        self.office.set_group("reviewers", ("pb", "reviewer"))
        result = self.channel.message("reviewers", "Review this change.")
        self.assertEqual(result.deliveries[0].message_id, result.message_id)
        self.assertEqual(len(self.office.list_messages("pb")), 1)
        self.assertEqual(len(self.office.list_messages("reviewer")), 1)


if __name__ == "__main__":
    unittest.main()
