from __future__ import annotations

import os
import sys
import tempfile
import threading
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from agentpost import (  # noqa: E402
    DuplicateDeliveryError,
    Experience,
    InvalidMessageError,
    MessageNotFoundError,
    PostOffice,
    Profile,
    UnknownAgentError,
)


def profile(name: str, cli: str = "claude") -> Profile:
    return Profile(
        name=name,
        display_name=name.upper(),
        cli=cli,
        kind="hybrid",
        summary=f"Agent {name}",
        roles=("reviewer",),
        projects=(f"project-{name}",),
        specialties=("testing",),
        experience=(
            Experience(
                topic="testing",
                summary="Built tests",
                projects=(f"project-{name}",),
                evidence=(f"/tmp/{name}-evidence.md",),
            ),
        ),
    )


class PostOfficeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "post"
        self.office = PostOffice(self.root)
        self.office.register_profile(profile("cx", "codex"))
        self.office.register_profile(profile("k"))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_initialize_creates_minimal_runtime(self) -> None:
        self.assertEqual(
            (self.root / "config.toml").read_text(),
            'version = 1\nconnection_mode = "auto"\n',
        )
        self.assertTrue((self.root / "bindings").is_dir())
        for name in ("cx", "k"):
            for directory in ("tmp", "unread", "read", "sent", "adapter"):
                self.assertTrue((self.root / "agents" / name / directory).is_dir())

    def test_profiles_round_trip_and_scan(self) -> None:
        loaded = self.office.load_profile("cx")
        self.assertEqual(loaded, profile("cx", "codex"))
        self.assertEqual([item.name for item in self.office.list_profiles()], ["cx", "k"])

    def test_named_groups_round_trip_and_validate_members(self) -> None:
        self.office.register_profile(profile("pb"))
        self.office.set_group("council", ("cx", "k", "pb", "k"))
        self.assertEqual(
            self.office.list_groups(), {"council": ("cx", "k", "pb")}
        )
        with self.assertRaises(UnknownAgentError):
            self.office.set_group("bad", ("missing",))

    def test_profile_update_is_atomic_and_preserves_mail(self) -> None:
        result = self.office.send("cx", "k", "hello")
        updated = Profile(
            **{**profile("k").__dict__, "summary": "Updated K"}
        )
        self.office.register_profile(updated)
        self.assertEqual(self.office.load_profile("k").summary, "Updated K")
        self.assertTrue(result.recipient_path.exists())

    def test_project_binding_reconnects_and_can_move_without_touching_mail(self) -> None:
        first = Path(self.temp.name) / "first"
        second = Path(self.temp.name) / "second"
        self.office.bind_agent("cx", "codex", first)
        self.assertEqual(
            [(item.agent, item.cli, item.project) for item in self.office.list_bindings()],
            [("cx", "codex", str(first.resolve()))],
        )
        delivered = self.office.send("k", "cx", "survives relocation")
        self.office.bind_agent("cx", "codex", second)
        self.office.unbind_agent("codex", first)
        self.assertTrue(delivered.recipient_path.exists())
        self.assertEqual(self.office.list_bindings()[0].project, str(second.resolve()))

    def test_mailbox_can_bind_multiple_cli_adapters_and_keeps_one_workspace_default(self) -> None:
        project = Path(self.temp.name) / "shared"
        project.mkdir()
        self.office.bind_agent("cx", "codex", project)
        self.office.bind_agent("k", "claude", project)
        marker = self.office.workspace_identity(project / "src")
        self.assertEqual(marker[0], "cx")
        self.assertEqual(marker[1], ("cx", "k"))
        self.assertEqual(marker[2], project)

    def test_workspace_marker_is_excluded_from_git_when_bound(self) -> None:
        project = Path(self.temp.name) / "repository"
        (project / ".git" / "info").mkdir(parents=True)
        self.office.bind_agent("cx", "codex", project)
        self.assertTrue((project / ".agentpost.toml").is_file())
        self.assertIn(
            ".agentpost.toml",
            (project / ".git" / "info" / "exclude").read_text(encoding="utf-8"),
        )

    def test_migrate_upgrades_v1_profile_and_materializes_legacy_binding_marker(self) -> None:
        project = Path(self.temp.name) / "legacy"
        project.mkdir()
        self.office.bind_agent("cx", "codex", project)
        (project / ".agentpost.toml").unlink()
        profile_path = self.root / "agents" / "cx" / "profile.toml"
        legacy = profile_path.read_text(encoding="utf-8").replace(
            "version = 2", "version = 1", 1
        ).replace("cli_hint =", "cli =", 1)
        profile_path.write_text(legacy, encoding="utf-8")

        actions = self.office.migrate()

        self.assertEqual(self.office.load_profile("cx").version, 2)
        self.assertEqual(self.office.load_profile("cx").cli, "codex")
        self.assertEqual(self.office.workspace_identity(project)[0], "cx")
        self.assertTrue(any("profile cx" in action for action in actions))
        self.assertTrue(any("default cx" in action for action in actions))

    def test_connection_mode_round_trips_without_losing_groups(self) -> None:
        self.office.set_group("team", ("cx", "k"))
        self.office.set_connection_mode("manual")
        self.assertEqual(self.office.connection_mode(), "manual")
        self.assertEqual(self.office.list_groups(), {"team": ("cx", "k")})

    def test_registration_verified_same_filesystem(self) -> None:
        agent = self.root / "agents" / "cx"
        self.assertEqual((agent / "tmp").stat().st_dev, (agent / "unread").stat().st_dev)
        self.assertEqual(list((agent / "tmp").iterdir()), [])

    def test_direct_delivery_is_plain_markdown_and_archived(self) -> None:
        result = self.office.send(
            "cx",
            "k",
            "Please review this.",
            subject="Review",
            kind="question",
            notify="immediate",
        )
        text = result.recipient_path.read_text()
        self.assertIn(f"Message-ID: {result.message_id}", text)
        self.assertIn("From: cx", text)
        self.assertIn("To: k", text)
        self.assertIn("X-Agent-Kind: question", text)
        self.assertRegex(text, r"Date: \d{4}-\d{2}-\d{2}T.*Z")
        self.assertTrue(text.endswith("Please review this."))
        self.assertEqual(result.sent_path.read_bytes(), result.recipient_path.read_bytes())

    def test_utf8_markdown_and_headers_round_trip(self) -> None:
        result = self.office.send(
            "cx",
            "k",
            "Caf\u00e9 \u2014 \u4e16\u754c\n",
            subject="R\u00e9sum\u00e9",
        )
        letter = self.office.read("k", result.message_id).letter
        self.assertEqual(letter.body, "Caf\u00e9 \u2014 \u4e16\u754c\n")
        self.assertEqual(letter.subject, "R\u00e9sum\u00e9")
        self.assertIn("Caf\u00e9 \u2014 \u4e16\u754c".encode(), result.recipient_path.read_bytes())

    def test_header_injection_is_rejected_before_delivery(self) -> None:
        with self.assertRaises(InvalidMessageError):
            self.office.send("cx", "k", "body", subject="safe\nX-Evil: injected")
        self.assertEqual(self.office.list_messages("k"), ())

    def test_list_and_read_are_side_effect_free(self) -> None:
        result = self.office.send("cx", "k", "hello")
        before = result.recipient_path.stat()
        listed = self.office.list_messages("k")
        read = self.office.read("k", result.message_id)
        after = result.recipient_path.stat()
        self.assertEqual(len(listed), 1)
        self.assertEqual(read.state, "unread")
        self.assertEqual(before.st_ino, after.st_ino)
        self.assertEqual(before.st_mtime_ns, after.st_mtime_ns)
        self.assertEqual(len(self.office.list_messages("k", "read")), 0)

    def test_list_tolerates_a_concurrent_claim_after_directory_scan(self) -> None:
        sent = self.office.send("cx", "k", "claimed during list")
        source = self.office.read("k", sent.message_id).path
        destination = source.parent.parent / "read" / source.name
        original_read_bytes = Path.read_bytes
        moved = False

        def racing_read_bytes(path: Path) -> bytes:
            nonlocal moved
            if path == source and not moved:
                moved = True
                os.replace(source, destination)
            return original_read_bytes(path)

        with patch("pathlib.Path.read_bytes", new=racing_read_bytes):
            self.assertEqual(self.office.list_messages("k"), ())
        self.assertEqual(len(self.office.list_messages("k", "read")), 1)

    def test_read_follows_a_message_claimed_during_inspection(self) -> None:
        sent = self.office.send("cx", "k", "claimed during read")
        source = self.office.read("k", sent.message_id).path
        destination = source.parent.parent / "read" / source.name
        original_read_bytes = Path.read_bytes
        moved = False

        def racing_read_bytes(path: Path) -> bytes:
            nonlocal moved
            if path == source and not moved:
                moved = True
                os.replace(source, destination)
            return original_read_bytes(path)

        with patch("pathlib.Path.read_bytes", new=racing_read_bytes):
            record = self.office.read("k", sent.message_id)
        self.assertEqual(record.state, "read")
        self.assertEqual(record.letter.message_id, sent.message_id)

    def test_claim_moves_exactly_one_message(self) -> None:
        result = self.office.send("cx", "k", "hello")
        claimed = self.office.claim("k", result.message_id)
        self.assertEqual(claimed.state, "read")
        self.assertFalse(result.recipient_path.exists())
        self.assertTrue(claimed.path.exists())
        self.assertEqual(len(self.office.list_messages("k")), 0)
        self.assertEqual(len(self.office.list_messages("k", "read")), 1)

    def test_read_claim_and_reply_accept_bracketless_message_ids(self) -> None:
        result = self.office.send("cx", "k", "question")
        bare_address = result.message_id[1:-1]
        bare_uuid = bare_address.split("@", 1)[0]
        self.assertEqual(
            self.office.read("k", bare_address).letter.message_id,
            result.message_id,
        )
        self.assertEqual(
            self.office.claim("k", bare_uuid).letter.message_id,
            result.message_id,
        )
        reply = self.office.reply("k", bare_address, "answer")
        self.assertEqual(
            self.office.read("cx", reply.message_id).letter.in_reply_to,
            result.message_id,
        )

    def test_competing_claim_allows_one_winner(self) -> None:
        result = self.office.send("cx", "k", "race")
        outcomes: list[str] = []
        barrier = threading.Barrier(2)

        def claim() -> None:
            barrier.wait()
            try:
                self.office.claim("k", result.message_id)
                outcomes.append("won")
            except MessageNotFoundError:
                outcomes.append("lost")

        threads = [threading.Thread(target=claim) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertCountEqual(outcomes, ["won", "lost"])

    def test_duplicate_delivery_pair_is_rejected(self) -> None:
        message_id = f"<{uuid.uuid4()}@agentpost.local>"
        self.office.send("cx", "k", "one", message_id=message_id)
        with self.assertRaises(DuplicateDeliveryError):
            self.office.send("cx", "k", "two", message_id=message_id)

    def test_concurrent_duplicate_delivery_has_one_winner(self) -> None:
        message_id = f"<{uuid.uuid4()}@agentpost.local>"
        outcomes: list[str] = []
        barrier = threading.Barrier(2)

        def send() -> None:
            barrier.wait()
            try:
                self.office.send("cx", "k", "same", message_id=message_id)
                outcomes.append("sent")
            except DuplicateDeliveryError:
                outcomes.append("duplicate")

        threads = [threading.Thread(target=send) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertCountEqual(outcomes, ["sent", "duplicate"])
        self.assertEqual(len(self.office.list_messages("k")), 1)
        self.assertEqual(len(self.office.list_messages("cx", "sent")), 1)

    def test_claimed_message_still_blocks_duplicate(self) -> None:
        message_id = f"<{uuid.uuid4()}@agentpost.local>"
        self.office.send("cx", "k", "one", message_id=message_id)
        self.office.claim("k", message_id)
        with self.assertRaises(DuplicateDeliveryError):
            self.office.send("cx", "k", "two", message_id=message_id)

    def test_reply_correlates_to_original(self) -> None:
        question = self.office.send(
            "cx", "k", "Question?", subject="Decision", kind="question"
        )
        answer = self.office.reply("k", question.message_id, "Answer.")
        letter = self.office.read("cx", answer.message_id).letter
        self.assertEqual(letter.kind, "answer")
        self.assertEqual(letter.in_reply_to, question.message_id)
        self.assertEqual(letter.subject, "Re: Decision")
        self.assertEqual(letter.from_agent, "k")
        self.assertEqual(letter.to_agent, "cx")

    def test_fanout_uses_one_id_and_preserves_full_audience(self) -> None:
        self.office.register_profile(profile("pb"))
        self.office.register_profile(profile("c"))
        result = self.office.send_many(
            "cx",
            ("k", "pb", "k", "c"),
            "Panel question?",
            subject="Panel",
            kind="question",
            notify="immediate",
        )
        self.assertEqual(result.failures, ())
        self.assertEqual(len(result.deliveries), 3)
        for recipient in ("k", "pb", "c"):
            letter = self.office.read(recipient, result.message_id).letter
            self.assertEqual(letter.to_agent, recipient)
            self.assertEqual(letter.audience, ("k", "pb", "c"))
            self.assertEqual(letter.message_id, result.message_id)
        sent = self.office.read("cx", result.message_id, ("sent",)).letter
        self.assertEqual(sent.audience, ("k", "pb", "c"))
        self.assertEqual(len(self.office.list_messages("cx", "sent")), 1)

    def test_rapid_messages_have_stable_physical_order(self) -> None:
        first = self.office.send("cx", "k", "first")
        second = self.office.send("cx", "k", "second")
        records = self.office.list_messages("k")
        self.assertEqual([record.letter.body for record in records], ["first", "second"])
        self.assertLess(first.recipient_path.name, second.recipient_path.name)

    def test_unknown_agent_fails_before_delivery(self) -> None:
        with self.assertRaises(UnknownAgentError):
            self.office.send("cx", "missing", "hello")

    def test_oldest_claim_uses_filename_order(self) -> None:
        self.office.send("cx", "k", "first")
        self.office.send("cx", "k", "second")
        self.assertEqual(self.office.claim("k").letter.body, "first")

    def test_profile_rejects_path_like_name(self) -> None:
        invalid = Profile(
            name="../bad",
            display_name="Bad",
            cli="claude",
            kind="project",
            summary="Bad",
            projects=("bad",),
        )
        with self.assertRaises(ValueError):
            self.office.register_profile(invalid)


if __name__ == "__main__":
    unittest.main()
