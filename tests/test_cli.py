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

from agentpost import PostOffice, Profile  # noqa: E402
from agentpost.cli import _infer_join_agent, _join, main  # noqa: E402


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
                    "Pattern Buffer",
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
                        "Pattern Buffer",
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
                        "pb",
                        "Queued message.",
                    ]
                )
        self.assertEqual(result, 0)
        self.assertIn("recipient offline; queued for its next adapter start", errors.getvalue())
        self.assertNotIn("notifier not armed", errors.getvalue())
        self.assertNotIn("generation", errors.getvalue().lower())

    def test_optional_channel_bodies_may_follow_flags(self) -> None:
        request = self.office.send("pb", "app", "Please reply.")
        commands = (
            ["message", "pb", "--notify", "immediate", "message after flag"],
            ["question", "pb", "--subject", "Review", "question after flag"],
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

    def test_identities_and_resolve_expose_the_address_book(self) -> None:
        identities = StringIO()
        with redirect_stdout(identities):
            self.assertEqual(
                main(["--root", str(self.root), "identities"]),
                0,
            )
        self.assertIn(
            "agent\tpb\toffline\tPattern Buffer\tpattern-buffer\t",
            identities.getvalue(),
        )
        self.assertTrue(identities.getvalue().startswith("type\taddress\tattention"))

        resolved = StringIO()
        with redirect_stdout(resolved):
            self.assertEqual(
                main(["--root", str(self.root), "resolve", "Pattern Buffer"]),
                0,
            )
        self.assertEqual(resolved.getvalue(), "agent\tpb\toffline\tPattern Buffer\n")

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


if __name__ == "__main__":
    unittest.main()
