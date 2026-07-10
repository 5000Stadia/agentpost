from __future__ import annotations

import time
from dataclasses import dataclass

from .core import FanoutResult, MessageRecord, PostOffice


@dataclass(frozen=True)
class PanelStatus:
    message_id: str
    audience: tuple[str, ...]
    responses: tuple[MessageRecord, ...]
    answered: tuple[str, ...]
    errors: tuple[str, ...]
    pending: tuple[str, ...]
    duplicates: tuple[MessageRecord, ...]
    unexpected: tuple[MessageRecord, ...]
    quorum: int
    complete: bool


def ask(
    office: PostOffice,
    sender: str,
    recipients: tuple[str, ...],
    body: str,
    **kwargs,
) -> FanoutResult:
    kwargs.setdefault("kind", "question")
    kwargs.setdefault("notify", "immediate")
    return office.send_many(sender, recipients, body, **kwargs)


def panel_status(
    office: PostOffice,
    originator: str,
    message_id: str,
    *,
    quorum: int | None = None,
) -> PanelStatus:
    root = office.read(originator, message_id, ("sent",)).letter
    audience = root.audience
    requested = len(audience) if quorum is None else quorum
    if requested < 1 or requested > len(audience):
        raise ValueError(f"quorum must be between 1 and {len(audience)}")

    records = sorted(
        (
            *office.list_messages(originator, "unread"),
            *office.list_messages(originator, "read"),
        ),
        key=lambda record: record.path.name,
    )
    responses = tuple(
        record
        for record in records
        if record.letter.in_reply_to == message_id
        and record.letter.kind in {"answer", "error"}
    )
    first_by_sender = {}
    duplicates = []
    unexpected = []
    for record in responses:
        sender = record.letter.from_agent
        if sender not in audience:
            unexpected.append(record)
        elif sender in first_by_sender:
            duplicates.append(record)
        else:
            first_by_sender[sender] = record

    answered = tuple(
        name
        for name in audience
        if name in first_by_sender and first_by_sender[name].letter.kind == "answer"
    )
    errors = tuple(
        name
        for name in audience
        if name in first_by_sender and first_by_sender[name].letter.kind == "error"
    )
    pending = tuple(name for name in audience if name not in first_by_sender)
    return PanelStatus(
        message_id=message_id,
        audience=audience,
        responses=responses,
        answered=answered,
        errors=errors,
        pending=pending,
        duplicates=tuple(duplicates),
        unexpected=tuple(unexpected),
        quorum=requested,
        complete=len(first_by_sender) >= requested,
    )


def wait_for_panel(
    office: PostOffice,
    originator: str,
    message_id: str,
    *,
    quorum: int | None = None,
    timeout: float,
    poll_interval: float = 0.1,
) -> PanelStatus:
    if timeout < 0:
        raise ValueError("timeout must not be negative")
    deadline = time.monotonic() + timeout
    while True:
        status = panel_status(office, originator, message_id, quorum=quorum)
        if status.complete or time.monotonic() >= deadline:
            return status
        time.sleep(min(poll_interval, max(0.0, deadline - time.monotonic())))
