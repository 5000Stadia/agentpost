from __future__ import annotations

import os
import stat
import sys
import tempfile
import threading
import unittest
import uuid
from contextlib import redirect_stderr
from dataclasses import replace
from io import StringIO
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from agentpost import (  # noqa: E402
    AgentPostError,
    DuplicateDeliveryError,
    Experience,
    InvalidMessageError,
    MessageNotFoundError,
    PostOffice,
    Profile,
    UnknownAgentError,
)
from agentpost.ownership import ConsumerLease  # noqa: E402


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

    def test_profile_address_names_reserve_dot_for_project_qualification(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid agent name"):
            profile("project.nav").validate()
        dotted_project = replace(
            profile("valid"),
            projects=("project.name",),
        )
        with self.assertRaisesRegex(ValueError, "PROJECT.SEAT"):
            dotted_project.validate()

    def test_wipe_agents_removes_mailboxes_bindings_markers_and_group_membership(
        self,
    ) -> None:
        project = Path(self.temp.name) / "shared-project"
        project.mkdir()
        self.office.bind_agent("cx", "codex", project)
        self.office.bind_agent("k", "claude", project)
        self.office.set_group("team", ("cx", "k"))
        self.office.send("cx", "k", "A copy retained by k.")
        self.office.send("k", "cx", "A copy destroyed with cx.")
        attachment = self.root / "runtime" / "codex-sessions" / "cx.json"
        attachment.parent.mkdir(parents=True)
        attachment.write_text('{"agent": "cx"}', encoding="utf-8")
        (self.root / "runtime").chmod(0o700)
        attachment.parent.chmod(0o700)
        attachment.chmod(0o600)

        self.assertEqual(self.office.wipe_agents(("cx",)), ("cx",))
        self.assertFalse(attachment.exists())
        with self.assertRaises(UnknownAgentError):
            self.office.load_profile("cx")
        self.assertEqual(self.office.load_profile("k").name, "k")
        self.assertEqual(
            tuple(binding.agent for binding in self.office.list_bindings()),
            ("k",),
        )
        self.assertEqual(self.office.list_groups(), {"team": ("k",)})
        self.assertEqual(
            self.office.workspace_identity(project)[:2],
            ("k", ("k",)),
        )
        self.assertEqual(
            self.office.list_messages("k", "unread")[0].letter.body,
            "A copy retained by k.",
        )

        self.assertEqual(self.office.wipe_agents(("k",)), ("k",))
        self.assertEqual(self.office.list_profiles(), ())
        self.assertEqual(self.office.list_bindings(), ())
        self.assertEqual(self.office.list_groups(), {})
        self.assertFalse((project / ".agentpost.toml").exists())
        stale_attachment = (
            self.root / "runtime" / "codex-sessions" / "stale.json"
        )
        stale_attachment.parent.mkdir(parents=True, exist_ok=True)
        stale_attachment.write_text('{"agent": "missing"}', encoding="utf-8")
        stale_attachment.chmod(0o600)
        self.assertEqual(
            self.office.wipe_agents((), purge_all_attachments=True),
            (),
        )
        self.assertFalse(stale_attachment.exists())

    def test_wipe_agents_rejects_attachment_directory_symlink_escape(self) -> None:
        for scope in ("agent", "all"):
            with self.subTest(scope=scope), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary) / "post"
                office = PostOffice(root)
                office.register_profile(profile("cx"))
                external = Path(temporary) / "source-repository"
                external.mkdir()
                external_file = external / "release.json"
                external_file.write_text('{"agent": "cx"}', encoding="utf-8")
                runtime = root / "runtime"
                runtime.mkdir(mode=0o700)
                (runtime / "codex-sessions").symlink_to(
                    external,
                    target_is_directory=True,
                )

                with self.assertRaisesRegex(
                    AgentPostError,
                    "cannot securely open AgentPost runtime directory",
                ):
                    office.wipe_agents(
                        ("cx",) if scope == "agent" else (),
                        purge_all_attachments=scope == "all",
                    )

                self.assertEqual(office.load_profile("cx").name, "cx")
                self.assertEqual(
                    external_file.read_text(encoding="utf-8"),
                    '{"agent": "cx"}',
                )

    def test_wipe_agents_rejects_permissive_attachment_directory(self) -> None:
        runtime = self.root / "runtime"
        attachments = runtime / "codex-sessions"
        attachments.mkdir(parents=True)
        runtime.chmod(0o700)
        attachments.chmod(0o755)
        attachment = attachments / "cx.json"
        attachment.write_text('{"agent": "cx"}', encoding="utf-8")
        attachment.chmod(0o600)

        with self.assertRaisesRegex(
            AgentPostError,
            "insecure AgentPost runtime directory",
        ):
            self.office.wipe_agents(("cx",))

        self.assertTrue(attachment.exists())
        self.assertEqual(self.office.load_profile("cx").name, "cx")

    def test_wipe_agents_rolls_back_before_irreversible_stage_cleanup(self) -> None:
        project = Path(self.temp.name) / "rollback-project"
        project.mkdir()
        self.office.bind_agent("cx", "codex", project)
        self.office.set_group("team", ("cx", "k"))
        sent = self.office.send("k", "cx", "Must survive rollback.")

        with patch.object(
            self.office,
            "_rewrite_workspace_identity",
            side_effect=OSError("marker unavailable"),
        ):
            with self.assertRaisesRegex(OSError, "marker unavailable"):
                self.office.wipe_agents(("cx",))

        self.assertEqual(self.office.load_profile("cx").name, "cx")
        self.assertEqual(
            self.office.read("cx", sent.message_id).letter.body,
            "Must survive rollback.",
        )
        self.assertEqual(
            tuple(binding.agent for binding in self.office.list_bindings()),
            ("cx",),
        )
        self.assertEqual(self.office.list_groups(), {"team": ("cx", "k")})

    def test_wipe_serializes_profile_recreation_and_consumer_startup(self) -> None:
        project = Path(self.temp.name) / "serialized-wipe-project"
        project.mkdir()
        self.office.bind_agent("cx", "codex", project)
        detached = threading.Event()
        continue_wipe = threading.Event()
        registration_started = threading.Event()
        profile_registered = threading.Event()
        lease_acquired = threading.Event()
        release_lease = threading.Event()
        wipe_results = []
        worker_errors = []
        original_rewrite = self.office._rewrite_workspace_identity

        def pause_after_detach(*args, **kwargs):
            detached.set()
            if not continue_wipe.wait(3):
                raise AssertionError("test did not release the paused wipe")
            return original_rewrite(*args, **kwargs)

        def run_wipe() -> None:
            try:
                wipe_results.append(self.office.wipe_agents(("cx",)))
            except BaseException as exc:
                worker_errors.append(exc)

        def recreate_and_consume() -> None:
            lease = None
            try:
                registration_started.set()
                self.office.register_profile(profile("cx", "codex"))
                profile_registered.set()
                lease = ConsumerLease(self.office, "cx", "replacement-consumer")
                if not lease.acquire():
                    raise AssertionError("replacement consumer did not acquire")
                lease_acquired.set()
                if not release_lease.wait(3):
                    raise AssertionError("test did not release replacement lease")
            except BaseException as exc:
                worker_errors.append(exc)
            finally:
                if lease is not None:
                    lease.release()

        with patch.object(
            self.office,
            "_rewrite_workspace_identity",
            side_effect=pause_after_detach,
        ):
            wipe_thread = threading.Thread(target=run_wipe)
            wipe_thread.start()
            self.assertTrue(detached.wait(3))

            replacement_thread = threading.Thread(target=recreate_and_consume)
            replacement_thread.start()
            self.assertTrue(registration_started.wait(3))
            self.assertFalse(profile_registered.wait(0.2))
            self.assertFalse(lease_acquired.is_set())

            continue_wipe.set()
            wipe_thread.join(3)
            self.assertFalse(wipe_thread.is_alive())

        self.assertEqual(wipe_results, [("cx",)])
        self.assertTrue(profile_registered.wait(3))
        self.assertTrue(lease_acquired.wait(3))
        release_lease.set()
        replacement_thread.join(3)
        self.assertFalse(replacement_thread.is_alive())
        self.assertEqual(worker_errors, [])

    def test_wipe_preserves_original_stage_on_recreated_source_collision(
        self,
    ) -> None:
        project = Path(self.temp.name) / "colliding-rollback-project"
        project.mkdir()
        self.office.bind_agent("cx", "codex", project)
        sent = self.office.send("k", "cx", "Original mailbox must survive.")
        original_letter = sent.recipient_path.read_bytes()
        source = self.root / "agents" / "cx"
        replacement_profile = (source / "profile.toml").read_bytes()
        collision_marker = source / "replacement.txt"
        original_rewrite = self.office._rewrite_workspace_identity

        def recreate_source(*args, **kwargs):
            result = original_rewrite(*args, **kwargs)
            source.mkdir(mode=0o700)
            for directory in ("tmp", "unread", "read", "sent", "adapter"):
                (source / directory).mkdir(mode=0o700)
            (source / "profile.toml").write_bytes(replacement_profile)
            (source / "profile.toml").chmod(0o600)
            collision_marker.write_text("replacement", encoding="utf-8")
            return result

        with patch.object(
            self.office,
            "_rewrite_workspace_identity",
            side_effect=recreate_source,
        ):
            with self.assertRaisesRegex(
                AgentPostError,
                "recovery staging was preserved.*replacement collides",
            ):
                self.office.wipe_agents(("cx",))

        stages = tuple(self.root.glob(".wipe-*"))
        self.assertEqual(len(stages), 1)
        staged_letter = stages[0] / "cx" / "unread" / sent.recipient_path.name
        self.assertEqual(staged_letter.read_bytes(), original_letter)
        self.assertEqual(collision_marker.read_text(encoding="utf-8"), "replacement")
        self.assertEqual(
            tuple(binding.agent for binding in self.office.list_bindings()),
            ("cx",),
        )

    def test_new_runtime_state_is_private_even_with_permissive_umask(self) -> None:
        root = Path(self.temp.name) / "private-post"
        original_umask = os.umask(0)
        try:
            office = PostOffice(root)
            office.register_profile(profile("private"))
            office.register_profile(profile("recipient"))
            result = office.send("private", "recipient", "owner only")
            request = office.request_notification(
                "private",
                "recipient",
                result.message_id,
            )
            project = Path(self.temp.name) / "private-project"
            project.mkdir()
            office.bind_agent("private", "python", project)
        finally:
            os.umask(original_umask)

        for directory, _names, files in os.walk(root):
            current = Path(directory)
            self.assertEqual(stat.S_IMODE(current.stat().st_mode), 0o700)
            for name in files:
                self.assertEqual(
                    stat.S_IMODE((current / name).stat().st_mode),
                    0o600,
                )
        self.assertEqual(stat.S_IMODE(request.path.stat().st_mode), 0o600)
        self.assertTrue(
            tuple((root / "agents" / "recipient" / "adapter").glob("delivery-*.lock"))
        )
        self.assertEqual(
            stat.S_IMODE((project / ".agentpost.toml").stat().st_mode),
            0o600,
        )

    def test_migrate_hardens_runtime_without_following_symlinks(self) -> None:
        delivered = self.office.send("cx", "k", "preserve bytes")
        external = Path(self.temp.name) / "external"
        external.write_text("outside", encoding="ascii")
        external.chmod(0o666)
        link = self.root / "external-link"
        link.symlink_to(external)

        durable_paths = (
            self.root / "config.toml",
            self.root / "agents" / "cx" / "profile.toml",
            delivered.recipient_path,
            delivered.sent_path,
        )
        before = {path: path.read_bytes() for path in durable_paths}
        for directory in (self.root, self.root / "agents", self.root / "agents" / "k"):
            directory.chmod(0o777)
        for path in durable_paths:
            path.chmod(0o666)

        actions = self.office.migrate()

        self.assertTrue(
            any(action.startswith("runtime permissions: ") for action in actions)
        )
        self.assertEqual({path: path.read_bytes() for path in durable_paths}, before)
        for directory, names, files in os.walk(self.root, followlinks=False):
            current = Path(directory)
            self.assertEqual(stat.S_IMODE(current.stat().st_mode), 0o700)
            names[:] = [name for name in names if not (current / name).is_symlink()]
            for name in files:
                path = current / name
                if not path.is_symlink():
                    self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(external.stat().st_mode), 0o666)

        second_actions = self.office.migrate()

        self.assertFalse(
            any(action.startswith("runtime permissions: ") for action in second_actions)
        )
        self.assertEqual({path: path.read_bytes() for path in durable_paths}, before)
        for directory, names, files in os.walk(self.root, followlinks=False):
            current = Path(directory)
            self.assertEqual(stat.S_IMODE(current.stat().st_mode), 0o700)
            names[:] = [name for name in names if not (current / name).is_symlink()]
            for name in files:
                path = current / name
                if not path.is_symlink():
                    self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(external.stat().st_mode), 0o666)

    def test_migrate_continues_after_permission_hardening_failure(self) -> None:
        blocked = self.root / "config.toml"
        hardened = self.root / "agents" / "cx" / "profile.toml"
        blocked.chmod(0o666)
        hardened.chmod(0o666)
        real_chmod = os.chmod

        def selective_chmod(path: os.PathLike[str] | str, mode: int) -> None:
            if Path(path) == blocked:
                raise PermissionError("permission denied by test")
            real_chmod(path, mode)

        errors = StringIO()
        with (
            patch("agentpost.core.os.chmod", side_effect=selective_chmod),
            redirect_stderr(errors),
        ):
            actions = self.office.migrate()

        self.assertIn("runtime permissions: 1 tightened, 1 failed", actions)
        self.assertIn(str(blocked), errors.getvalue())
        self.assertIn("permission denied by test", errors.getvalue())
        self.assertEqual(stat.S_IMODE(blocked.stat().st_mode), 0o666)
        self.assertEqual(stat.S_IMODE(hardened.stat().st_mode), 0o600)

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

    def test_migrate_refuses_to_guess_an_ambiguous_legacy_workspace_default(self) -> None:
        project = Path(self.temp.name) / "ambiguous-legacy"
        project.mkdir()
        self.office.bind_agent("cx", "codex", project)
        self.office.bind_agent("k", "claude", project)
        (project / ".agentpost.toml").unlink()

        actions = self.office.migrate()

        self.assertFalse((project / ".agentpost.toml").exists())
        self.assertIn(
            f"workspace {project}: skipped ambiguous defaults cx, k",
            actions,
        )

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
        self.assertEqual(self.office.list_messages("k", "unread"), ())
        self.assertEqual(
            self.office.read("k", question.message_id, states=("read",)).state,
            "read",
        )

    def test_reply_allows_corrections_to_an_already_read_original(self) -> None:
        question = self.office.send("cx", "k", "Question?", kind="question")
        self.office.claim("k", question.message_id)
        first = self.office.reply("k", question.message_id, "First answer.")
        second = self.office.reply("k", question.message_id, "Correction.")
        self.assertEqual(
            self.office.read("cx", first.message_id).letter.in_reply_to,
            question.message_id,
        )
        self.assertEqual(
            self.office.read("cx", second.message_id).letter.in_reply_to,
            question.message_id,
        )

    def test_reply_validation_failure_leaves_original_unread(self) -> None:
        question = self.office.send("cx", "k", "Question?", kind="question")
        with self.assertRaisesRegex(ValueError, "body must not be empty"):
            self.office.reply("k", question.message_id, "")
        self.assertEqual(
            self.office.read("k", question.message_id, states=("unread",)).state,
            "unread",
        )

    def test_reply_delivery_failure_leaves_claimed_original_read(self) -> None:
        question = self.office.send("cx", "k", "Question?", kind="question")
        with patch.object(
            self.office,
            "send",
            side_effect=AgentPostError("delivery state is ambiguous"),
        ):
            with self.assertRaisesRegex(AgentPostError, "delivery state is ambiguous"):
                self.office.reply("k", question.message_id, "Answer.")
        self.assertEqual(self.office.list_messages("k", "unread"), ())
        self.assertEqual(
            self.office.read("k", question.message_id, states=("read",)).state,
            "read",
        )

    def test_competing_replies_that_observe_unread_have_one_winner(self) -> None:
        question = self.office.send("cx", "k", "Question?", kind="question")
        original_read = self.office.read
        barrier = threading.Barrier(2)
        outcomes: list[str] = []

        def synchronized_read(agent, message_id, states=("unread", "read")):
            record = original_read(agent, message_id, states)
            if agent == "k" and record.letter.message_id == question.message_id:
                barrier.wait()
            return record

        def reply() -> None:
            try:
                self.office.reply("k", question.message_id, "Answer.")
                outcomes.append("sent")
            except MessageNotFoundError:
                outcomes.append("lost")

        with patch.object(self.office, "read", side_effect=synchronized_read):
            threads = [threading.Thread(target=reply) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

        self.assertCountEqual(outcomes, ["sent", "lost"])
        self.assertEqual(len(self.office.list_messages("cx", "unread")), 1)

    def test_sender_can_request_fresh_attention_for_existing_unread_mail(self) -> None:
        sent = self.office.send("cx", "k", "Please revisit this.")
        request = self.office.request_notification(
            "cx", "k", sent.message_id, notify="immediate"
        )
        self.assertTrue(request.path.is_file())
        self.assertEqual(request.message_id, sent.message_id)
        self.assertEqual(request.notify, "immediate")
        self.assertEqual(self.office.notification_requests("k"), (request,))
        self.assertTrue(self.office.acknowledge_notification("k", request.request_id))
        self.assertEqual(self.office.notification_requests("k"), ())
        self.assertEqual(len(self.office.list_messages("k", "unread")), 1)

    def test_notification_request_requires_original_sender_and_unread_mail(self) -> None:
        self.office.register_profile(profile("pb"))
        sent = self.office.send("cx", "k", "Sender-owned pointer.")
        with self.assertRaisesRegex(AgentPostError, "only the original sender cx"):
            self.office.request_notification("pb", "k", sent.message_id)
        self.office.claim("k", sent.message_id)
        with self.assertRaises(MessageNotFoundError):
            self.office.request_notification("cx", "k", sent.message_id)

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

    def test_verify_send_path_passes_on_a_healthy_mailbox(self) -> None:
        detail = self.office.verify_send_path("cx")
        self.assertIn("delivery lock", detail)

    def test_verify_send_path_leaves_no_artifacts_behind(self) -> None:
        agent_dir = self.root / "agents" / "cx"
        before = {
            name: sorted(p.name for p in (agent_dir / name).iterdir())
            for name in ("tmp", "unread", "read", "sent", "adapter")
        }
        self.office.verify_send_path("cx")
        after = {
            name: sorted(p.name for p in (agent_dir / name).iterdir())
            for name in ("tmp", "unread", "read", "sent", "adapter")
        }
        # The notification queue is created on demand, exactly as
        # request_notification creates it; nothing else may change.
        before["adapter"] = sorted({*before["adapter"], "notifications"})
        self.assertEqual(after, before)
        self.assertEqual(self.office.list_messages("cx"), ())
        self.assertEqual(self.office.list_messages("cx", "sent"), ())

    def test_verify_send_path_detects_an_unwritable_sent_archive(self) -> None:
        sent = self.root / "agents" / "cx" / "sent"
        sent.chmod(0o500)
        try:
            with self.assertRaises(AgentPostError) as caught:
                self.office.verify_send_path("cx")
        finally:
            sent.chmod(0o700)
        self.assertIn("send path broken", str(caught.exception))

    def test_verify_send_path_detects_a_missing_mailbox_directory(self) -> None:
        (self.root / "agents" / "cx" / "tmp").rmdir()
        with self.assertRaises(AgentPostError) as caught:
            self.office.verify_send_path("cx")
        self.assertIn("missing mailbox directory: tmp", str(caught.exception))

    def test_verify_send_path_rejects_an_unknown_agent(self) -> None:
        with self.assertRaises(UnknownAgentError):
            self.office.verify_send_path("nobody")

    def test_verify_send_path_does_not_disturb_existing_mail(self) -> None:
        delivered = self.office.send("k", "cx", "keep me")
        self.office.verify_send_path("cx")
        record = self.office.read("cx", delivered.message_id)
        self.assertEqual(record.letter.body, "keep me")
        self.assertEqual(len(self.office.list_messages("cx")), 1)


if __name__ == "__main__":
    unittest.main()
