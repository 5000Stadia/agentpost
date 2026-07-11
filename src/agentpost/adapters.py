from __future__ import annotations

import time
from dataclasses import dataclass, replace
from typing import Iterator, Protocol

from .core import MessageRecord, PostOffice


@dataclass(frozen=True)
class BellCapabilities:
    immediate: str
    idle: str
    catch_up: bool = True


class Bell(Protocol):
    def notify(self, agent: str, message_id: str, mode: str) -> None: ...

    def on_turn_start(self, agent: str) -> None: ...

    def on_turn_complete(self, agent: str) -> None: ...

    def capabilities(self) -> BellCapabilities: ...


class RecordingBell:
    """Deterministic test adapter; it never starts a model or process."""

    def __init__(self) -> None:
        self.notifications: list[tuple[str, str, str]] = []
        self.completed: list[str] = []

    def notify(self, agent: str, message_id: str, mode: str) -> None:
        self.notifications.append((agent, message_id, mode))

    def on_turn_complete(self, agent: str) -> None:
        self.completed.append(agent)

    def on_turn_start(self, agent: str) -> None:
        pass

    def capabilities(self) -> BellCapabilities:
        return BellCapabilities("recorded", "recorded")


class BoundaryBell:
    """Reference attention scheduler used by native adapter tests."""

    def __init__(self) -> None:
        self.busy: set[str] = set()
        self.queued: dict[str, list[str]] = {}
        self.surfaced: list[tuple[str, str, str]] = []

    def notify(self, agent: str, message_id: str, mode: str) -> None:
        if mode not in {"immediate", "idle"}:
            raise ValueError(f"invalid notify mode: {mode}")
        if mode == "idle" and agent in self.busy:
            self.queued.setdefault(agent, []).append(message_id)
            return
        self.surfaced.append((agent, message_id, mode))

    def on_turn_start(self, agent: str) -> None:
        self.busy.add(agent)

    def on_turn_complete(self, agent: str) -> None:
        self.busy.discard(agent)
        for message_id in self.queued.pop(agent, []):
            self.surfaced.append((agent, message_id, "idle"))

    def capabilities(self) -> BellCapabilities:
        return BellCapabilities("earliest adapter boundary", "turn completion")


class MailboxWatcher:
    """Polling fallback that emits pointers without changing mailbox state."""

    def __init__(self, office: PostOffice, agent: str, interval: float = 1.0):
        if interval <= 0:
            raise ValueError("watch interval must be positive")
        office.load_profile(agent)
        self.office = office
        self.agent = agent
        self.interval = interval
        self._surfaced: set[str] = set()

    def pending(self) -> tuple[MessageRecord, ...]:
        records = self.office.list_messages(self.agent, "unread")
        requests = self.office.notification_requests(self.agent)
        forced = {}
        for request in requests:
            previous = forced.get(request.message_id)
            forced[request.message_id] = (
                "immediate"
                if request.notify == "immediate" or previous == "immediate"
                else "idle"
            )
        fresh = []
        for record in records:
            message_id = record.letter.message_id
            if message_id in self._surfaced and message_id not in forced:
                continue
            if message_id in forced and record.letter.notify != forced[message_id]:
                record = replace(record, letter=replace(record.letter, notify=forced[message_id]))
            fresh.append(record)
        delivered = {record.letter.message_id for record in fresh}
        for request in requests:
            if request.message_id in delivered:
                self.office.acknowledge_notification(self.agent, request.request_id)
        self._surfaced.update(record.letter.message_id for record in fresh)
        return tuple(fresh)

    def events(self) -> Iterator[MessageRecord]:
        while True:
            yield from self.pending()
            time.sleep(self.interval)
