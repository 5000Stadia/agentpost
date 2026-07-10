from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .core import PostOffice, Profile, UnknownAgentError
from .presence import agent_presence


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
                    identity = resolve_identity(office, address)
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

            expanded.append(resolve_identity(office, address).name)

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


def identify_agent(
    office: PostOffice,
    cwd: str | Path,
    *,
    cli: str | None = None,
    agent: str | None = None,
) -> Profile:
    if agent is not None:
        profile = office.load_profile(agent)
        if cli is not None and profile.cli != cli:
            raise ValueError(
                f"mailbox {agent} is registered for {profile.cli}, not {cli}"
            )
        return profile

    current = Path(cwd).expanduser().resolve()
    candidates = []
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
            if cli is not None and profile.cli != cli:
                continue
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
    return best[0]


def project_candidates(
    office: PostOffice,
    cwd: str | Path,
    *,
    cli: str | None = None,
) -> tuple[Profile, ...]:
    """Profiles whose declared roots contain cwd, restricted to the deepest root."""
    current = Path(cwd).expanduser().resolve()
    candidates = []
    for profile in office.list_profiles():
        if cli is not None and profile.cli != cli:
            continue
        for root_value in profile.project_roots:
            root = Path(root_value).expanduser().resolve()
            if current == root or root in current.parents:
                candidates.append((len(root.parts), profile))
                break
    if not candidates:
        return ()
    best_depth = max(depth for depth, _ in candidates)
    return tuple(
        profile
        for depth, profile in sorted(candidates, key=lambda item: item[1].name)
        if depth == best_depth
    )


def resolve_identity(office: PostOffice, label: str) -> Profile:
    """Resolve a human-facing AgentPost identity, including offline profiles."""
    expected = _normalize(label)
    if not expected:
        raise UnknownAgentError("identity label must not be empty")
    exact = []
    for profile in office.list_profiles():
        fields = (
            (profile.name, 400),
            (profile.display_name, 300),
            *((value, 200) for value in profile.handles),
            *((value, 100) for value in profile.projects),
        )
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
        raise ValueError(f"ambiguous AgentPost identity {label!r}: {names}")

    raise UnknownAgentError(
        f"unknown AgentPost identity: {label}; use `agentpost agents-find` "
        "for responsibility discovery"
    )


def _normalize(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.lower()))


def _tokens(values: Iterable[str]) -> set[str]:
    tokens = set()
    for value in values:
        tokens.update(_normalize(value).split())
    return tokens
