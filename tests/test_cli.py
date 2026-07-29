from __future__ import annotations

import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from agentpost import PostOffice, Profile, UnknownAgentError  # noqa: E402
from agentpost.cli import _infer_join_agent, _join, main  # noqa: E402
from agentpost.installer import UpgradeResult  # noqa: E402


class JoinCommandTest(unittest.TestCase):
    def setUp(self) -> None:
        self.agentpost_environment = {
            name: os.environ.pop(name, None)
            for name in (
                "AGENTPOST_AGENT",
                "AGENTPOST_CODEX_BRIDGE",
                "AGENTPOST_ROOT",
            )
        }
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "post"
        self.project = Path(self.temp.name) / "application"
        self.project.mkdir()
        self.office = PostOffice(self.root)
        self.office.register_profile(
            Profile(
                name="app",
                display_name="Application",
                cli="python",
                kind="project",
                summary="Python application agent",
                projects=("application",),
                project_roots=(str(self.project),),
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

    def tearDown(self) -> None:
        for name, value in self.agentpost_environment.items():
            os.environ.pop(name, None)
            if value is not None:
                os.environ[name] = value
        self.temp.cleanup()

    def test_bare_join_resolves_and_is_idempotent(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            self.assertEqual(_join(self.office, None, None, self.project), 0)
            self.assertEqual(_join(self.office, None, None, self.project), 0)
        self.assertIn("JOINED\tapp\tpython", output.getvalue())
        self.assertEqual(len(self.office.list_bindings()), 1)

    def test_explicit_join_handles_a_moved_root(self) -> None:
        moved = Path(self.temp.name) / "moved"
        moved.mkdir()
        with redirect_stdout(StringIO()):
            self.assertEqual(_join(self.office, "app", None, moved), 0)
        self.assertEqual(self.office.list_bindings()[0].project, str(moved.resolve()))

    def test_bare_join_reports_real_ambiguity(self) -> None:
        self.office.register_profile(
            Profile(
                name="reviewer",
                display_name="Reviewer",
                cli="python",
                kind="specialist",
                summary="Review agent in the same project",
                specialties=("review",),
                project_roots=(str(self.project),),
            )
        )
        with self.assertRaisesRegex(ValueError, r"app.*reviewer"):
            _infer_join_agent(self.office, self.project, None)

    def test_message_is_a_sender_inferred_named_channel(self) -> None:
        output = StringIO()
        with patch.dict("os.environ", {"AGENTPOST_AGENT": "app"}), redirect_stdout(
            output
        ):
            result = main(
                [
                    "--root",
                    str(self.root),
                    "message",
                    "pattern-buffer.pb",
                    "Please inspect the world model.",
                ]
            )
        self.assertEqual(result, 0)
        self.assertIn("FROM\tapp", output.getvalue())
        self.assertIn("TO\tpb\toffline\tqueued", output.getvalue())
        record = self.office.list_messages("pb")[0]
        self.assertEqual(record.letter.from_agent, "app")
        self.assertEqual(record.letter.body, "Please inspect the world model.")

    def test_reply_reads_a_dash_body_from_stdin(self) -> None:
        request = self.office.send("pb", "app", "Please review this.")
        body = "Substantive review response.\nSecond line.\n"
        with patch("sys.stdin", StringIO(body)), redirect_stdout(StringIO()):
            result = main(
                [
                    "--root",
                    str(self.root),
                    "reply",
                    "app",
                    request.message_id,
                    "-",
                ]
            )
        self.assertEqual(result, 0)
        reply = self.office.list_messages("pb")[0].letter
        self.assertEqual(reply.body, body)
        self.assertEqual(reply.in_reply_to, request.message_id)
        self.assertEqual(reply.notify, "idle")

    def test_reply_infers_sender_from_workspace_identity(self) -> None:
        request = self.office.send("pb", "app", "Please review this.")
        with patch.dict("os.environ", {"AGENTPOST_AGENT": "app"}, clear=False):
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                result = main(
                    [
                        "--root",
                        str(self.root),
                        "reply",
                        request.message_id,
                        "Inferred sender response.",
                    ]
                )
        self.assertEqual(result, 0)
        reply = self.office.list_messages("pb")[0].letter
        self.assertEqual(reply.from_agent, "app")
        self.assertEqual(reply.in_reply_to, request.message_id)
        self.assertEqual(reply.notify, "idle")

    def test_reply_to_question_defaults_to_immediate_notification(self) -> None:
        request = self.office.send(
            "pb", "app", "Are these semantics correct?", kind="question"
        )
        with patch.dict("os.environ", {"AGENTPOST_AGENT": "app"}, clear=False):
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                result = main(
                    [
                        "--root",
                        str(self.root),
                        "reply",
                        request.message_id,
                        "Yes.",
                    ]
                )
        self.assertEqual(result, 0)
        self.assertEqual(self.office.list_messages("pb")[0].letter.notify, "immediate")

    def test_sender_can_re_notify_existing_unread_mail_without_resending(self) -> None:
        sent = self.office.send("app", "pb", "Existing review request.")
        output = StringIO()
        with patch.dict("os.environ", {"AGENTPOST_AGENT": "app"}, clear=False):
            with redirect_stdout(output), redirect_stderr(StringIO()):
                result = main(
                    [
                        "--root",
                        str(self.root),
                        "notify",
                        "pattern-buffer.pb",
                        sent.message_id,
                        "--mode",
                        "immediate",
                    ]
                )
        self.assertEqual(result, 0)
        self.assertIn(f"NOTIFY\t{sent.message_id}", output.getvalue())
        requests = self.office.notification_requests("pb")
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].notify, "immediate")
        self.assertEqual(len(self.office.list_messages("pb", "unread")), 1)

    def test_bare_doctor_infers_agent_and_project_from_workspace(self) -> None:
        with patch("agentpost.cli.Path.cwd", return_value=self.project):
            with patch("agentpost.cli.doctor", return_value=()) as run_doctor:
                with redirect_stdout(StringIO()):
                    result = main(["--root", str(self.root), "doctor"])
        self.assertEqual(result, 0)
        called = run_doctor.call_args.args
        self.assertEqual(called[1:], ("app", self.project, None))

    def test_offline_delivery_warning_is_concise(self) -> None:
        output = StringIO()
        errors = StringIO()
        with patch.dict("os.environ", {"AGENTPOST_AGENT": "app"}, clear=False):
            with redirect_stdout(output), redirect_stderr(errors):
                result = main(
                    [
                        "--root",
                        str(self.root),
                        "message",
                        "pattern-buffer.pb",
                        "Queued message.",
                    ]
                )
        self.assertEqual(result, 0)
        # pb is registered but never bound, so there is no adapter to start.
        self.assertIn("recipient has no connected adapter", errors.getvalue())
        self.assertNotIn("queued for its next adapter start", errors.getvalue())
        self.assertNotIn("notifier not armed", errors.getvalue())
        self.assertNotIn("generation", errors.getvalue().lower())

    def test_offline_delivery_warning_promises_a_start_only_when_bound(self) -> None:
        self.office.bind_agent("pb", "claude", self.project)
        output = StringIO()
        errors = StringIO()
        with patch.dict("os.environ", {"AGENTPOST_AGENT": "app"}, clear=False):
            with redirect_stdout(output), redirect_stderr(errors):
                result = main(
                    [
                        "--root",
                        str(self.root),
                        "message",
                        "pattern-buffer.pb",
                        "Queued message.",
                    ]
                )
        self.assertEqual(result, 0)
        self.assertIn(
            "recipient offline; queued for its next adapter start", errors.getvalue()
        )
        self.assertNotIn("no connected adapter", errors.getvalue())

    def test_optional_channel_bodies_may_follow_flags(self) -> None:
        request = self.office.send("pb", "app", "Please reply.")
        commands = (
            [
                "message",
                "pattern-buffer.pb",
                "--notify",
                "immediate",
                "message after flag",
            ],
            [
                "question",
                "pattern-buffer.pb",
                "--subject",
                "Review",
                "question after flag",
            ],
            [
                "reply",
                "app",
                request.message_id,
                "--notify",
                "idle",
                "reply after flag",
            ],
        )
        with patch.dict("os.environ", {"AGENTPOST_AGENT": "app"}, clear=False):
            for command in commands:
                with self.subTest(command=command[0]):
                    with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                        result = main(["--root", str(self.root), *command])
                    self.assertEqual(result, 0)
        self.assertEqual(
            [record.letter.body for record in self.office.list_messages("pb")],
            ["message after flag", "question after flag", "reply after flag"],
        )

    def test_codex_install_forwards_session_close_confirmation(self) -> None:
        with patch("agentpost.cli.install") as install:
            result = main(
                [
                    "--root",
                    str(self.root),
                    "install",
                    "codex",
                    "--agent",
                    "app",
                    "--project",
                    str(self.project),
                    "--confirm-codex-sessions-closed",
                ]
            )
        self.assertEqual(result, 0)
        install.assert_called_once()
        args, kwargs = install.call_args
        self.assertEqual(args[0].root, self.root)
        self.assertEqual(args[1:], ("codex", "app", self.project))
        self.assertEqual(kwargs, {"confirm_codex_sessions_closed": True})

    def test_codex_join_forwards_session_close_confirmation(self) -> None:
        with patch("agentpost.cli.install") as install:
            with redirect_stdout(StringIO()):
                result = main(
                    [
                        "--root",
                        str(self.root),
                        "join",
                        "app",
                        "--cli",
                        "codex",
                        "--project",
                        str(self.project),
                        "--confirm-codex-sessions-closed",
                    ]
                )
        self.assertEqual(result, 0)
        install.assert_called_once()
        args, kwargs = install.call_args
        self.assertEqual(args[0].root, self.root)
        self.assertEqual(args[1:], ("codex", "app", self.project))
        self.assertEqual(kwargs, {"confirm_codex_sessions_closed": True})

    def test_codex_uninstall_forwards_session_close_confirmation(self) -> None:
        with patch("agentpost.cli.uninstall") as uninstall:
            result = main(
                [
                    "--root",
                    str(self.root),
                    "uninstall",
                    "codex",
                    "--project",
                    str(self.project),
                    "--confirm-codex-sessions-closed",
                ]
            )
        self.assertEqual(result, 0)
        uninstall.assert_called_once_with(
            "codex",
            self.project,
            confirm_codex_sessions_closed=True,
        )

    def test_identities_and_resolve_expose_the_address_book(self) -> None:
        identities = StringIO()
        with redirect_stdout(identities):
            self.assertEqual(
                main(["--root", str(self.root), "identities"]),
                0,
            )
        self.assertIn(
            "agent\tpb\toffline\tpattern-buffer.pb\tPattern Buffer\t"
            "pattern-buffer\t",
            identities.getvalue(),
        )
        self.assertTrue(identities.getvalue().startswith("type\taddress\tattention"))

        resolved = StringIO()
        with redirect_stdout(resolved):
            self.assertEqual(
                main(
                    [
                        "--root",
                        str(self.root),
                        "resolve",
                        "Pattern Buffer",
                        "--project",
                        "pattern-buffer",
                    ]
                ),
                0,
            )
        self.assertEqual(
            resolved.getvalue(),
            "agent\tpb\toffline\tpattern-buffer.pb\tPattern Buffer\n",
        )

    def test_project_directory_filters_and_cross_project_addresses(self) -> None:
        directory = StringIO()
        with redirect_stdout(directory):
            self.assertEqual(
                main(
                    [
                        "--root",
                        str(self.root),
                        "identities",
                        "--project",
                        "pattern-buffer",
                    ]
                ),
                0,
            )
        self.assertIn("pattern-buffer.pb", directory.getvalue())
        self.assertNotIn("\tagent\tapp\t", f"\t{directory.getvalue()}")

        profiles = StringIO()
        with redirect_stdout(profiles):
            self.assertEqual(
                main(
                    [
                        "--root",
                        str(self.root),
                        "profiles",
                        "--project",
                        "pattern-buffer",
                        "--all",
                    ]
                ),
                0,
            )
        self.assertIn(
            "pb\toffline\tclaude\tproject\tPersistent world state",
            profiles.getvalue(),
        )
        self.assertNotIn("app\toffline", profiles.getvalue())

        status = StringIO()
        with redirect_stdout(status):
            self.assertEqual(
                main(
                    [
                        "--root",
                        str(self.root),
                        "status",
                        "--project",
                        "pattern-buffer",
                    ]
                ),
                0,
            )
        self.assertTrue(status.getvalue().startswith("pb\toffline\t"))

        errors = StringIO()
        with patch.dict("os.environ", {"AGENTPOST_AGENT": "app"}, clear=False):
            with redirect_stdout(StringIO()), redirect_stderr(errors):
                result = main(
                    [
                        "--root",
                        str(self.root),
                        "message",
                        "pb",
                        "This must not cross projects.",
                    ]
                )
        self.assertEqual(result, 1)
        self.assertIn(
            "cross-project addresses must use PROJECT.SEAT",
            errors.getvalue(),
        )

    def test_project_wipe_previews_exact_boxes_and_requires_confirmation(
        self,
    ) -> None:
        self.office.register_profile(
            Profile(
                name="pbr",
                display_name="Pattern Buffer Review",
                cli="codex",
                kind="role",
                summary="Reviews Pattern Buffer",
                roles=("code review",),
                projects=("pattern-buffer",),
                handles=("codereview",),
            )
        )
        errors = StringIO()
        with patch.dict("os.environ", {"AGENTPOST_AGENT": "app"}, clear=False):
            with redirect_stderr(errors):
                result = main(
                    [
                        "--root",
                        str(self.root),
                        "wipe",
                        "project",
                        "pattern-buffer",
                    ]
                )
        self.assertEqual(result, 1)
        self.assertIn("Affected mailboxes: pb,pbr", errors.getvalue())
        self.assertIn("--confirm 'pb,pbr'", errors.getvalue())
        self.assertEqual(self.office.load_profile("pb").name, "pb")

        output = StringIO()
        with patch.dict("os.environ", {"AGENTPOST_AGENT": "app"}, clear=False):
            with redirect_stdout(output):
                result = main(
                    [
                        "--root",
                        str(self.root),
                        "wipe",
                        "project",
                        "pattern-buffer",
                        "--confirm",
                        "pb,pbr",
                    ]
                )
        self.assertEqual(result, 0)
        self.assertIn("WIPED\tproject\tpb,pbr", output.getvalue())
        self.assertIn("RECOVERY\tirreversible", output.getvalue())
        with self.assertRaises(UnknownAgentError):
            self.office.load_profile("pb")
        with self.assertRaises(UnknownAgentError):
            self.office.load_profile("pbr")

    def test_wiping_another_agent_requires_confirmation_but_self_wipe_does_not(
        self,
    ) -> None:
        errors = StringIO()
        with patch.dict("os.environ", {"AGENTPOST_AGENT": "app"}, clear=False):
            with redirect_stderr(errors):
                result = main(
                    [
                        "--root",
                        str(self.root),
                        "wipe",
                        "agent",
                        "pattern-buffer.pb",
                    ]
                )
        self.assertEqual(result, 1)
        self.assertIn("Affected mailboxes: pb", errors.getvalue())

        with patch.dict("os.environ", {"AGENTPOST_AGENT": "app"}, clear=False):
            with redirect_stdout(StringIO()):
                result = main(
                    [
                        "--root",
                        str(self.root),
                        "wipe",
                        "agent",
                    ]
                )
        self.assertEqual(result, 0)
        with self.assertRaises(UnknownAgentError):
            self.office.load_profile("app")

    def test_all_agent_wipe_rejects_a_stale_confirmation_list(self) -> None:
        errors = StringIO()
        with patch.dict("os.environ", {"AGENTPOST_AGENT": "app"}, clear=False):
            with redirect_stderr(errors):
                result = main(
                    [
                        "--root",
                        str(self.root),
                        "wipe",
                        "all",
                        "--confirm",
                        "app",
                    ]
                )
        self.assertEqual(result, 1)
        self.assertIn("Affected mailboxes: app,pb", errors.getvalue())
        self.assertEqual(
            tuple(profile.name for profile in self.office.list_profiles()),
            ("app", "pb"),
        )

    def test_profile_help_teaches_searchable_durable_nameplates(self) -> None:
        output = StringIO()
        with redirect_stdout(output), self.assertRaises(SystemExit) as stopped:
            main(["profile-register", "--help"])
        self.assertEqual(stopped.exception.code, 0)
        help_text = output.getvalue()
        self.assertIn("what this agent owns", help_text)
        self.assertIn("Two to five concrete request categories", help_text)
        self.assertIn("Do not include current task/status", help_text)
        self.assertIn("profile-register reviewer", help_text)

    def test_profile_registration_records_organization_and_boundaries(self) -> None:
        with redirect_stdout(StringIO()):
            result = main(
                [
                    "--root",
                    str(self.root),
                    "profile-register",
                    "release",
                    "--display-name",
                    "Release Engineering",
                    "--cli",
                    "python",
                    "--kind",
                    "specialist",
                    "--summary",
                    "Owns release automation and packaging decisions.",
                    "--organization",
                    "Platform",
                    "--roles",
                    "release engineering",
                    "--specialties",
                    "packaging,reproducible builds",
                    "--handles",
                    "release reviews,build failures",
                    "--does-not-handle",
                    "product roadmap,marketing copy",
                ]
            )
        self.assertEqual(result, 0)
        profile = self.office.load_profile("release")
        self.assertEqual(profile.organization, "Platform")
        self.assertEqual(profile.handles, ("release reviews", "build failures"))
        self.assertEqual(
            profile.does_not_handle,
            ("product roadmap", "marketing copy"),
        )

    def _alternate_seat_letter(self) -> str:
        """A workspace whose default seat is not the addressed seat."""
        self.office.register_profile(
            Profile(
                name="alt",
                display_name="Alternate Seat",
                cli="codex",
                kind="role",
                summary="Alternate review seat in the same workspace",
                roles=("review",),
            )
        )
        self.office.bind_agent("app", "python", self.project)
        return self.office.send("pb", "alt", "Addressed to the alt seat.").message_id

    def test_mailbox_miss_names_the_acting_seat_and_the_rule(self) -> None:
        message_id = self._alternate_seat_letter()
        errors = StringIO()
        with patch("pathlib.Path.cwd", return_value=self.project):
            with redirect_stderr(errors):
                result = main(
                    ["--root", str(self.root), "reply", message_id, "an answer"]
                )
        self.assertEqual(result, 1)
        text = errors.getvalue()
        self.assertIn("acted as app by workspace default", text)
        self.assertIn("--from NAME", text)
        # The bare mailbox-miss wording must survive for anyone matching on it.
        self.assertIn("message not found for app", text)

    def test_mailbox_miss_reports_an_explicit_identity_as_explicit(self) -> None:
        message_id = self._alternate_seat_letter()
        errors = StringIO()
        with patch.dict("os.environ", {"AGENTPOST_AGENT": "app"}, clear=False):
            with patch("pathlib.Path.cwd", return_value=self.project):
                with redirect_stderr(errors):
                    result = main(
                        ["--root", str(self.root), "reply", message_id, "an answer"]
                    )
        self.assertEqual(result, 1)
        self.assertIn("acted as app by explicit AGENTPOST_AGENT", errors.getvalue())

    def test_addressed_seat_replies_without_from(self) -> None:
        message_id = self._alternate_seat_letter()
        output = StringIO()
        with patch.dict("os.environ", {"AGENTPOST_AGENT": "alt"}, clear=False):
            with patch("pathlib.Path.cwd", return_value=self.project):
                with redirect_stdout(output), redirect_stderr(StringIO()):
                    result = main(
                        ["--root", str(self.root), "reply", message_id, "an answer"]
                    )
        self.assertEqual(result, 0)
        self.assertIn("@agentpost.local", output.getvalue())

    def _reviewer_seat_letter(self) -> str:
        """A registered alternate seat sharing the workspace project root."""
        self.office.register_profile(
            Profile(
                name="review",
                display_name="Application Reviewer",
                cli="codex",
                kind="role",
                summary="Review seat sharing the application project root",
                roles=("review",),
                project_roots=(str(self.project),),
            )
        )
        self.office.bind_agent("app", "python", self.project)
        return self.office.send(
            "pb", "review", "Addressed to the review seat."
        ).message_id

    def test_reply_answers_from_the_seat_holding_the_letter(self) -> None:
        message_id = self._reviewer_seat_letter()
        with patch("pathlib.Path.cwd", return_value=self.project):
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                result = main(
                    ["--root", str(self.root), "reply", message_id, "an answer"]
                )
        self.assertEqual(result, 0)
        reply = self.office.list_messages("pb")[0].letter
        self.assertEqual(reply.from_agent, "review")
        self.assertEqual(reply.in_reply_to, message_id)

    def test_reply_keeps_the_workspace_default_that_holds_the_letter(self) -> None:
        self.office.bind_agent("app", "python", self.project)
        request = self.office.send("pb", "app", "Please review this.")
        with patch("pathlib.Path.cwd", return_value=self.project):
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                result = main(
                    [
                        "--root",
                        str(self.root),
                        "reply",
                        request.message_id,
                        "an answer",
                    ]
                )
        self.assertEqual(result, 0)
        self.assertEqual(self.office.list_messages("pb")[0].letter.from_agent, "app")

    def test_reply_prefers_the_workspace_default_holding_a_shared_letter(self) -> None:
        self._reviewer_seat_letter()
        fanout = self.office.send_many("pb", ("app", "review"), "Addressed to both.")
        with patch("pathlib.Path.cwd", return_value=self.project):
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                result = main(
                    ["--root", str(self.root), "reply", fanout.message_id, "an answer"]
                )
        # Both seats hold a copy, so inference stays the tiebreak.
        self.assertEqual(result, 0)
        self.assertEqual(self.office.list_messages("pb")[0].letter.from_agent, "app")

    def test_reply_refuses_to_guess_between_two_alternate_seats(self) -> None:
        self._reviewer_seat_letter()
        self.office.register_profile(
            Profile(
                name="audit",
                display_name="Application Auditor",
                cli="codex",
                kind="role",
                summary="Second alternate seat sharing the project root",
                roles=("audit",),
                project_roots=(str(self.project),),
            )
        )
        fanout = self.office.send_many(
            "pb", ("review", "audit"), "Addressed to both alternates."
        )
        errors = StringIO()
        with patch("pathlib.Path.cwd", return_value=self.project):
            with redirect_stderr(errors):
                result = main(
                    ["--root", str(self.root), "reply", fanout.message_id, "an answer"]
                )
        self.assertEqual(result, 1)
        text = errors.getvalue()
        self.assertIn("audit, review", text)
        self.assertIn("--from NAME", text)

    def test_explicit_from_outranks_the_seat_holding_the_letter(self) -> None:
        message_id = self._reviewer_seat_letter()
        errors = StringIO()
        with patch("pathlib.Path.cwd", return_value=self.project):
            with redirect_stderr(errors):
                result = main(
                    [
                        "--root",
                        str(self.root),
                        "reply",
                        "--from",
                        "app",
                        message_id,
                        "an answer",
                    ]
                )
        self.assertEqual(result, 1)
        self.assertIn("acted as app by explicit --from", errors.getvalue())

    def test_upgrade_reports_each_binding_and_fails_only_on_failure(self) -> None:
        self.office.bind_agent("app", "python", self.project)
        output = StringIO()
        errors = StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            result = main(["--root", str(self.root), "upgrade", "--dry-run"])
        self.assertEqual(result, 0)
        self.assertIn("SKIPPED\tapp\tpython", output.getvalue())
        self.assertNotIn("restart", errors.getvalue())

    def test_upgrade_names_the_restart_and_exits_nonzero_on_failure(self) -> None:
        self.office.bind_agent("pb", "claude", self.project)
        results = (
            UpgradeResult("pb", "claude", str(self.project), "upgraded", "0.0.7"),
            UpgradeResult("app", "codex", str(self.project), "failed", "sessions open"),
        )
        output = StringIO()
        errors = StringIO()
        with patch("agentpost.cli.upgrade", return_value=results):
            with redirect_stdout(output), redirect_stderr(errors):
                result = main(["--root", str(self.root), "upgrade"])
        self.assertEqual(result, 1)
        self.assertIn("UPGRADED\tpb\tclaude", output.getvalue())
        self.assertIn("FAILED\tapp\tcodex", output.getvalue())
        self.assertIn("restart claude", errors.getvalue())
        self.assertIn("package-only changes are already live", errors.getvalue())

    def test_upgrade_reports_when_no_binding_matches(self) -> None:
        errors = StringIO()
        with redirect_stderr(errors):
            result = main(["--root", str(self.root), "upgrade", "--cli", "codex"])
        self.assertEqual(result, 1)
        self.assertIn("no adapter bindings match", errors.getvalue())

    def test_watch_help_states_it_does_not_connect_the_mailbox(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            with self.assertRaises(SystemExit) as exited:
                main(["--root", str(self.root), "watch", "--help"])
        self.assertEqual(exited.exception.code, 0)
        # argparse wraps the description, so compare against unwrapped text.
        help_text = " ".join(output.getvalue().lower().split())
        for phrase in (
            "read-only",
            "no inbound consumer lease",
            "publishes no presence",
            "injects no native",
            "not a persistent monitor",
        ):
            self.assertIn(phrase, help_text)


if __name__ == "__main__":
    unittest.main()
