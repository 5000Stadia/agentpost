from __future__ import annotations

import hashlib
import json
import os
import re
import time
import tomllib
import uuid
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from email.header import Header
from email.parser import BytesParser
from email.policy import default as email_policy
from pathlib import Path
from typing import Iterable


AGENT_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
GROUP_NAME_RE = AGENT_NAME_RE
MESSAGE_KINDS = {"letter", "question", "answer", "error"}
NOTIFY_MODES = {"immediate", "idle"}
MAILBOX_DIRS = ("tmp", "unread", "read", "sent", "adapter")
CONNECTION_MODES = {"auto", "manual"}


class AgentPostError(Exception):
    pass


class UnknownAgentError(AgentPostError):
    pass


class DuplicateDeliveryError(AgentPostError):
    pass


class MessageNotFoundError(AgentPostError):
    pass


class InvalidMessageError(AgentPostError):
    pass


@dataclass(frozen=True)
class Experience:
    topic: str
    summary: str
    projects: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class Profile:
    name: str
    display_name: str
    cli: str
    kind: str
    summary: str
    version: int = 1
    organization: str | None = None
    roles: tuple[str, ...] = ()
    projects: tuple[str, ...] = ()
    project_roots: tuple[str, ...] = ()
    specialties: tuple[str, ...] = ()
    handles: tuple[str, ...] = ()
    does_not_handle: tuple[str, ...] = ()
    experience: tuple[Experience, ...] = ()

    def validate(self) -> None:
        _validate_agent_name(self.name)
        for label, value in (
            ("display_name", self.display_name),
            ("cli", self.cli),
            ("kind", self.kind),
            ("summary", self.summary),
        ):
            if not value.strip():
                raise ValueError(f"{label} must not be empty")
        if not (self.roles or self.projects or self.specialties):
            raise ValueError("profile needs at least one role, project, or specialty")


@dataclass(frozen=True)
class Binding:
    agent: str
    cli: str
    project: str


@dataclass(frozen=True)
class Letter:
    message_id: str
    date: str
    from_agent: str
    to_agent: str
    audience: tuple[str, ...]
    kind: str
    notify: str
    body: str
    subject: str | None = None
    in_reply_to: str | None = None
    route_query: str | None = None
    route_reason: str | None = None

    def as_bytes(self) -> bytes:
        headers = (
            ("Message-ID", self.message_id),
            ("Date", self.date),
            ("From", self.from_agent),
            ("To", self.to_agent),
            ("Audience", ",".join(self.audience)),
            ("Subject", self.subject),
            ("In-Reply-To", self.in_reply_to),
            ("X-Agent-Kind", self.kind),
            ("X-Agent-Notify", self.notify),
            ("X-Agent-Route-Query", self.route_query),
            ("X-Agent-Route-Reason", self.route_reason),
        )
        lines = []
        for name, value in headers:
            if value is not None:
                lines.append(_header_line(name, value))
        # Header handles RFC encoding and folding; appending the body ourselves
        # preserves every Markdown byte, including trailing whitespace.
        return ("\n".join(lines) + "\n\n").encode("ascii") + self.body.encode("utf-8")

    @classmethod
    def from_bytes(cls, data: bytes) -> Letter:
        message = BytesParser(policy=email_policy).parsebytes(data)
        required = (
            "Message-ID",
            "Date",
            "From",
            "To",
            "Audience",
            "X-Agent-Kind",
            "X-Agent-Notify",
        )
        missing = [name for name in required if message.get(name) is None]
        if missing:
            raise InvalidMessageError(f"missing headers: {', '.join(missing)}")
        kind = str(message["X-Agent-Kind"])
        notify = str(message["X-Agent-Notify"])
        if kind not in MESSAGE_KINDS:
            raise InvalidMessageError(f"invalid message kind: {kind}")
        if notify not in NOTIFY_MODES:
            raise InvalidMessageError(f"invalid notify mode: {notify}")
        audience = tuple(
            item.strip() for item in str(message["Audience"]).split(",") if item.strip()
        )
        separator = b"\n\n"
        if separator not in data:
            raise InvalidMessageError("message has no header/body separator")
        try:
            body = data.split(separator, 1)[1].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise InvalidMessageError("message body is not valid UTF-8") from exc
        return cls(
            message_id=str(message["Message-ID"]),
            date=str(message["Date"]),
            from_agent=str(message["From"]),
            to_agent=str(message["To"]),
            audience=audience,
            kind=kind,
            notify=notify,
            body=body,
            subject=str(message["Subject"]) if message.get("Subject") else None,
            in_reply_to=(
                str(message["In-Reply-To"]) if message.get("In-Reply-To") else None
            ),
            route_query=(
                str(message["X-Agent-Route-Query"])
                if message.get("X-Agent-Route-Query")
                else None
            ),
            route_reason=(
                str(message["X-Agent-Route-Reason"])
                if message.get("X-Agent-Route-Reason")
                else None
            ),
        )


@dataclass(frozen=True)
class MessageRecord:
    path: Path
    state: str
    letter: Letter


@dataclass(frozen=True)
class DeliveryResult:
    message_id: str
    recipient_path: Path
    sent_path: Path
    notification_error: str | None = None


@dataclass(frozen=True)
class FanoutResult:
    message_id: str
    deliveries: tuple[DeliveryResult, ...]
    failures: tuple[tuple[str, str], ...]
    sent_path: Path
    notification_failures: tuple[tuple[str, str], ...] = ()


class PostOffice:
    def __init__(self, root: str | Path, notifier=None):
        self.root = Path(root).expanduser().resolve()
        self.notifier = notifier

    @property
    def agents_dir(self) -> Path:
        return self.root / "agents"

    @property
    def bindings_dir(self) -> Path:
        return self.root / "bindings"

    def initialize(self, connection_mode: str | None = None) -> Path:
        self.agents_dir.mkdir(parents=True, exist_ok=True)
        self.bindings_dir.mkdir(parents=True, exist_ok=True)
        config = self.root / "config.toml"
        if not config.exists():
            mode = connection_mode or "auto"
            _validate_connection_mode(mode)
            _atomic_write(config, _config_to_toml({}, mode).encode("utf-8"))
        elif connection_mode is not None:
            self.set_connection_mode(connection_mode)
        return self.root

    def connection_mode(self) -> str:
        config = self.root / "config.toml"
        if not config.exists():
            return "auto"
        with config.open("rb") as handle:
            value = tomllib.load(handle).get("connection_mode", "auto")
        _validate_connection_mode(value)
        return value

    def set_connection_mode(self, mode: str) -> Path:
        _validate_connection_mode(mode)
        groups = self.list_groups() if (self.root / "config.toml").exists() else {}
        path = self.root / "config.toml"
        _atomic_write(path, _config_to_toml(groups, mode).encode("utf-8"))
        return path

    def register_profile(self, profile: Profile) -> Path:
        profile.validate()
        self.initialize()
        agent_dir = self._agent_dir(profile.name)
        agent_dir.mkdir(parents=True, exist_ok=True)
        for directory in MAILBOX_DIRS:
            (agent_dir / directory).mkdir(exist_ok=True)
        self._verify_atomic_mailbox(agent_dir)
        path = agent_dir / "profile.toml"
        _atomic_write(path, _profile_to_toml(profile).encode("utf-8"))
        return path

    def load_profile(self, name: str) -> Profile:
        path = self._require_agent(name) / "profile.toml"
        with path.open("rb") as handle:
            data = tomllib.load(handle)
        experiences = tuple(
            Experience(
                topic=item["topic"],
                summary=item["summary"],
                projects=tuple(item.get("projects", ())),
                evidence=tuple(item.get("evidence", ())),
            )
            for item in data.get("experience", ())
        )
        profile = Profile(
            version=data["version"],
            name=data["name"],
            display_name=data["display_name"],
            cli=data["cli"],
            kind=data["kind"],
            summary=data["summary"],
            organization=data.get("organization"),
            roles=tuple(data.get("roles", ())),
            projects=tuple(data.get("projects", ())),
            project_roots=tuple(data.get("project_roots", ())),
            specialties=tuple(data.get("specialties", ())),
            handles=tuple(data.get("handles", ())),
            does_not_handle=tuple(data.get("does_not_handle", ())),
            experience=experiences,
        )
        profile.validate()
        return profile

    def list_profiles(self) -> tuple[Profile, ...]:
        if not self.agents_dir.exists():
            return ()
        profiles = []
        for path in sorted(self.agents_dir.glob("*/profile.toml")):
            profiles.append(self.load_profile(path.parent.name))
        return tuple(profiles)

    def bind_agent(self, name: str, cli: str, project: str | Path) -> Path:
        profile = self.load_profile(name)
        if profile.cli != cli:
            raise ValueError(
                f"mailbox {name} is registered for {profile.cli}, not {cli}"
            )
        current = Path(project).expanduser().resolve()
        self.initialize()
        token = hashlib.sha256(f"{cli}\0{current}".encode("utf-8")).hexdigest()
        path = self.bindings_dir / f"{token}.toml"
        binding = Binding(agent=name, cli=cli, project=str(current))
        _atomic_write(path, _binding_to_toml(binding).encode("utf-8"))
        return path

    def list_bindings(self) -> tuple[Binding, ...]:
        if not self.bindings_dir.exists():
            return ()
        bindings = []
        for path in sorted(self.bindings_dir.glob("*.toml")):
            with path.open("rb") as handle:
                data = tomllib.load(handle)
            binding = Binding(
                agent=str(data["agent"]),
                cli=str(data["cli"]),
                project=str(Path(data["project"]).expanduser().resolve()),
            )
            self.load_profile(binding.agent)
            bindings.append(binding)
        return tuple(bindings)

    def unbind_agent(self, cli: str, project: str | Path) -> bool:
        current = Path(project).expanduser().resolve()
        token = hashlib.sha256(f"{cli}\0{current}".encode("utf-8")).hexdigest()
        path = self.bindings_dir / f"{token}.toml"
        existed = path.exists()
        path.unlink(missing_ok=True)
        if existed:
            _fsync_directory(path.parent)
        return existed

    def list_groups(self) -> dict[str, tuple[str, ...]]:
        self.initialize()
        with (self.root / "config.toml").open("rb") as handle:
            data = tomllib.load(handle)
        return {
            name: tuple(members)
            for name, members in data.get("groups", {}).items()
        }

    def set_group(self, name: str, members: Iterable[str]) -> Path:
        if not GROUP_NAME_RE.fullmatch(name):
            raise ValueError(f"invalid group name: {name!r}")
        roster = tuple(dict.fromkeys(members))
        if not roster:
            raise ValueError("group needs at least one member")
        for member in roster:
            self._require_agent(member)
        groups = self.list_groups()
        groups[name] = roster
        path = self.root / "config.toml"
        _atomic_write(
            path,
            _config_to_toml(groups, self.connection_mode()).encode("utf-8"),
        )
        return path

    def send(
        self,
        sender: str,
        recipient: str,
        body: str,
        *,
        subject: str | None = None,
        kind: str = "letter",
        notify: str = "idle",
        message_id: str | None = None,
        in_reply_to: str | None = None,
        route_query: str | None = None,
        route_reason: str | None = None,
    ) -> DeliveryResult:
        result = self.send_many(
            sender,
            (recipient,),
            body,
            subject=subject,
            kind=kind,
            notify=notify,
            message_id=message_id,
            in_reply_to=in_reply_to,
            route_query=route_query,
            route_reasons={recipient: route_reason} if route_reason else None,
        )
        if result.failures:
            raise AgentPostError(result.failures[0][1])
        return result.deliveries[0]

    def send_many(
        self,
        sender: str,
        recipients: Iterable[str],
        body: str,
        *,
        subject: str | None = None,
        kind: str = "letter",
        notify: str = "idle",
        message_id: str | None = None,
        in_reply_to: str | None = None,
        route_query: str | None = None,
        route_reasons: dict[str, str] | None = None,
    ) -> FanoutResult:
        sender_dir = self._require_agent(sender)
        roster = tuple(dict.fromkeys(recipients))
        if not roster:
            raise ValueError("at least one recipient is required")
        if sender in roster:
            raise ValueError("sender cannot be a recipient")
        recipient_dirs = {name: self._require_agent(name) for name in roster}
        if kind not in MESSAGE_KINDS:
            raise ValueError(f"invalid message kind: {kind}")
        if notify not in NOTIFY_MODES:
            raise ValueError(f"invalid notify mode: {notify}")
        if not body:
            raise ValueError("message body must not be empty")

        logical_id = (
            _canonical_message_id(message_id)
            if message_id is not None
            else f"<{uuid.uuid4()}@agentpost.local>"
        )
        _validate_message_id(logical_id)
        token = _message_token(logical_id)
        with ExitStack() as locks:
            for name in sorted(roster):
                lock_path = recipient_dirs[name] / "adapter" / f"delivery-{token}.lock"
                locks.enter_context(_exclusive_lock(lock_path))
            for name, recipient_dir in recipient_dirs.items():
                if self._find_token(recipient_dir, token, ("unread", "read")):
                    raise DuplicateDeliveryError(
                        f"delivery already exists for {logical_id} and {name}"
                    )
            if self._find_token(sender_dir, token, ("sent",)):
                raise DuplicateDeliveryError(
                    f"sender copy already exists for {logical_id}"
                )

            sent_at = _utc_now()
            filename = f"{time.time_ns():020d}--{token}.md"
            recipient_data = {}
            for name in roster:
                recipient_data[name] = Letter(
                    message_id=logical_id,
                    date=sent_at,
                    from_agent=sender,
                    to_agent=name,
                    audience=roster,
                    kind=kind,
                    notify=notify,
                    body=body,
                    subject=subject,
                    in_reply_to=in_reply_to,
                    route_query=route_query,
                    route_reason=(route_reasons or {}).get(name),
                ).as_bytes()
            sent_data = Letter(
                message_id=logical_id,
                date=sent_at,
                from_agent=sender,
                to_agent=",".join(roster),
                audience=roster,
                kind=kind,
                notify=notify,
                body=body,
                subject=subject,
                in_reply_to=in_reply_to,
                route_query=route_query,
            ).as_bytes()

            delivered_paths = []
            failures = []
            for name, recipient_dir in recipient_dirs.items():
                try:
                    recipient_path = self._deliver(
                        recipient_dir, filename, recipient_data[name]
                    )
                    delivered_paths.append((name, recipient_path))
                except Exception as exc:
                    failures.append((name, str(exc)))

            try:
                sent_path = self._write_sent(sender_dir, filename, sent_data)
            except Exception as exc:
                raise AgentPostError(
                    f"recipient delivery committed, but sent archive failed"
                ) from exc
            notification_failures = []
            completed = []
            for name, recipient_path in delivered_paths:
                notification_error = None
                if self.notifier is not None:
                    try:
                        self.notifier.notify(name, logical_id, notify)
                    except Exception as exc:
                        notification_error = str(exc)
                        notification_failures.append((name, notification_error))
                completed.append(
                    DeliveryResult(
                        logical_id,
                        recipient_path,
                        sent_path,
                        notification_error,
                    )
                )
            return FanoutResult(
                logical_id,
                tuple(completed),
                tuple(failures),
                sent_path,
                tuple(notification_failures),
            )

    def reply(
        self,
        replier: str,
        original_message_id: str,
        body: str,
        *,
        subject: str | None = None,
        notify: str = "immediate",
    ) -> DeliveryResult:
        original = self.read(replier, original_message_id).letter
        reply_subject = subject
        if reply_subject is None and original.subject:
            reply_subject = f"Re: {original.subject}"
        kind = "answer" if original.kind == "question" else "letter"
        return self.send(
            replier,
            original.from_agent,
            body,
            subject=reply_subject,
            kind=kind,
            notify=notify,
            in_reply_to=original.message_id,
        )

    def list_messages(self, agent: str, state: str = "unread") -> tuple[MessageRecord, ...]:
        if state not in {"unread", "read", "sent"}:
            raise ValueError(f"invalid mailbox state: {state}")
        directory = self._require_agent(agent) / state
        records = []
        for path in sorted(directory.glob("*.md")):
            try:
                content = path.read_bytes()
            except FileNotFoundError:
                # A concurrent claim may rename an unread entry after globbing.
                continue
            records.append(MessageRecord(path, state, Letter.from_bytes(content)))
        return tuple(records)

    def read(
        self,
        agent: str,
        message_id: str,
        states: Iterable[str] = ("unread", "read"),
    ) -> MessageRecord:
        message_id = _canonical_message_id(message_id)
        agent_dir = self._require_agent(agent)
        token = _message_token(message_id)
        for state in states:
            if state not in {"unread", "read", "sent"}:
                raise ValueError(f"invalid mailbox state: {state}")
            path = self._find_token(agent_dir, token, (state,))
            if path:
                try:
                    content = path.read_bytes()
                except FileNotFoundError:
                    # An unread entry may move to read between lookup and read.
                    continue
                letter = Letter.from_bytes(content)
                if letter.message_id == message_id:
                    return MessageRecord(path, state, letter)
        raise MessageNotFoundError(f"message not found for {agent}: {message_id}")

    def claim(self, agent: str, message_id: str | None = None) -> MessageRecord:
        agent_dir = self._require_agent(agent)
        if message_id is None:
            candidates = sorted((agent_dir / "unread").glob("*.md"))
            if not candidates:
                raise MessageNotFoundError(f"no unread mail for {agent}")
            source = candidates[0]
        else:
            message_id = _canonical_message_id(message_id)
            source = self._find_token(
                agent_dir, _message_token(message_id), ("unread",)
            )
            if source is None:
                raise MessageNotFoundError(f"unread message not found: {message_id}")
        target = agent_dir / "read" / source.name
        if target.exists():
            raise MessageNotFoundError("message was already claimed")
        try:
            os.rename(source, target)
        except FileNotFoundError as exc:
            raise MessageNotFoundError("message was already claimed") from exc
        _fsync_directory(source.parent)
        _fsync_directory(target.parent)
        return MessageRecord(target, "read", Letter.from_bytes(target.read_bytes()))

    def _deliver(self, agent_dir: Path, filename: str, data: bytes) -> Path:
        return self._publish(agent_dir, "unread", filename, data)

    def _write_sent(self, agent_dir: Path, filename: str, data: bytes) -> Path:
        return self._publish(agent_dir, "sent", filename, data)

    @staticmethod
    def _publish(agent_dir: Path, mailbox: str, filename: str, data: bytes) -> Path:
        temp = agent_dir / "tmp" / f".{filename}.{uuid.uuid4().hex}.tmp"
        destination = agent_dir / mailbox / filename
        _write_new_file(temp, data)
        try:
            if destination.exists():
                raise DuplicateDeliveryError(
                    f"physical message already exists: {destination.name}"
                )
            os.rename(temp, destination)
        except Exception:
            temp.unlink(missing_ok=True)
            raise
        _fsync_directory(destination.parent)
        _fsync_directory(temp.parent)
        return destination

    def _agent_dir(self, name: str) -> Path:
        _validate_agent_name(name)
        return self.agents_dir / name

    def _require_agent(self, name: str) -> Path:
        path = self._agent_dir(name)
        if not (path / "profile.toml").is_file():
            raise UnknownAgentError(f"unknown agent: {name}")
        return path

    @staticmethod
    def _find_token(agent_dir: Path, token: str, states: Iterable[str]) -> Path | None:
        matches = []
        for state in states:
            matches.extend((agent_dir / state).glob(f"*--{token}.md"))
        if len(matches) > 1:
            raise DuplicateDeliveryError(f"multiple physical copies for token {token}")
        return matches[0] if matches else None

    @staticmethod
    def _verify_atomic_mailbox(agent_dir: Path) -> None:
        temp_dir = agent_dir / "tmp"
        unread_dir = agent_dir / "unread"
        if temp_dir.stat().st_dev != unread_dir.stat().st_dev:
            raise AgentPostError("tmp and unread are on different filesystems")
        probe_name = f".rename-probe-{uuid.uuid4().hex}"
        source = temp_dir / probe_name
        target = unread_dir / probe_name
        _write_new_file(source, b"probe")
        try:
            os.rename(source, target)
        finally:
            source.unlink(missing_ok=True)
            target.unlink(missing_ok=True)


def _validate_agent_name(name: str) -> None:
    if not AGENT_NAME_RE.fullmatch(name):
        raise ValueError(f"invalid agent name: {name!r}")


def _validate_connection_mode(mode: str) -> None:
    if mode not in CONNECTION_MODES:
        raise ValueError(f"invalid connection mode: {mode!r}")


def _validate_message_id(message_id: str) -> None:
    if "\n" in message_id or "\r" in message_id:
        raise InvalidMessageError("message ID contains a newline")
    match = re.fullmatch(r"<([0-9a-fA-F-]{36})@agentpost\.local>", message_id)
    if not match:
        raise InvalidMessageError(f"invalid AgentPost Message-ID: {message_id}")
    try:
        uuid.UUID(match.group(1))
    except ValueError as exc:
        raise InvalidMessageError(f"invalid AgentPost Message-ID: {message_id}") from exc


def _canonical_message_id(message_id: str) -> str:
    if "\n" in message_id or "\r" in message_id:
        raise InvalidMessageError("message ID contains a newline")
    candidate = message_id.strip()
    if re.fullmatch(r"[0-9a-fA-F-]{36}", candidate):
        candidate = f"<{candidate}@agentpost.local>"
    elif re.fullmatch(r"[0-9a-fA-F-]{36}@agentpost\.local", candidate):
        candidate = f"<{candidate}>"
    _validate_message_id(candidate)
    return candidate


def _message_token(message_id: str) -> str:
    return hashlib.sha256(message_id.encode("ascii")).hexdigest()[:32]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _header_line(name: str, value: str) -> str:
    if "\n" in value or "\r" in value:
        raise InvalidMessageError(f"{name} contains a newline")
    charset = None if value.isascii() else "utf-8"
    encoded = Header(value, charset, header_name=name).encode(linesep="\n")
    return f"{name}: {encoded}"


def _write_new_file(path: Path, data: bytes) -> None:
    with path.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


@contextmanager
def _exclusive_lock(path: Path):
    import fcntl

    with path.open("a+b") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
    _write_new_file(temp, data)
    try:
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)
    _fsync_directory(path.parent)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=True)


def _toml_array(values: Iterable[str]) -> str:
    return "[" + ", ".join(_toml_string(value) for value in values) + "]"


def _profile_to_toml(profile: Profile) -> str:
    fields = [
        f"version = {profile.version}",
        f"name = {_toml_string(profile.name)}",
        f"display_name = {_toml_string(profile.display_name)}",
        f"cli = {_toml_string(profile.cli)}",
        f"kind = {_toml_string(profile.kind)}",
        f"summary = {_toml_string(profile.summary)}",
    ]
    if profile.organization is not None:
        fields.append(f"organization = {_toml_string(profile.organization)}")
    for name in (
        "roles",
        "projects",
        "project_roots",
        "specialties",
        "handles",
        "does_not_handle",
    ):
        fields.append(f"{name} = {_toml_array(getattr(profile, name))}")
    for item in profile.experience:
        fields.extend(
            (
                "",
                "[[experience]]",
                f"topic = {_toml_string(item.topic)}",
                f"summary = {_toml_string(item.summary)}",
                f"projects = {_toml_array(item.projects)}",
                f"evidence = {_toml_array(item.evidence)}",
            )
        )
    return "\n".join(fields) + "\n"


def _config_to_toml(
    groups: dict[str, tuple[str, ...]], connection_mode: str = "auto"
) -> str:
    _validate_connection_mode(connection_mode)
    lines = ["version = 1", f"connection_mode = {_toml_string(connection_mode)}"]
    if groups:
        lines.extend(("", "[groups]"))
        for name, members in sorted(groups.items()):
            lines.append(f"{name} = {_toml_array(members)}")
    return "\n".join(lines) + "\n"


def _binding_to_toml(binding: Binding) -> str:
    return "\n".join(
        (
            "version = 1",
            f"agent = {_toml_string(binding.agent)}",
            f"cli = {_toml_string(binding.cli)}",
            f"project = {_toml_string(binding.project)}",
            "",
        )
    )
