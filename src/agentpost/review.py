from __future__ import annotations

import re
import subprocess
from pathlib import Path, PurePosixPath
from typing import Iterable

from .core import AgentPostError, ReviewArtifact


FULL_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
REJECTED_STRUCTURED_TOKENS = ("$(", "${", "`", "|", ";", "&", "<", ">")


class ReviewPreflightError(AgentPostError):
    pass


def prepare_review(
    repository: str | Path,
    commit: str,
    paths: Iterable[str],
    tests: Iterable[str],
    *,
    parent: str | None = None,
) -> ReviewArtifact:
    repository_text = str(repository)
    _validate_structured_value("repository", repository_text)
    try:
        repo = Path(repository_text).expanduser().resolve(strict=True)
    except OSError as exc:
        raise ReviewPreflightError(
            f"review repository is unavailable: {repository_text}"
        ) from exc
    if not repo.is_dir():
        raise ReviewPreflightError(f"review repository is not a directory: {repo}")

    top_level = Path(_git(repo, "rev-parse", "--show-toplevel")).resolve()
    if top_level != repo:
        raise ReviewPreflightError(
            f"review repository must name the Git worktree root: {top_level}"
        )

    canonical_commit = _resolve_commit(repo, "commit", commit)
    canonical_parent = (
        _resolve_commit(repo, "parent", parent) if parent is not None else None
    )
    if canonical_parent is not None:
        ancestry = _git(
            repo, "rev-list", "--parents", "-n", "1", canonical_commit
        ).split()
        if canonical_parent not in ancestry[1:]:
            raise ReviewPreflightError(
                f"asserted parent {canonical_parent} is not a direct parent of {canonical_commit}"
            )

    canonical_paths = tuple(_canonical_tree_path("path", value) for value in paths)
    canonical_tests = tuple(_canonical_test(value) for value in tests)
    if not canonical_paths:
        raise ReviewPreflightError("review needs at least one --path assertion")
    if not canonical_tests:
        raise ReviewPreflightError("review needs at least one --test assertion")
    _require_unique("path", canonical_paths)
    _require_unique("test", canonical_tests)

    for path in canonical_paths:
        _require_tree_path(repo, canonical_commit, path, "review path")
    for test in canonical_tests:
        test_path = test.split("::", 1)[0]
        _require_tree_path(repo, canonical_commit, test_path, "test file", blob=True)

    artifact = ReviewArtifact(
        repository=str(repo),
        commit=canonical_commit,
        parent=canonical_parent,
        paths=canonical_paths,
        tests=canonical_tests,
    )
    artifact.validate()
    return artifact


def render_review_request(artifact: ReviewArtifact, request: str) -> str:
    if not request:
        raise ReviewPreflightError("review request body must not be empty")
    artifact.validate()
    parent = f"`{artifact.parent}`" if artifact.parent else "(not asserted)"
    path_lines = "\n".join(f"- `{path}`" for path in artifact.paths)
    test_lines = "\n".join(f"- `{test}`" for test in artifact.tests)
    return (
        "## AgentPost Review Artifact\n"
        f"Repository: `{artifact.repository}`\n"
        f"Commit: `{artifact.commit}`\n"
        f"Parent: {parent}\n\n"
        f"Paths:\n{path_lines}\n\n"
        f"Tests:\n{test_lines}\n\n"
        "## Review Request\n"
        f"{request}"
    )


def verify_review_artifact(artifact: ReviewArtifact) -> None:
    verified = prepare_review(
        artifact.repository,
        artifact.commit,
        artifact.paths,
        artifact.tests,
        parent=artifact.parent,
    )
    if verified != artifact:
        raise ReviewPreflightError("review artifact is not in canonical verified form")


def _resolve_commit(repo: Path, label: str, value: str) -> str:
    _validate_structured_value(label, value)
    if not FULL_SHA_RE.fullmatch(value):
        raise ReviewPreflightError(
            f"review {label} must be an explicit full 40-hex SHA"
        )
    resolved = _git(repo, "rev-parse", "--verify", f"{value}^{{commit}}")
    if not re.fullmatch(r"[0-9a-f]{40}", resolved):
        raise ReviewPreflightError(
            f"Git returned a non-canonical {label} SHA: {resolved}"
        )
    if resolved != value.lower():
        raise ReviewPreflightError(
            f"review {label} must identify a commit object directly"
        )
    return resolved


def _canonical_tree_path(label: str, value: str) -> str:
    _validate_structured_value(label, value)
    if ":" in value or "\\" in value:
        raise ReviewPreflightError(
            f"review {label} contains unsupported path syntax: {value}"
        )
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ReviewPreflightError(
            f"review {label} must be a normalized relative path: {value}"
        )
    canonical = path.as_posix()
    if canonical != value:
        raise ReviewPreflightError(f"review {label} must be normalized: {value}")
    return canonical


def _canonical_test(value: str) -> str:
    _validate_structured_value("test", value)
    path, separator, node = value.partition("::")
    if not separator or not node or not all(part for part in node.split("::")):
        raise ReviewPreflightError(
            "review --test must be file-qualified as RELATIVE_PATH::TEST_NODE"
        )
    canonical_path = _canonical_tree_path("test file", path)
    return f"{canonical_path}::{node}"


def _require_tree_path(
    repo: Path,
    commit: str,
    path: str,
    label: str,
    *,
    blob: bool = False,
) -> None:
    try:
        _git(repo, "cat-file", "-e", f"{commit}:{path}")
    except ReviewPreflightError as exc:
        raise ReviewPreflightError(
            f"{label} does not exist in {commit}: {path}"
        ) from exc
    if blob and _git(repo, "cat-file", "-t", f"{commit}:{path}") != "blob":
        raise ReviewPreflightError(f"{label} is not a file in {commit}: {path}")


def _require_unique(label: str, values: tuple[str, ...]) -> None:
    if len(set(values)) != len(values):
        raise ReviewPreflightError(f"duplicate review {label} assertion")


def _validate_structured_value(label: str, value: str) -> None:
    if not value:
        raise ReviewPreflightError(f"review {label} must not be empty")
    token = next(
        (token for token in REJECTED_STRUCTURED_TOKENS if token in value),
        None,
    )
    if token is not None:
        raise ReviewPreflightError(
            f"review {label} contains rejected structured-field syntax {token!r}"
        )
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ReviewPreflightError(f"review {label} contains a control character")


def _git(repo: Path, *arguments: str) -> str:
    try:
        result = subprocess.run(
            ("git", "-C", str(repo), *arguments),
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise ReviewPreflightError("git executable not found") from exc
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.strip() or exc.stdout.strip() or "git command failed"
        raise ReviewPreflightError(detail) from exc
    return result.stdout.strip()
