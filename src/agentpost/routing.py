from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .codex_session import load_codex_session_attachment
from .core import PostOffice, Profile, UnknownAgentError
from .presence import agent_presence


_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "is",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}
_ADDRESS_SEGMENT_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$", re.IGNORECASE)


@dataclass(frozen=True)
class AgentMatch:
    profile: Profile
    score: int
    reasons: tuple[str, ...]
    evidence: tuple[str, ...] = ()
    presence: str = "offline"


def find_agents(
    office: PostOffice,
    query: str | None = None,
    *,
    role: str | None = None,
    project: str | None = None,
    specialty: str | None = None,
    include_offline: bool = False,
) -> tuple[AgentMatch, ...]:
    selectors = tuple(
        (label, _normalize(value))
        for label, value in (
            ("role", role),
            ("project", project),
            ("specialty", specialty),
        )
        if value
    )
    query_normalized = _normalize(query or "")
    query_tokens = set(query_normalized.split())
    matches = []

    for profile in office.list_profiles():
        current_presence = agent_presence(office, profile.name)
        if not include_offline and not current_presence.active:
            continue
        score = 0
        reasons = []
        evidence = []

        if selectors:
            fields = {
                "role": profile.roles,
                "project": profile.projects,
                "specialty": profile.specialties,
            }
            rejected = False
            for label, expected in selectors:
                values = {_normalize(item) for item in fields[label]}
                if expected not in values:
                    rejected = True
                    break
                score += 100
                reasons.append(f"exact {label}: {expected}")
            if rejected:
                continue

        if query_normalized:
            if query_normalized == _normalize(profile.name):
                score += 1000
                reasons.append(f"exact agent: {profile.name}")

            exact_fields = (
                ("role", profile.roles, 180),
                ("project", profile.projects, 180),
                ("specialty", profile.specialties, 200),
                ("responsibility", profile.handles, 160),
            )
            for label, values, weight in exact_fields:
                for value in values:
                    if query_normalized == _normalize(value):
                        score += weight
                        reasons.append(f"exact {label}: {value}")

            searchable = (
                ("summary", (profile.summary,)),
                ("role", profile.roles),
                ("project", profile.projects),
                ("specialty", profile.specialties),
                ("responsibility", profile.handles),
            )
            for label, values in searchable:
                field_tokens = _tokens(values)
                overlap = sorted(query_tokens & field_tokens)
                if overlap:
                    score += len(overlap) * 10
                    reasons.append(f"{label} tokens: {', '.join(overlap)}")

            for item in profile.experience:
                item_tokens = _tokens((item.topic, item.summary, *item.projects))
                overlap = sorted(query_tokens & item_tokens)
                exact = query_normalized == _normalize(item.topic)
                if exact or overlap:
                    score += 240 if exact else len(overlap) * 15
                    if item.evidence:
                        score += 40
                        evidence.extend(item.evidence)
                    reason = f"experience: {item.topic}"
                    if item.evidence:
                        reason += " (evidence-backed)"
                    reasons.append(reason)

        if reasons or (not selectors and not query_normalized):
            matches.append(
                AgentMatch(
                    profile=profile,
                    score=score,
                    reasons=tuple(dict.fromkeys(reasons)) or ("registered agent",),
                    evidence=tuple(dict.fromkeys(evidence)),
                    presence=current_presence.state,
                )
            )

    return tuple(sorted(matches, key=lambda item: (-item.score, item.profile.name)))


def resolve_recipients(
    office: PostOffice,
    addresses: Iterable[str],
    *,
    sender: str | None = None,
    groups: dict[str, tuple[str, ...]] | None = None,
    skip_sender: bool = True,
) -> tuple[str, ...]:
    groups = groups or {}
    resolved = []
    for raw in addresses:
        for address in (item.strip() for item in raw.split(",")):
            if not address:
                continue
            if address.startswith("@role:"):
                found = find_agents(office, role=address[6:])
                resolved.extend(item.profile.name for item in found)
            elif address.startswith("@project:"):
                found = find_agents(office, project=address[9:])
                resolved.extend(item.profile.name for item in found)
            elif address.startswith("@specialty:"):
                found = find_agents(office, specialty=address[11:])
                resolved.extend(item.profile.name for item in found)
            elif address.startswith("@"):
                group = address[1:]
                if group not in groups:
                    raise ValueError(f"unknown group: {group}")
                resolved.extend(groups[group])
            else:
                resolved.append(address)

    known = {profile.name for profile in office.list_profiles()}
    for name in resolved:
        if name not in known:
            raise UnknownAgentError(f"unknown agent: {name}")
    return tuple(
        name
        for name in dict.fromkeys(resolved)
        if not (skip_sender and sender is not None and name == sender)
    )


def resolve_channel_recipients(
    office: PostOffice,
    addresses: Iterable[str],
    *,
    sender: str | None = None,
) -> tuple[str, ...]:
    """Resolve names as a human-facing address book rather than raw mailbox keys."""
    groups = office.list_groups()
    expanded = []
    for raw in addresses:
        for address in (item.strip() for item in raw.split(",")):
            if not address:
                continue
            if address.startswith("@"):
                expanded.extend(
                    resolve_recipients(
                        office,
                        (address,),
                        sender=sender,
                        groups=groups,
                    )
                )
                continue

            group = resolve_group(office, address)
            if group is not None:
                try:
                    identity = resolve_identity(
                        office,
                        address,
                        sender=sender,
                    )
                except UnknownAgentError:
                    identity = None
                if identity is not None:
                    raise ValueError(
                        f"ambiguous AgentPost address {address!r}: "
                        f"agent {identity.name} "
                        f"or group @{group}"
                    )
                expanded.extend(groups[group])
                continue

            expanded.append(
                resolve_identity(
                    office,
                    address,
                    sender=sender,
                ).name
            )

    return resolve_recipients(
        office,
        expanded,
        sender=sender,
        groups=groups,
    )


def resolve_group(office: PostOffice, label: str) -> str | None:
    """Resolve a bare human-facing group label, rejecting normalized collisions."""
    expected = _normalize(label.removeprefix("@"))
    matches = [
        name for name in office.list_groups() if _normalize(name) == expected
    ]
    if len(matches) > 1:
        names = ", ".join(f"@{name}" for name in sorted(matches))
        raise ValueError(f"ambiguous AgentPost group {label!r}: {names}")
    return matches[0] if matches else None


IDENTITY_SOURCES = {
    2: "workspace default",
    1: "adapter binding",
    0: "declared project root",
}


def identify_agent(
    office: PostOffice,
    cwd: str | Path,
    *,
    cli: str | None = None,
    agent: str | None = None,
    session_id: str | None = None,
) -> Profile:
    return identify_agent_source(
        office,
        cwd,
        cli=cli,
        agent=agent,
        session_id=session_id,
    )[0]


def identify_agent_source(
    office: PostOffice,
    cwd: str | Path,
    *,
    cli: str | None = None,
    agent: str | None = None,
    session_id: str | None = None,
) -> tuple[Profile, str]:
    """Resolve the acting mailbox and name the rule that chose it.

    Callers that only need the mailbox use identify_agent. The rule matters on
    a mailbox miss: without it, acting as the wrong seat is indistinguishable
    from the letter being absent.
    """
    if agent is not None:
        return office.load_profile(agent), "explicit identity"

    codex_session = (
        session_id
        if session_id is not None
        else os.environ.get("CODEX_THREAD_ID")
    )
    if codex_session and cli in {None, "codex"}:
        attachment = load_codex_session_attachment(office, codex_session)
        if attachment is not None:
            return office.load_profile(attachment.agent), "Codex session attachment"

    current = Path(cwd).expanduser().resolve()
    candidates = []
    workspace = office.workspace_identity(current)
    if workspace is not None:
        candidates.append(
            (len(workspace[2].parts), 2, office.load_profile(workspace[0]))
        )
    for binding in office.list_bindings():
        if cli is not None and binding.cli != cli:
            continue
        root = Path(binding.project).expanduser().resolve()
        if current == root or root in current.parents:
            candidates.append(
                (len(root.parts), 1, office.load_profile(binding.agent))
            )

    if office.connection_mode() == "auto":
        for profile in office.list_profiles():
            for root_value in profile.project_roots:
                root = Path(root_value).expanduser().resolve()
                if current == root or root in current.parents:
                    candidates.append((len(root.parts), 0, profile))
                    break

    if not candidates and office.connection_mode() == "manual":
        raise UnknownAgentError(
            f"no explicit agent binding for project path: {current}; "
            "run `agentpost connect AGENT --cli CLI --project PATH`"
        )
    if not candidates:
        raise UnknownAgentError(f"no agent is bound to project path: {current}")
    candidates.sort(key=lambda item: (-item[0], -item[1], item[2].name))
    best_depth = candidates[0][0]
    best_priority = candidates[0][1]
    best = [
        profile
        for depth, priority, profile in candidates
        if depth == best_depth and priority == best_priority
    ]
    if len(best) > 1:
        names = ", ".join(profile.name for profile in best)
        raise ValueError(f"ambiguous agent binding for {current}: {names}")
    return best[0], IDENTITY_SOURCES[best_priority]


def workspace_seats(office: PostOffice, cwd: str | Path) -> tuple[str, ...]:
    """Mailboxes a runtime in this directory may legitimately act as.

    identify_agent collapses this set to a single default. The set itself
    matters whenever the default is not the seat a letter was addressed to:
    an alternate seat sharing the project root is reachable from here, while
    an unrelated mailbox is not.
    """
    current = Path(cwd).expanduser().resolve()
    seats: list[str] = []
    workspace = office.workspace_identity(current)
    if workspace is not None:
        seats.extend(workspace[1])
    for binding in office.list_bindings():
        root = Path(binding.project).expanduser().resolve()
        if current == root or root in current.parents:
            seats.append(binding.agent)
    if office.connection_mode() == "auto":
        for profile in office.list_profiles():
            for root_value in profile.project_roots:
                root = Path(root_value).expanduser().resolve()
                if current == root or root in current.parents:
                    seats.append(profile.name)
                    break
    return tuple(dict.fromkeys(seats))


def project_candidates(
    office: PostOffice,
    cwd: str | Path,
    *,
    cli: str | None = None,
) -> tuple[Profile, ...]:
    """Profiles whose declared roots contain cwd, restricted to the deepest root."""
    current = Path(cwd).expanduser().resolve()
    candidates = []
    workspace = office.workspace_identity(current)
    if workspace is not None:
        candidates.append(
            (len(workspace[2].parts), 1, office.load_profile(workspace[0]))
        )
    for profile in office.list_profiles():
        for root_value in profile.project_roots:
            root = Path(root_value).expanduser().resolve()
            if current == root or root in current.parents:
                candidates.append((len(root.parts), 0, profile))
                break
    if not candidates:
        return ()
    best_depth = max(depth for depth, _, _ in candidates)
    best_priority = max(
        priority for depth, priority, _ in candidates if depth == best_depth
    )
    return tuple(
        profile
        for depth, priority, profile in sorted(
            candidates, key=lambda item: item[2].name
        )
        if depth == best_depth and priority == best_priority
    )


def project_profiles(
    office: PostOffice,
    project: str,
) -> tuple[Profile, ...]:
    """Return every registered seat carrying an exact project name or alias."""
    expected = _normalize(project)
    if not expected:
        raise UnknownAgentError("project label must not be empty")
    matches = tuple(
        profile
        for profile in office.list_profiles()
        if expected in {_normalize(value) for value in profile.projects}
    )
    if not matches:
        raise UnknownAgentError(
            f"unknown AgentPost project: {project}; use `agentpost identities` "
            "to inspect registered project names"
        )
    return matches


def qualified_addresses(profile: Profile) -> tuple[str, ...]:
    """Derive stable PROJECT.SEAT references without inventing aliases."""
    projects = tuple(
        token
        for value in profile.projects
        if (token := _address_segment(value)) is not None
    )
    seat = next(
        (
            token
            for value in profile.handles
            if (token := _address_segment(value)) is not None
        ),
        profile.name,
    )
    return tuple(f"{project}.{seat}" for project in dict.fromkeys(projects))


def resolve_identity(
    office: PostOffice,
    label: str,
    *,
    project: str | None = None,
    sender: str | None = None,
) -> Profile:
    """Resolve a human-facing identity with optional fail-closed project scope.

    A qualified PROJECT.SEAT address supplies its own scope. An unqualified
    channel address with a sender is restricted to profiles sharing at least
    one registered project alias with that sender. It never falls back to a
    globally unique seat in another project.
    """
    qualified = _qualified_address(label)
    if qualified is not None:
        address_project, seat = qualified
        if project is not None and _normalize(project) != _normalize(address_project):
            raise ValueError(
                f"qualified address {label!r} conflicts with --project {project!r}"
            )
        return _resolve_identity_candidates(
            seat,
            project_profiles(office, address_project),
            context=f"project {address_project}",
            include_projects=False,
        )

    candidates: tuple[Profile, ...]
    context = "global directory"
    if project is not None:
        candidates = project_profiles(office, project)
        context = f"project {project}"
    elif sender is not None:
        sender_profile = office.load_profile(sender)
        if label == sender_profile.name:
            return sender_profile
        sender_projects = {
            _normalize(value)
            for value in sender_profile.projects
            if _normalize(value)
        }
        if not sender_projects:
            raise UnknownAgentError(
                f"sender {sender} has no registered project scope; qualify "
                f"{label!r} as PROJECT.SEAT"
            )
        candidates = tuple(
            profile
            for profile in office.list_profiles()
            if sender_projects
            & {
                _normalize(value)
                for value in profile.projects
                if _normalize(value)
            }
        )
        context = (
            f"sender {sender} projects "
            + ", ".join(sender_profile.projects)
        )
    else:
        candidates = office.list_profiles()
    try:
        return _resolve_identity_candidates(
            label,
            candidates,
            context=context,
            include_projects=True,
        )
    except UnknownAgentError as exc:
        if sender is not None:
            raise UnknownAgentError(
                f"bare AgentPost address {label!r} did not resolve within "
                f"{context}; cross-project addresses must use PROJECT.SEAT"
            ) from exc
        raise


def _resolve_identity_candidates(
    label: str,
    candidates: Iterable[Profile],
    *,
    context: str,
    include_projects: bool,
) -> Profile:
    expected = _normalize(label)
    if not expected:
        raise UnknownAgentError("identity label must not be empty")
    exact = []
    for profile in candidates:
        fields = [
            (profile.name, 400),
            (profile.display_name, 300),
            *((value, 200) for value in profile.handles),
            *((value, 150) for value in profile.roles),
        ]
        if include_projects:
            fields.extend((value, 100) for value in profile.projects)
        score = max(
            (weight for value, weight in fields if _normalize(value) == expected),
            default=0,
        )
        if score:
            exact.append((score, profile))
    if exact:
        best_score = max(score for score, _ in exact)
        best = sorted(
            (profile for score, profile in exact if score == best_score),
            key=lambda profile: profile.name,
        )
        if len(best) == 1:
            return best[0]
        names = ", ".join(profile.name for profile in best)
        raise ValueError(
            f"ambiguous AgentPost identity {label!r} in {context}: {names}; "
            "use PROJECT.SEAT or a canonical mailbox key"
        )

    raise UnknownAgentError(
        f"unknown AgentPost identity in {context}: {label}; use "
        "`agentpost identities --project PROJECT` or `agentpost agents-find` "
        "for responsibility discovery"
    )


def _qualified_address(label: str) -> tuple[str, str] | None:
    value = label.strip()
    if "." not in value:
        return None
    if value.count(".") != 1:
        raise ValueError(
            f"invalid qualified AgentPost address {label!r}; use exactly PROJECT.SEAT"
        )
    project, seat = (part.strip() for part in value.split(".", 1))
    if (
        _ADDRESS_SEGMENT_RE.fullmatch(project) is None
        or _ADDRESS_SEGMENT_RE.fullmatch(seat) is None
    ):
        raise ValueError(
            f"invalid qualified AgentPost address {label!r}; PROJECT and SEAT "
            "must use letters, digits, hyphens, or underscores"
        )
    return project, seat


def _address_segment(value: str) -> str | None:
    candidate = value.strip().lower()
    return (
        candidate
        if _ADDRESS_SEGMENT_RE.fullmatch(candidate) is not None
        else None
    )


def _normalize(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.lower()))


def _tokens(values: Iterable[str]) -> set[str]:
    tokens = set()
    for value in values:
        tokens.update(
            token for token in _normalize(value).split() if token not in _STOPWORDS
        )
    return tokens
