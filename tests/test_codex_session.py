from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from agentpost import AgentPostError, PostOffice, Profile  # noqa: E402
from agentpost.cli import main  # noqa: E402
from agentpost.codex_generation import (  # noqa: E402
    CODEX_HOOK_GENERATION,
    codex_hook_marker,
    codex_newer_generation_is_compatible,
)
from agentpost.codex_session import (  # noqa: E402
    CODEX_SESSION_ATTACHMENT_TTL_SECONDS,
    attach_codex_session,
    codex_session_attachment_path,
    load_codex_session_attachment,
)
from agentpost.installer import _doctor_codex, install  # noqa: E402
from agentpost.native import codex_hook  # noqa: E402
from agentpost.ownership import ConsumerLease  # noqa: E402
from agentpost.routing import identify_agent, identify_agent_source, workspace_seats  # noqa: E402


class CodexSessionAttachTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "post"
        self.project = Path(self.temp.name) / "pattern-buffer-evolution"
        self.project.mkdir()
        self.home = Path(self.temp.name) / "home"
        self.office = PostOffice(self.root)
        for name in ("pbeo", "pbeocx", "peer"):
            roots = (str(self.project),) if name != "peer" else ()
            self.office.register_profile(
                Profile(
                    name=name,
                    display_name=name.upper(),
                    cli="codex",
                    kind="project",
                    summary=f"Agent {name}",
                    projects=("pattern-buffer-evolution",)
                    if name != "peer"
                    else ("other-project",),
                    project_roots=roots,
                )
            )
        # The marker preserves pbeo as the workspace default and records
        # pbeocx as an alternate seat at the same root.
        self.office.bind_agent("pbeo", "codex", self.project)
        self.office.bind_agent("pbeocx", "codex", self.project)
        self.thread_id = "019-codex-thread"
        self._observe(self.thread_id, "0.0.4+codex.20260701000000")
        self._install_generation(CODEX_HOOK_GENERATION)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _observe(
        self,
        thread_id: str,
        generation: str,
        *,
        agent: str = "pbeo",
        event: str = "user-prompt-submit",
        observed_at: float = 100.0,
    ) -> None:
        marker = codex_hook_marker(self.office, agent, event)
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(
            json.dumps(
                {
                    "adapter": "codex-hook",
                    "generation": generation,
                    "event": event,
                    "observed_at": observed_at,
                    "session_id": thread_id,
                    "cwd": str(self.project),
                }
            ),
            encoding="utf-8",
        )

    def _install_generation(self, generation: str) -> Path:
        config = self.home / ".codex" / "config.toml"
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(
            '[plugins."agentpost@agentpost-local"]\nenabled = true\n',
            encoding="utf-8",
        )
        manifest = (
            self.home
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
        return manifest

    def _attach(self, thread_id: str | None = None, **kwargs):
        current_time = kwargs.pop("now", time.time())
        return attach_codex_session(
            self.office,
            "pbeocx",
            thread_id or self.thread_id,
            self.project,
            allowed_agents=workspace_seats(self.office, self.project),
            home=self.home,
            now=current_time,
            **kwargs,
        )

    def test_observed_older_hook_attaches_without_mutating_newer_plugin(self) -> None:
        config = self.home / ".codex" / "config.toml"
        before = {
            path: path.read_bytes()
            for path in (config, *self.home.glob(".codex/plugins/cache/**/plugin.json"))
        }

        result = self._attach()

        self.assertEqual(result.state, "attached")
        self.assertEqual(result.delivery, "boundary-only")
        self.assertEqual(
            result.attachment.observed_generation,
            "0.0.4+codex.20260701000000",
        )
        self.assertEqual(
            result.installed_generation,
            CODEX_HOOK_GENERATION,
        )
        self.assertEqual(
            before,
            {path: path.read_bytes() for path in before},
        )
        path = codex_session_attachment_path(self.office, self.thread_id)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)
        self.assertNotIn(self.thread_id, path.name)

    def test_session_attachment_outranks_workspace_default_but_not_explicit_identity(
        self,
    ) -> None:
        default, source = identify_agent_source(
            self.office,
            self.project,
            cli="codex",
            session_id="unattached-thread",
        )
        self.assertEqual((default.name, source), ("pbeo", "workspace default"))
        self._attach()

        attached, source = identify_agent_source(
            self.office,
            self.project,
            cli="codex",
            session_id=self.thread_id,
        )
        self.assertEqual(
            (attached.name, source),
            ("pbeocx", "Codex session attachment"),
        )
        explicit = identify_agent(
            self.office,
            self.project,
            cli="codex",
            agent="pbeo",
            session_id=self.thread_id,
        )
        self.assertEqual(explicit.name, "pbeo")

    def test_hook_uses_attachment_at_the_next_boundary_without_claiming(self) -> None:
        self._attach()
        sent = self.office.send("pbeo", "pbeocx", "Attached-session work")
        event = StringIO(
            json.dumps({"cwd": str(self.project), "session_id": self.thread_id})
        )
        output = StringIO()
        environment = {
            "AGENTPOST_ROOT": str(self.root),
            "CODEX_THREAD_ID": self.thread_id,
        }
        with patch.dict(os.environ, environment, clear=True):
            with patch("sys.stdin", event), redirect_stdout(output):
                self.assertEqual(
                    codex_hook(
                        "user-prompt-submit",
                        "0.0.4+codex.20260701000000",
                    ),
                    0,
                )

        instruction = json.loads(output.getvalue())["hookSpecificOutput"][
            "additionalContext"
        ]
        self.assertIn("AgentPost startup notice", instruction)
        self.assertIn("mailbox pbeocx", instruction)
        self.assertIn(sent.message_id, instruction)
        self.assertIn("ask whether to inspect", instruction)
        self.assertNotIn("agentpost read", instruction)
        self.assertEqual(len(self.office.list_messages("pbeocx", "unread")), 1)
        observed = json.loads(
            codex_hook_marker(
                self.office,
                "pbeocx",
                "user-prompt-submit",
            ).read_text()
        )
        self.assertEqual(observed["session_id"], self.thread_id)

    def test_cli_calls_inside_attached_thread_use_the_attached_sender(self) -> None:
        self._attach()
        output = StringIO()
        errors = StringIO()
        environment = {
            "CODEX_THREAD_ID": self.thread_id,
            "AGENTPOST_ROOT": str(self.root),
        }
        with patch.dict(os.environ, environment, clear=True):
            with redirect_stdout(output), redirect_stderr(errors):
                result = main(
                    [
                        "--root",
                        str(self.root),
                        "message",
                        "other-project.peer",
                        "Sent from the attached seat.",
                    ]
                )
        self.assertEqual(result, 0)
        self.assertIn("FROM\tpbeocx", output.getvalue())
        self.assertEqual(
            self.office.list_messages("peer")[0].letter.from_agent,
            "pbeocx",
        )

    def test_attach_is_idempotent_and_can_rebind_explicitly(self) -> None:
        first = self._attach()
        path = codex_session_attachment_path(self.office, self.thread_id)
        contents = path.read_bytes()
        for event in ("session-start", "user-prompt-submit", "stop"):
            codex_hook_marker(self.office, "pbeo", event).unlink(missing_ok=True)
        second = self._attach()
        self.assertEqual(second.state, "current")
        self.assertEqual(path.read_bytes(), contents)
        self.assertEqual(second.attachment, first.attachment)

        rebound = attach_codex_session(
            self.office,
            "pbeo",
            self.thread_id,
            self.project,
            allowed_agents=workspace_seats(self.office, self.project),
            home=self.home,
            now=time.time(),
        )
        self.assertEqual(rebound.state, "rebound")
        self.assertEqual(
            load_codex_session_attachment(
                self.office,
                self.thread_id,
                now=time.time(),
            ).agent,
            "pbeo",
        )

    def test_attach_rejects_unreachable_mailbox_and_explicit_environment_conflict(
        self,
    ) -> None:
        with self.assertRaisesRegex(AgentPostError, "not reachable"):
            attach_codex_session(
                self.office,
                "peer",
                self.thread_id,
                self.project,
                allowed_agents=workspace_seats(self.office, self.project),
                home=self.home,
            )
        with self.assertRaisesRegex(AgentPostError, "AGENTPOST_AGENT=pbeo outranks"):
            self._attach(explicit_agent="pbeo")
        self.assertFalse(
            codex_session_attachment_path(self.office, self.thread_id).exists()
        )

    def test_attach_fails_closed_for_unknown_hook_abi(self) -> None:
        thread_id = "old-hook-thread"
        self._observe(thread_id, "0.0.2+codex.20260601000000")
        with self.assertRaisesRegex(AgentPostError, "incompatible attach ABI"):
            self._attach(thread_id)
        self.assertFalse(
            codex_session_attachment_path(self.office, thread_id).exists()
        )

    def test_stale_attachment_expires_and_falls_back_to_workspace_default(self) -> None:
        self._attach()
        attachment = load_codex_session_attachment(self.office, self.thread_id)
        self.assertIsNone(
            load_codex_session_attachment(
                self.office,
                self.thread_id,
                now=attachment.attached_at + CODEX_SESSION_ATTACHMENT_TTL_SECONDS,
            )
        )
        self.assertFalse(
            codex_session_attachment_path(self.office, self.thread_id).exists()
        )
        profile = identify_agent(
            self.office,
            self.project,
            cli="codex",
            session_id=self.thread_id,
        )
        self.assertEqual(profile.name, "pbeo")

    def test_attach_refuses_a_mailbox_consumer_conflict(self) -> None:
        owner = ConsumerLease(self.office, "pbeocx", "claude")
        owner.require()
        try:
            with self.assertRaisesRegex(
                AgentPostError,
                "already has an inbound consumer: claude",
            ):
                self._attach()
        finally:
            owner.release()
        self.assertFalse(
            codex_session_attachment_path(self.office, self.thread_id).exists()
        )

    def test_managed_resume_remains_live_and_can_record_the_same_attachment(
        self,
    ) -> None:
        owner = ConsumerLease(self.office, "pbeocx", "codex")
        owner.require()
        marker = (
            self.root
            / "agents"
            / "pbeocx"
            / "adapter"
            / "codex-bridge.active"
        )
        marker.write_text(
            json.dumps({"instance_id": owner.instance_id}),
            encoding="utf-8",
        )
        try:
            result = self._attach(
                explicit_agent="pbeocx",
                bridge_active=True,
            )
        finally:
            owner.release()
        self.assertEqual(result.delivery, "live-bridge")
        self.assertEqual(result.attachment.agent, "pbeocx")

    def test_insecure_attachment_permissions_fail_closed(self) -> None:
        self._attach()
        path = codex_session_attachment_path(self.office, self.thread_id)
        path.chmod(0o644)
        with self.assertRaisesRegex(AgentPostError, "insecure"):
            load_codex_session_attachment(self.office, self.thread_id)

    def test_preexisting_invalid_attachment_provenance_fails_closed(self) -> None:
        self._attach()
        path = codex_session_attachment_path(self.office, self.thread_id)
        valid = json.loads(path.read_text(encoding="utf-8"))
        unrelated = Path(self.temp.name) / "unrelated-project"
        unrelated.mkdir()
        cases = (
            (
                "event",
                {"observed_event": "not-a-hook"},
                "invalid Codex session attachment event",
            ),
            (
                "generation",
                {"observed_generation": "0.0.2+codex.20260601000000"},
                "incompatible attach ABI",
            ),
            (
                "non-finite",
                {"expires_at": float("nan")},
                "non-finite Codex session attachment timestamp",
            ),
            (
                "ttl",
                {"expires_at": valid["expires_at"] + 1},
                "incoherent Codex session attachment timestamps",
            ),
            (
                "unreachable",
                {"project": str(unrelated)},
                "no longer reachable",
            ),
        )
        for label, change, expected in cases:
            with self.subTest(label=label):
                payload = {**valid, **change}
                path.write_text(json.dumps(payload), encoding="utf-8")
                path.chmod(0o600)
                with self.assertRaisesRegex(AgentPostError, expected):
                    load_codex_session_attachment(self.office, self.thread_id)
                with self.assertRaisesRegex(AgentPostError, expected):
                    identify_agent_source(
                        self.office,
                        self.project,
                        cli="codex",
                        session_id=self.thread_id,
                    )

    def test_permissive_attachment_directory_fails_closed(self) -> None:
        self._attach()
        path = codex_session_attachment_path(self.office, self.thread_id)
        path.parent.chmod(0o755)
        try:
            with self.assertRaisesRegex(
                AgentPostError,
                "insecure AgentPost runtime directory",
            ):
                load_codex_session_attachment(self.office, self.thread_id)
            with self.assertRaisesRegex(
                AgentPostError,
                "insecure AgentPost runtime directory",
            ):
                identify_agent_source(
                    self.office,
                    self.project,
                    cli="codex",
                    session_id=self.thread_id,
                )
        finally:
            path.parent.chmod(0o700)

    def test_attach_cli_reports_boundary_capability_without_installing(self) -> None:
        output = StringIO()
        errors = StringIO()
        environment = {
            "CODEX_THREAD_ID": self.thread_id,
            "AGENTPOST_ROOT": str(self.root),
        }
        with patch.dict(os.environ, environment, clear=True):
            with patch("agentpost.codex_session.Path.home", return_value=self.home):
                with patch("agentpost.cli.install") as install:
                    with redirect_stdout(output), redirect_stderr(errors):
                        result = main(
                            [
                                "--root",
                                str(self.root),
                                "attach",
                                "pbeocx",
                                "--project",
                                str(self.project),
                            ]
                        )
        self.assertEqual(result, 0, errors.getvalue())
        install.assert_not_called()
        self.assertIn("ATTACHED\tpbeocx\tcodex-session", output.getvalue())
        self.assertIn("DELIVERY\tboundary-only", output.getvalue())
        self.assertIn("PRESENCE\tboundary-only", output.getvalue())
        self.assertIn("agentpost codex --agent pbeocx resume", output.getvalue())

    def test_attach_cli_requires_a_live_codex_thread(self) -> None:
        errors = StringIO()
        with patch.dict(os.environ, {}, clear=True):
            with redirect_stdout(StringIO()), redirect_stderr(errors):
                result = main(
                    [
                        "--root",
                        str(self.root),
                        "attach",
                        "pbeocx",
                        "--project",
                        str(self.project),
                    ]
                )
        self.assertEqual(result, 1)
        self.assertIn("requires a live Codex thread", errors.getvalue())

    def test_doctor_reports_exact_attachment_separately_from_stale_aggregate(
        self,
    ) -> None:
        self._observe(
            self.thread_id,
            CODEX_HOOK_GENERATION,
            observed_at=200.0,
        )
        self._attach()
        for event in ("session-start", "user-prompt-submit", "stop"):
            self._observe(
                f"historical-{event}",
                "0.0.4+codex.20260701000000",
                agent="pbeocx",
                event=event,
                observed_at=100.0,
            )
        environment = {"CODEX_THREAD_ID": self.thread_id}
        with patch.dict(os.environ, environment, clear=True):
            with patch("agentpost.installer.Path.home", return_value=self.home):
                with patch("agentpost.installer._list_codex_hooks", return_value=[]):
                    with patch(
                        "agentpost.installer._trusted_agentpost_hooks",
                        return_value=({"sessionStart", "userPromptSubmit", "stop"}, ()),
                    ):
                        with patch(
                            "agentpost.installer.shutil.which",
                            return_value="/usr/bin/node",
                        ):
                            checks = {
                                check.name: check
                                for check in _doctor_codex(
                                    self.office,
                                    "pbeocx",
                                    self.project,
                                )
                            }

        attached = checks["codex-session-attachment"]
        self.assertTrue(attached.ok)
        self.assertIn("boundary-only", attached.detail)
        self.assertIn("thread ", attached.detail)
        self.assertIn(f"observed {CODEX_HOOK_GENERATION}", attached.detail)
        self.assertIn("reported separately", attached.detail)
        aggregate = checks["codex-generation"]
        self.assertFalse(aggregate.ok)
        self.assertIn("stale", aggregate.detail)

    def test_join_from_older_runtime_preserves_a_compatible_newer_plugin(
        self,
    ) -> None:
        manifest = next(
            self.home.glob(".codex/plugins/cache/**/.codex-plugin/plugin.json")
        )
        before = manifest.read_bytes()
        environment = {"CODEX_THREAD_ID": self.thread_id}
        with patch.dict(os.environ, environment, clear=True):
            with patch("agentpost.installer.Path.home", return_value=self.home):
                with patch(
                    "agentpost.installer.CODEX_HOOK_GENERATION",
                    "0.0.4+codex.20260701000000",
                ):
                    with patch(
                        "agentpost.installer._integration_source",
                        return_value=self.project,
                    ):
                        with patch("agentpost.installer._run") as run:
                            with redirect_stdout(StringIO()):
                                install(
                                    self.office,
                                    "codex",
                                    "pbeocx",
                                    self.project,
                                )

        commands = [call.args[0] for call in run.call_args_list]
        self.assertNotIn(
            ["codex", "plugin", "remove", "agentpost@agentpost-local"],
            commands,
        )
        self.assertNotIn(
            ["codex", "plugin", "add", "agentpost@agentpost-local"],
            commands,
        )
        self.assertEqual(manifest.read_bytes(), before)

    def test_newer_build_timestamp_is_also_preserved(self) -> None:
        self.assertTrue(
            codex_newer_generation_is_compatible(
                "0.0.5+codex.20260713000000",
                "0.0.5+codex.20260712082137",
            )
        )
        self.assertFalse(
            codex_newer_generation_is_compatible(
                "0.1.0+codex.20260713000000",
                "0.0.5+codex.20260712082137",
            )
        )


if __name__ == "__main__":
    unittest.main()
