from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from agentpost import AgentChannel, PostOffice, Profile  # noqa: E402
from agentpost.cli import main  # noqa: E402


class ReviewCommandTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.root = self.base / "post"
        self.repo = self.base / "repository"
        self.repo.mkdir()
        self.office = PostOffice(self.root)
        self.office.register_profile(
            Profile(
                name="app",
                display_name="Application",
                cli="python",
                kind="project",
                summary="Application owner",
                projects=("application",),
            )
        )
        self.office.register_profile(
            Profile(
                name="reviewer",
                display_name="Reviewer",
                cli="claude",
                kind="role",
                summary="Implementation reviewer",
                roles=("code review",),
            )
        )
        self._git("init", "-b", "main")
        self._git("config", "user.email", "tests@agentpost.local")
        self._git("config", "user.name", "AgentPost Tests")
        self._write("src/module.py", "VALUE = 1\n")
        self._write("docs/spec.md", "# Specification\n")
        self._write("tests/test_module.py", "def test_value(): pass\n")
        self._write("tests/test_other.py", "def test_other(): pass\n")
        self._git("add", ".")
        self._git("commit", "-m", "base")
        self.base_commit = self._git("rev-parse", "HEAD")

        self._write("src/module.py", "VALUE = 2\n")
        self._git("commit", "-am", "main change")
        self.main_parent = self._git("rev-parse", "HEAD")

        self._git("checkout", "-b", "feature", self.base_commit)
        self._write("docs/spec.md", "# Specification\n\nFeature.\n")
        self._git("commit", "-am", "feature change")
        self._git("checkout", "main")
        self._git("merge", "--no-ff", "feature", "-m", "merge feature")
        self.merge_commit = self._git("rev-parse", "HEAD")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_golden_envelope_serializes_verified_artifact_and_immediate_default(self) -> None:
        output = StringIO()
        result = self._run_review(
            "Inspect behavior and regression coverage.",
            "--parent",
            self.main_parent,
            "--path",
            "src/module.py",
            "--path",
            "docs/spec.md",
            "--test",
            "tests/test_module.py::test_value",
            "--test",
            "tests/test_other.py::TestOther::test_other",
            output=output,
        )

        self.assertEqual(result, 0)
        expected_body = (
            "## AgentPost Review Artifact\n"
            f"Repository: `{self.repo}`\n"
            f"Commit: `{self.merge_commit}`\n"
            f"Parent: `{self.main_parent}`\n\n"
            "Paths:\n"
            "- `src/module.py`\n"
            "- `docs/spec.md`\n\n"
            "Tests:\n"
            "- `tests/test_module.py::test_value`\n"
            "- `tests/test_other.py::TestOther::test_other`\n\n"
            "## Review Request\n"
            "Inspect behavior and regression coverage."
        )
        self.assertIn(
            f"REVIEW-ENVELOPE-BEGIN\n{expected_body}\nREVIEW-ENVELOPE-END\n",
            output.getvalue(),
        )
        record = self.office.list_messages("reviewer")[0]
        self.assertEqual(record.letter.body, expected_body)
        self.assertEqual(record.letter.kind, "question")
        self.assertEqual(record.letter.notify, "immediate")
        self.assertEqual(record.letter.review.repository, str(self.repo))
        self.assertEqual(record.letter.review.commit, self.merge_commit)
        self.assertEqual(record.letter.review.parent, self.main_parent)
        self.assertEqual(record.letter.review.paths, ("src/module.py", "docs/spec.md"))
        self.assertEqual(
            record.letter.review.tests,
            (
                "tests/test_module.py::test_value",
                "tests/test_other.py::TestOther::test_other",
            ),
        )

    def test_non_worktree_fails_without_delivery(self) -> None:
        other = self.base / "not-a-repository"
        other.mkdir()
        result = self._run_review("Review.", "--repo-override", str(other))
        self.assertEqual(result, 1)
        self._assert_no_delivery()

    def test_python_channel_uses_the_same_verified_review_contract(self) -> None:
        result = AgentChannel("app", office=self.office).review(
            "reviewer",
            "Review through Python.",
            repository=self.repo,
            commit=self.merge_commit,
            parent=self.main_parent,
            paths=("src/module.py",),
            tests=("tests/test_module.py::test_value",),
        )
        letter = self.office.read("reviewer", result.message_id).letter
        self.assertEqual(letter.review.commit, self.merge_commit)
        self.assertEqual(letter.notify, "immediate")

    def test_unresolvable_commit_fails_without_delivery(self) -> None:
        result = self._run_review("Review.", "--commit-override", "0" * 40)
        self.assertEqual(result, 1)
        self._assert_no_delivery()

    def test_non_direct_merge_parent_fails_without_delivery(self) -> None:
        result = self._run_review(
            "Review.",
            "--parent",
            self.base_commit,
        )
        self.assertEqual(result, 1)
        self._assert_no_delivery()

    def test_absent_path_fails_without_delivery(self) -> None:
        result = self._run_review(
            "Review.",
            "--path",
            "src/missing.py",
        )
        self.assertEqual(result, 1)
        self._assert_no_delivery()

    def test_unqualified_test_fails_without_delivery(self) -> None:
        result = self._run_review(
            "Review.",
            "--test",
            "test_value",
        )
        self.assertEqual(result, 1)
        self._assert_no_delivery()

    def test_rejected_structured_syntax_fails_without_delivery(self) -> None:
        rejected = (
            "$(command)",
            "${value}",
            "`command`",
            "a|b",
            "a;b",
            "a&b",
            "<path>",
            "a>b",
        )
        for value in rejected:
            with self.subTest(value=value):
                result = self._run_review(
                    "Review.",
                    "--path",
                    value,
                )
                self.assertEqual(result, 1)
                self._assert_no_delivery()

    def _run_review(
        self,
        body: str,
        *overrides: str,
        output: StringIO | None = None,
    ) -> int:
        values = list(overrides)
        repo = self.repo
        commit = self.merge_commit
        if "--repo-override" in values:
            index = values.index("--repo-override")
            repo = Path(values[index + 1])
            del values[index : index + 2]
        if "--commit-override" in values:
            index = values.index("--commit-override")
            commit = values[index + 1]
            del values[index : index + 2]
        arguments = [
            "--root",
            str(self.root),
            "review",
            "reviewer",
            body,
            "--repo",
            str(repo),
            "--commit",
            commit,
        ]
        if "--path" not in values:
            arguments.extend(("--path", "src/module.py"))
        if "--test" not in values:
            arguments.extend(("--test", "tests/test_module.py::test_value"))
        arguments.extend(values)
        with patch.dict(os.environ, {"AGENTPOST_AGENT": "app"}, clear=False):
            with redirect_stdout(output or StringIO()), redirect_stderr(StringIO()):
                return main(arguments)

    def _assert_no_delivery(self) -> None:
        self.assertEqual(self.office.list_messages("reviewer", "unread"), ())
        self.assertEqual(self.office.list_messages("app", "sent"), ())

    def _write(self, relative: str, content: str) -> None:
        path = self.repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="ascii")

    def _git(self, *arguments: str) -> str:
        result = subprocess.run(
            ("git", "-C", str(self.repo), *arguments),
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()


if __name__ == "__main__":
    unittest.main()
