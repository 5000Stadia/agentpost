from __future__ import annotations

import hashlib
import json
import math
import os
import stat
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from .codex_generation import (
    CODEX_HOOK_EVENTS,
    CODEX_STABLE_DISPATCH_MIN_RELEASE,
    _installed_codex_generation,
    codex_generation_release,
    codex_hook_marker,
)
from .core import (
    PRIVATE_FILE_MODE,
    AgentPostError,
    PostOffice,
    _open_private_runtime_subdirectory,
    _read_private_file_at,
)
from .ownership import ConsumerLease


CODEX_SESSION_ATTACHMENT_SCHEMA = 1
CODEX_SESSION_ATTACHMENT_TTL_SECONDS = 30 * 24 * 60 * 60
_MAX_ATTACHMENT_BYTES = 16 * 1024


@dataclass(frozen=True)
class CodexSessionAttachment:
    agent: str
    session_digest: str
    project: str
    attached_at: float
    expires_at: float
    observed_event: str
    observed_generation: str


@dataclass(frozen=True)
class CodexAttachResult:
    attachment: CodexSessionAttachment
    state: str
    delivery: str
    installed_generation: str | None
    installed_problem: str


@dataclass(frozen=True)
class _CodexSessionObservation:
    agent: str
    event: str
    generation: str
    observed_at: float
    cwd: str


def codex_session_attachment_path(
    office: PostOffice,
    session_id: str,
) -> Path:
    digest = _session_digest(session_id)
    return office.root / "runtime" / "codex-sessions" / f"{digest}.json"


def load_codex_session_attachment(
    office: PostOffice,
    session_id: str,
    *,
    now: float | None = None,
) -> CodexSessionAttachment | None:
    path = codex_session_attachment_path(office, session_id)
    try:
        payload = _read_private_json(office, path)
    except FileNotFoundError:
        return None
    try:
        attachment = CodexSessionAttachment(
            agent=str(payload["agent"]),
            session_digest=str(payload["session_digest"]),
            project=str(payload["project"]),
            attached_at=float(payload["attached_at"]),
            expires_at=float(payload["expires_at"]),
            observed_event=str(payload["observed_event"]),
            observed_generation=str(payload["observed_generation"]),
        )
        schema = int(payload["schema"])
    except (KeyError, TypeError, ValueError) as exc:
        raise AgentPostError(
            f"invalid Codex session attachment at {path}: {exc}"
        ) from exc
    if schema != CODEX_SESSION_ATTACHMENT_SCHEMA:
        raise AgentPostError(
            f"unsupported Codex session attachment schema {schema} at {path}"
        )
    if attachment.session_digest != _session_digest(session_id):
        raise AgentPostError(f"Codex session attachment key mismatch at {path}")
    current_time = time.time() if now is None else now
    if not all(
        math.isfinite(value)
        for value in (
            attachment.attached_at,
            attachment.expires_at,
            current_time,
        )
    ):
        raise AgentPostError(
            f"non-finite Codex session attachment timestamp at {path}"
        )
    if (
        attachment.attached_at < 0
        or attachment.expires_at <= attachment.attached_at
        or not math.isclose(
            attachment.expires_at - attachment.attached_at,
            CODEX_SESSION_ATTACHMENT_TTL_SECONDS,
            rel_tol=0,
            abs_tol=1e-6,
        )
    ):
        raise AgentPostError(
            f"incoherent Codex session attachment timestamps at {path}"
        )
    if attachment.observed_event not in CODEX_HOOK_EVENTS:
        raise AgentPostError(
            f"invalid Codex session attachment event "
            f"{attachment.observed_event!r} at {path}"
        )
    _require_compatible_generation(attachment.observed_generation)
    if attachment.expires_at <= current_time:
        _unlink_attachment(office, path)
        return None
    profile = office.load_profile(attachment.agent)
    mailbox = office.root / "agents" / profile.name / "unread"
    try:
        mailbox_details = mailbox.lstat()
    except OSError as exc:
        raise AgentPostError(
            f"Codex session attachment mailbox is not initialized: "
            f"{profile.name}"
        ) from exc
    if not stat.S_ISDIR(mailbox_details.st_mode):
        raise AgentPostError(
            f"Codex session attachment mailbox is not initialized: "
            f"{profile.name}"
        )
    project = Path(attachment.project)
    if (
        not project.is_absolute()
        or str(project.expanduser().resolve()) != attachment.project
    ):
        raise AgentPostError(
            f"invalid Codex session attachment project at {path}"
        )
    from .routing import workspace_seats

    if profile.name not in workspace_seats(office, project):
        raise AgentPostError(
            f"Codex session attachment mailbox {profile.name} is no longer "
            f"reachable from {project}"
        )
    return attachment


def attach_codex_session(
    office: PostOffice,
    agent: str,
    session_id: str,
    project: Path,
    *,
    allowed_agents: tuple[str, ...],
    explicit_agent: str | None = None,
    bridge_active: bool = False,
    now: float | None = None,
    home: Path | None = None,
) -> CodexAttachResult:
    if not session_id:
        raise AgentPostError(
            "`agentpost attach` requires a live Codex thread with CODEX_THREAD_ID"
        )
    profile = office.load_profile(agent)
    project = project.expanduser().resolve()
    if profile.name not in allowed_agents:
        choices = ", ".join(allowed_agents) or "none"
        raise AgentPostError(
            f"mailbox {profile.name} is not reachable from {project}; "
            f"workspace seats: {choices}"
        )
    mailbox = office.root / "agents" / profile.name / "unread"
    if not mailbox.is_dir():
        raise AgentPostError(f"mailbox {profile.name} is not initialized")
    if explicit_agent is not None and explicit_agent != profile.name:
        raise AgentPostError(
            f"AGENTPOST_AGENT={explicit_agent} outranks a session attachment; "
            f"restart with that variable unset or attach {explicit_agent}"
        )

    current_time = time.time() if now is None else now
    existing = load_codex_session_attachment(office, session_id, now=current_time)
    if existing is None:
        observation = _compatible_session_observation(office, session_id)
    else:
        _require_compatible_generation(existing.observed_generation)
        observation = _CodexSessionObservation(
            agent=existing.agent,
            event=existing.observed_event,
            generation=existing.observed_generation,
            observed_at=existing.attached_at,
            cwd=existing.project,
        )
    probe = ConsumerLease(office, profile.name, "codex-attach-probe", cwd=project)
    owner = probe.current_owner()
    managed = _managed_bridge_matches(
        office,
        profile.name,
        explicit_agent=explicit_agent,
        bridge_active=bridge_active,
        owner=owner,
    )
    if not managed:
        if not probe.acquire():
            owner = probe.current_owner()
            detail = (
                f"{owner.get('adapter', 'unknown')} pid {owner.get('pid', '?')} "
                f"instance {owner.get('instance_id', '?')}"
                if owner
                else "another live instance"
            )
            raise AgentPostError(
                f"mailbox {profile.name} already has an inbound consumer: {detail}; "
                "attach did not change the session identity"
            )
        probe.release()

    state = "attached"
    if existing is not None and existing.agent == profile.name:
        attachment = existing
        state = "current"
    else:
        state = "rebound" if existing is not None else "attached"
        attachment = CodexSessionAttachment(
            agent=profile.name,
            session_digest=_session_digest(session_id),
            project=str(project),
            attached_at=current_time,
            expires_at=current_time + CODEX_SESSION_ATTACHMENT_TTL_SECONDS,
            observed_event=observation.event,
            observed_generation=observation.generation,
        )
        _write_attachment(
            office,
            codex_session_attachment_path(office, session_id),
            attachment,
        )

    installed, problem = _installed_codex_generation(home or Path.home())
    return CodexAttachResult(
        attachment=attachment,
        state=state,
        delivery="live-bridge" if managed else "boundary-only",
        installed_generation=installed,
        installed_problem=problem,
    )


def _compatible_session_observation(
    office: PostOffice,
    session_id: str,
) -> _CodexSessionObservation:
    observations = []
    for profile in office.list_profiles():
        for event in CODEX_HOOK_EVENTS:
            marker = codex_hook_marker(office, profile.name, event)
            try:
                payload = json.loads(marker.read_text(encoding="utf-8"))
                marker_session = str(payload["session_id"])
                generation = str(payload["generation"])
                observed_at = float(payload["observed_at"])
            except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
                continue
            if marker_session != session_id:
                continue
            if not math.isfinite(observed_at):
                continue
            observations.append(
                _CodexSessionObservation(
                    agent=profile.name,
                    event=event,
                    generation=generation,
                    observed_at=observed_at,
                    cwd=str(payload.get("cwd", "")),
                )
            )
    if not observations:
        raise AgentPostError(
            "the current CODEX_THREAD_ID has not been observed by an AgentPost "
            "Codex hook; attach cannot verify a compatible lifecycle boundary. "
            "Submit a prompt after trusting the stable AgentPost hooks, or use "
            "`agentpost codex --agent MAILBOX resume THREAD_ID`"
        )
    observation = max(observations, key=lambda item: item.observed_at)
    _require_compatible_generation(observation.generation)
    return observation


def _require_compatible_generation(generation: str) -> None:
    release = codex_generation_release(generation)
    if release is None or release < CODEX_STABLE_DISPATCH_MIN_RELEASE:
        expected = ".".join(
            str(item) for item in CODEX_STABLE_DISPATCH_MIN_RELEASE
        )
        raise AgentPostError(
            f"Codex hook generation {generation!r} has unknown or "
            f"incompatible attach ABI; generation {expected} or newer is required. "
            "No session or plugin state was changed"
        )


def _session_digest(session_id: str) -> str:
    if not session_id or len(session_id) > 512 or "\x00" in session_id:
        raise AgentPostError("invalid CODEX_THREAD_ID")
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()


def _codex_bridge_marker(office: PostOffice, agent: str) -> Path:
    return office.root / "agents" / agent / "adapter" / "codex-bridge.active"


def _managed_bridge_matches(
    office: PostOffice,
    agent: str,
    *,
    explicit_agent: str | None,
    bridge_active: bool,
    owner: dict,
) -> bool:
    if not bridge_active or explicit_agent != agent or owner.get("adapter") != "codex":
        return False
    try:
        marker = json.loads(
            _codex_bridge_marker(office, agent).read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return False
    return bool(
        isinstance(marker, dict)
        and marker.get("instance_id")
        and marker.get("instance_id") == owner.get("instance_id")
    )


def _read_private_json(office: PostOffice, path: Path) -> dict:
    try:
        directory = _open_private_runtime_subdirectory(
            office.root,
            ("runtime", "codex-sessions"),
        )
    except FileNotFoundError:
        raise
    try:
        contents = _read_private_file_at(directory, path.name, path)
    finally:
        os.close(directory)
    if len(contents) > _MAX_ATTACHMENT_BYTES:
        raise AgentPostError(f"Codex session attachment is too large: {path}")
    try:
        value = json.loads(contents)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AgentPostError(f"invalid Codex session attachment at {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise AgentPostError(f"invalid Codex session attachment at {path}")
    return value


def _unlink_attachment(office: PostOffice, path: Path) -> None:
    directory = _open_private_runtime_subdirectory(
        office.root,
        ("runtime", "codex-sessions"),
    )
    try:
        try:
            os.unlink(path.name, dir_fd=directory)
        except FileNotFoundError:
            pass
        os.fsync(directory)
    finally:
        os.close(directory)


def _write_attachment(
    office: PostOffice,
    path: Path,
    attachment: CodexSessionAttachment,
) -> None:
    directory = _open_private_runtime_subdirectory(
        office.root,
        ("runtime", "codex-sessions"),
        create=True,
    )
    temporary = f".{path.name}.{uuid.uuid4().hex}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(
        temporary,
        flags,
        PRIVATE_FILE_MODE,
        dir_fd=directory,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "schema": CODEX_SESSION_ATTACHMENT_SCHEMA,
                    "agent": attachment.agent,
                    "session_digest": attachment.session_digest,
                    "project": attachment.project,
                    "attached_at": attachment.attached_at,
                    "expires_at": attachment.expires_at,
                    "observed_event": attachment.observed_event,
                    "observed_generation": attachment.observed_generation,
                },
                handle,
                sort_keys=True,
                allow_nan=False,
            )
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(
            temporary,
            path.name,
            src_dir_fd=directory,
            dst_dir_fd=directory,
        )
        os.fsync(directory)
    finally:
        try:
            os.unlink(temporary, dir_fd=directory)
        except FileNotFoundError:
            pass
        os.close(directory)
