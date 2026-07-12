from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .core import FanoutResult, PostOffice, Profile
from .panels import ask
from .presence import agent_presence
from .routing import resolve_channel_recipients, resolve_identity
from .review import prepare_review, render_review_request


@dataclass(frozen=True)
class Identity:
    name: str
    display_name: str
    presence: str
    summary: str


class AgentChannel:
    """Sender-bound, CLI-neutral AgentPost communication surface."""

    def __init__(
        self,
        sender: str,
        *,
        root: str | Path = "~/.agentpost",
        office: PostOffice | None = None,
    ) -> None:
        self.office = office or PostOffice(root)
        self.sender = resolve_identity(self.office, sender).name

    def identities(self) -> tuple[Identity, ...]:
        return tuple(
            Identity(
                name=profile.name,
                display_name=profile.display_name,
                presence=agent_presence(self.office, profile.name).state,
                summary=profile.summary,
            )
            for profile in self.office.list_profiles()
        )

    def resolve(self, address: str) -> tuple[Profile, ...]:
        recipients = resolve_channel_recipients(
            self.office,
            (address,),
            sender=self.sender,
        )
        return tuple(self.office.load_profile(name) for name in recipients)

    def message(
        self,
        address: str,
        body: str,
        *,
        subject: str | None = None,
        notify: str = "idle",
    ) -> FanoutResult:
        recipients = tuple(profile.name for profile in self.resolve(address))
        return self.office.send_many(
            self.sender,
            recipients,
            body,
            subject=subject,
            notify=notify,
        )

    def question(
        self,
        address: str,
        body: str,
        *,
        subject: str | None = None,
        notify: str = "immediate",
    ) -> FanoutResult:
        recipients = tuple(profile.name for profile in self.resolve(address))
        return ask(
            self.office,
            self.sender,
            recipients,
            body,
            subject=subject,
            notify=notify,
        )

    def review(
        self,
        address: str,
        body: str,
        *,
        repository: str | Path,
        commit: str,
        paths: tuple[str, ...],
        tests: tuple[str, ...],
        parent: str | None = None,
        subject: str | None = None,
        notify: str = "immediate",
    ) -> FanoutResult:
        recipients = tuple(profile.name for profile in self.resolve(address))
        artifact = prepare_review(
            repository,
            commit,
            paths,
            tests,
            parent=parent,
        )
        rendered = render_review_request(artifact, body)
        return self.office.send_many(
            self.sender,
            recipients,
            rendered,
            subject=subject or f"Review {artifact.commit[:12]}",
            kind="question",
            notify=notify,
            review=artifact,
        )
