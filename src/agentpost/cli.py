from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .core import AgentPostError, PostOffice, Profile
from .routing import (
    find_agents,
    identify_agent,
    project_candidates,
    resolve_channel_recipients,
    resolve_group,
    resolve_identity,
    resolve_recipients,
)
from .panels import ask, panel_status, wait_for_panel
from .adapters import MailboxWatcher
from .installer import armed, doctor, install, uninstall
from .presence import agent_presence
from .native import (
    antigravity_hook,
    antigravity_launch,
    claude_launch,
    claude_boundary,
    claude_monitor,
    codex_hook,
    codex_launch,
    codex_snapshot,
)


_PROFILE_GUIDANCE = """good profile guidance:
  summary            One durable sentence: what this agent owns and what
                     decisions or outputs it can help with. Use terms a
                     coworker would actually search.
  roles              Broad workplace functions, such as release engineering.
  projects           Stable project names and aliases users will mention.
  specialties        Specific reusable technical or domain expertise.
  handles             Two to five concrete request categories this agent
                     should receive, such as schema reviews or launch copy.
  does-not-handle    Nearby responsibilities owned elsewhere.

Prefer: "Owns Pattern Buffer temporal world-state semantics, ingestion
fidelity, and deterministic retrieval contracts."
Avoid: "Helpful coding agent working on the current task."

Keep the nameplate stable. Do not include current task/status, availability,
generic personality claims, unverified aspirations, or secrets.

Example:
  agentpost profile-register reviewer --display-name 'Code Review' --kind role
    --summary 'Reviews implementation correctness and regression risk.'
    --roles 'code review' --specialties 'correctness,regression analysis'
"""


def _csv(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _office(args: argparse.Namespace) -> PostOffice:
    return PostOffice(args.root)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agentpost")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(os.environ.get("AGENTPOST_ROOT", "~/.agentpost")).expanduser(),
    )
    commands = parser.add_subparsers(dest="command", required=True)

    init = commands.add_parser("init")
    init.add_argument("--connection-mode", choices=("auto", "manual"))
    commands.add_parser("migrate")

    profile = commands.add_parser(
        "profile-register",
        description=(
            "Create or update the durable nameplate other agents use for "
            "addressing and responsibility discovery."
        ),
        epilog=_PROFILE_GUIDANCE,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    profile.add_argument("name", help="stable short mailbox address")
    profile.add_argument(
        "--display-name", required=True, help="recognizable human-facing name"
    )
    profile.add_argument(
        "--cli",
        help=(
            "optional first-connection hint: antigravity, claude, codex, or python; "
            "the mailbox itself is CLI-neutral"
        ),
    )
    profile.add_argument(
        "--kind", required=True, help="descriptive kind: project, role, specialist, or hybrid"
    )
    profile.add_argument(
        "--summary", required=True, help="searchable sentence describing durable ownership"
    )
    profile.add_argument("--organization", help="optional stable organization or team")
    profile.add_argument("--roles", default="", help="comma-separated workplace functions")
    profile.add_argument("--projects", default="", help="comma-separated project names or aliases")
    profile.add_argument(
        "--project-roots", default="", help="comma-separated absolute project roots"
    )
    profile.add_argument("--specialties", default="", help="comma-separated reusable expertise")
    profile.add_argument(
        "--handles", default="", help="comma-separated concrete request categories"
    )
    profile.add_argument(
        "--does-not-handle",
        default="",
        help="comma-separated neighboring responsibilities owned elsewhere",
    )

    profiles = commands.add_parser("profiles")
    profiles_mode = profiles.add_mutually_exclusive_group()
    profiles_mode.add_argument("--all", action="store_true")
    profiles_mode.add_argument("--offline", action="store_true")

    find = commands.add_parser("agents-find")
    find.add_argument("query", nargs="?")
    find.add_argument("--role")
    find.add_argument("--project")
    find.add_argument("--specialty")
    find.add_argument("--all", action="store_true")

    commands.add_parser("identities")
    resolve = commands.add_parser("resolve")
    resolve.add_argument("label")

    group = commands.add_parser("group-set")
    group.add_argument("name")
    group.add_argument("members")
    commands.add_parser("groups")

    identify = commands.add_parser("identify")
    identify.add_argument("--cwd", type=Path, default=Path.cwd())
    identify.add_argument("--cli")
    identify.add_argument("--agent")

    connect = commands.add_parser("connect")
    connect.add_argument("agent", nargs="?")
    connect.add_argument("--cli", choices=("antigravity", "claude", "codex", "python"))
    connect.add_argument("--project", type=Path, default=Path.cwd())
    join = commands.add_parser("join")
    join.add_argument("agent", nargs="?")
    join.add_argument("--cli", choices=("antigravity", "claude", "codex", "python"))
    join.add_argument("--project", type=Path, default=Path.cwd())
    disconnect = commands.add_parser("disconnect")
    disconnect.add_argument(
        "--cli", choices=("antigravity", "claude", "codex"), required=True
    )
    disconnect.add_argument("--project", type=Path, default=Path.cwd())
    commands.add_parser("bindings")
    status = commands.add_parser("status")
    status.add_argument("agent", nargs="?")

    send = commands.add_parser("send")
    send.add_argument("sender")
    send.add_argument("recipient")
    send.add_argument("body")
    send.add_argument("--subject")
    send.add_argument("--kind", choices=("letter", "question", "answer", "error"), default="letter")
    send.add_argument("--notify", choices=("idle", "immediate"), default="idle")

    message = commands.add_parser("message")
    message.add_argument("recipient")
    message.add_argument("body", nargs="?")
    message.add_argument("--from", dest="sender")
    message.add_argument("--subject")
    message.add_argument("--notify", choices=("idle", "immediate"), default="idle")

    question = commands.add_parser("ask")
    question.add_argument("sender")
    question.add_argument("recipients")
    question.add_argument("body")
    question.add_argument("--subject")
    question.add_argument("--notify", choices=("idle", "immediate"), default="immediate")
    question.add_argument("--wait", type=float)
    question.add_argument("--quorum", type=int)

    channel_question = commands.add_parser("question")
    channel_question.add_argument("recipient")
    channel_question.add_argument("body", nargs="?")
    channel_question.add_argument("--from", dest="sender")
    channel_question.add_argument("--subject")
    channel_question.add_argument(
        "--notify", choices=("idle", "immediate"), default="immediate"
    )
    channel_question.add_argument("--wait", type=float)
    channel_question.add_argument("--quorum", type=int)

    panel = commands.add_parser("panel")
    panel.add_argument("originator")
    panel.add_argument("message_id")
    panel.add_argument("--quorum", type=int)

    listing = commands.add_parser("list")
    listing.add_argument("agent")
    listing.add_argument("--state", choices=("unread", "read", "sent"), default="unread")

    read = commands.add_parser("read")
    read.add_argument("agent")
    read.add_argument("message_id")

    claim = commands.add_parser("next")
    claim.add_argument("agent")
    claim.add_argument("--message-id")

    watch = commands.add_parser("watch")
    watch.add_argument("agent")
    watch.add_argument("--interval", type=float, default=1.0)
    watch.add_argument("--once", action="store_true")

    reply = commands.add_parser("reply")
    reply.add_argument(
        "parts",
        nargs="*",
        help="MESSAGE_ID [BODY], or legacy AGENT MESSAGE_ID [BODY]",
    )
    reply.add_argument("--from", dest="sender")
    reply.add_argument("--notify", choices=("idle", "immediate"), default="immediate")

    native_claude_boundary = commands.add_parser("internal-claude-boundary")
    native_claude_boundary.add_argument("state", choices=("busy", "idle"))
    native_claude_boundary.add_argument("--delay", type=float, default=0.0)
    commands.add_parser("internal-claude-monitor")
    native_codex = commands.add_parser("internal-codex-hook")
    native_codex.add_argument("event", choices=("session-start", "stop"))
    native_antigravity = commands.add_parser("internal-antigravity-hook")
    native_antigravity.add_argument("event", choices=("pre-invocation", "stop"))
    native_snapshot = commands.add_parser("internal-snapshot")
    native_snapshot.add_argument("agent")
    codex = commands.add_parser("codex")
    codex.add_argument("--agent")
    codex.add_argument("codex_args", nargs=argparse.REMAINDER)
    claude = commands.add_parser("claude")
    claude.add_argument("--agent", required=True)
    claude.add_argument("claude_args", nargs=argparse.REMAINDER)
    antigravity = commands.add_parser("antigravity")
    antigravity.add_argument("--agent", required=True)
    antigravity.add_argument("antigravity_args", nargs=argparse.REMAINDER)
    install_command = commands.add_parser("install")
    install_command.add_argument("cli", choices=("antigravity", "claude", "codex"))
    install_command.add_argument("--agent", required=True)
    install_command.add_argument("--project", type=Path, required=True)
    doctor_command = commands.add_parser("doctor")
    doctor_command.add_argument("agent")
    doctor_command.add_argument("--project", type=Path, required=True)
    doctor_command.add_argument(
        "--cli", choices=("antigravity", "claude", "codex", "python")
    )
    uninstall_command = commands.add_parser("uninstall")
    uninstall_command.add_argument("cli", choices=("antigravity", "claude", "codex"))
    uninstall_command.add_argument("--project", type=Path, required=True)
    armed_command = commands.add_parser("armed")
    armed_command.add_argument("agent")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = _parse_args(parser, argv)
    office = _office(args)
    try:
        if args.command == "init":
            print(office.initialize(_init_connection_mode(office, args.connection_mode)))
        elif args.command == "migrate":
            actions = office.migrate()
            for action in actions:
                print(f"MIGRATED\t{action}")
            if not actions:
                print("CURRENT\tno metadata migration needed")
        elif args.command == "profile-register":
            profile = Profile(
                name=args.name,
                display_name=args.display_name,
                cli=args.cli,
                kind=args.kind,
                summary=args.summary,
                organization=args.organization,
                roles=_csv(args.roles),
                projects=_csv(args.projects),
                project_roots=_csv(args.project_roots),
                specialties=_csv(args.specialties),
                handles=_csv(args.handles),
                does_not_handle=_csv(args.does_not_handle),
            )
            print(office.register_profile(profile))
        elif args.command == "profiles":
            for profile in office.list_profiles():
                presence = agent_presence(office, profile.name)
                if not args.all and not args.offline and not presence.active:
                    continue
                if args.offline and presence.active:
                    continue
                adapters = _profile_adapters(office, profile.name, profile.cli)
                print(
                    f"{profile.name}\t{presence.state}\t{','.join(adapters) or '-'}\t"
                    f"{profile.kind}\t{profile.summary}"
                )
        elif args.command == "agents-find":
            for match in find_agents(
                office,
                args.query,
                role=args.role,
                project=args.project,
                specialty=args.specialty,
                include_offline=args.all,
            ):
                reasons = "; ".join(match.reasons)
                evidence = ",".join(match.evidence)
                print(
                    f"{match.profile.name}\t{match.presence}\t{match.score}\t{reasons}"
                    f"\t{evidence}"
                )
        elif args.command == "identities":
            print("type\taddress\tattention\tdisplay\tprojects\thandles\tsummary")
            for profile in office.list_profiles():
                presence = agent_presence(office, profile.name)
                print(
                    f"agent\t{profile.name}\t{presence.state}\t"
                    f"{profile.display_name}\t{','.join(profile.projects)}\t"
                    f"{','.join(profile.handles)}\t{profile.summary}"
                )
            for name, members in sorted(office.list_groups().items()):
                print(f"group\t@{name}\t-\t{name}\t{','.join(members)}")
        elif args.command == "resolve":
            _print_resolution(office, args.label)
        elif args.command == "group-set":
            print(office.set_group(args.name, _csv(args.members)))
        elif args.command == "groups":
            for name, members in sorted(office.list_groups().items()):
                print(f"{name}\t{','.join(members)}")
        elif args.command == "identify":
            print(
                identify_agent(
                    office,
                    args.cwd,
                    cli=args.cli,
                    agent=args.agent or os.environ.get("AGENTPOST_AGENT"),
                ).name
            )
        elif args.command in {"connect", "join"}:
            return _join(office, args.agent, args.cli, args.project)
        elif args.command == "disconnect":
            if not office.unbind_agent(args.cli, args.project):
                raise ValueError(
                    f"no {args.cli} binding exists for {args.project.expanduser().resolve()}"
                )
        elif args.command == "bindings":
            for binding in office.list_bindings():
                print(f"{binding.agent}\t{binding.cli}\t{binding.project}")
        elif args.command == "status":
            names = (
                (args.agent,)
                if args.agent
                else tuple(profile.name for profile in office.list_profiles())
            )
            for name in names:
                presence = agent_presence(office, name)
                print(f"{name}\t{presence.state}\t{presence.detail}")
        elif args.command == "send":
            recipients = resolve_recipients(
                office,
                (args.recipient,),
                sender=args.sender,
                groups=office.list_groups(),
            )
            result = office.send_many(
                args.sender,
                recipients,
                args.body,
                subject=args.subject,
                kind=args.kind,
                notify=args.notify,
            )
            print(result.message_id)
            for recipient, error in result.failures:
                print(f"agentpost: {recipient}: {error}", file=sys.stderr)
            for recipient, error in result.notification_failures:
                print(
                    f"agentpost: delivered to {recipient}; notification failed: {error}",
                    file=sys.stderr,
                )
            _warn_unarmed(office, recipients)
        elif args.command == "message":
            sender = _channel_sender(office, args.sender)
            recipients = resolve_channel_recipients(
                office,
                (args.recipient,),
                sender=sender,
            )
            result = office.send_many(
                sender,
                recipients,
                _channel_body(args.body),
                subject=args.subject,
                notify=args.notify,
            )
            _print_channel_delivery(office, sender, recipients, result)
            _warn_unarmed(office, recipients)
        elif args.command == "ask":
            recipients = resolve_recipients(
                office,
                (args.recipients,),
                sender=args.sender,
                groups=office.list_groups(),
            )
            result = ask(
                office,
                args.sender,
                recipients,
                args.body,
                subject=args.subject,
                notify=args.notify,
            )
            print(result.message_id)
            _warn_unarmed(office, recipients)
            status = None
            if args.wait is not None:
                status = wait_for_panel(
                    office,
                    args.sender,
                    result.message_id,
                    quorum=args.quorum,
                    timeout=args.wait,
                )
            if status is not None:
                _print_panel(status)
                if not status.complete:
                    return 2
        elif args.command == "question":
            sender = _channel_sender(office, args.sender)
            recipients = resolve_channel_recipients(
                office,
                (args.recipient,),
                sender=sender,
            )
            result = ask(
                office,
                sender,
                recipients,
                _channel_body(args.body),
                subject=args.subject,
                notify=args.notify,
            )
            _print_channel_delivery(office, sender, recipients, result)
            _warn_unarmed(office, recipients)
            status = None
            if args.wait is not None:
                status = wait_for_panel(
                    office,
                    sender,
                    result.message_id,
                    quorum=args.quorum,
                    timeout=args.wait,
                )
            if status is not None:
                _print_panel(status)
                if not status.complete:
                    return 2
        elif args.command == "panel":
            _print_panel(
                panel_status(
                    office,
                    args.originator,
                    args.message_id,
                    quorum=args.quorum,
                )
            )
        elif args.command == "list":
            for record in office.list_messages(args.agent, args.state):
                letter = record.letter
                print(
                    f"{letter.message_id}\t{letter.from_agent}\t"
                    f"{letter.kind}\t{letter.subject or ''}"
                )
        elif args.command == "read":
            record = office.read(args.agent, args.message_id)
            sys.stdout.buffer.write(record.path.read_bytes())
        elif args.command == "next":
            record = office.claim(args.agent, args.message_id)
            sys.stdout.buffer.write(record.path.read_bytes())
        elif args.command == "watch":
            watcher = MailboxWatcher(office, args.agent, args.interval)
            if args.once:
                records = watcher.pending()
            else:
                records = watcher.events()
            for record in records:
                print(
                    json.dumps(
                        {
                            "message_id": record.letter.message_id,
                            "from": record.letter.from_agent,
                            "kind": record.letter.kind,
                            "notify": record.letter.notify,
                            "path": str(record.path),
                        }
                    ),
                    flush=True,
                )
        elif args.command == "reply":
            replier, message_id, body = _reply_parts(office, args.parts, args.sender)
            recipient = office.read(replier, message_id).letter.from_agent
            result = office.reply(
                replier,
                message_id,
                _channel_body(body),
                notify=args.notify,
            )
            print(result.message_id)
            _warn_unarmed(office, (recipient,))
        elif args.command == "internal-claude-boundary":
            return claude_boundary(args.state, args.delay)
        elif args.command == "internal-claude-monitor":
            return claude_monitor()
        elif args.command == "internal-codex-hook":
            return codex_hook(args.event)
        elif args.command == "internal-antigravity-hook":
            return antigravity_hook(args.event)
        elif args.command == "internal-snapshot":
            return codex_snapshot(office, args.agent)
        elif args.command == "codex":
            return codex_launch(
                office,
                Path.cwd(),
                _launcher_args(args.codex_args),
                agent=args.agent,
            )
        elif args.command == "claude":
            return claude_launch(
                office,
                Path.cwd(),
                _launcher_args(args.claude_args),
                agent=args.agent,
            )
        elif args.command == "antigravity":
            return antigravity_launch(
                office,
                Path.cwd(),
                _launcher_args(args.antigravity_args),
                agent=args.agent,
            )
        elif args.command == "install":
            install(office, args.cli, args.agent, args.project)
        elif args.command == "doctor":
            checks = doctor(office, args.agent, args.project, args.cli)
            for check in checks:
                print(f"{'PASS' if check.ok else 'FAIL'}\t{check.name}\t{check.detail}")
            return 0 if all(check.ok for check in checks) else 1
        elif args.command == "uninstall":
            uninstall(args.cli, args.project)
        elif args.command == "armed":
            is_armed, detail = armed(office, args.agent)
            print(f"{'ARMED' if is_armed else 'QUEUED'}\t{args.agent}\t{detail}")
            return 0 if is_armed else 2
        else:
            parser.error(f"unknown command: {args.command}")
    except (AgentPostError, ValueError) as exc:
        print(f"agentpost: {exc}", file=sys.stderr)
        return 1
    return 0


def _parse_args(
    parser: argparse.ArgumentParser, argv: list[str] | None
) -> argparse.Namespace:
    args, extras = parser.parse_known_args(argv)
    supports_optional_body = args.command in {"message", "question"}
    if (
        supports_optional_body
        and args.body is None
        and len(extras) == 1
        and (extras[0] == "-" or not extras[0].startswith("-"))
    ):
        args.body = extras[0]
        return args
    if (
        args.command == "reply"
        and len(extras) == 1
        and (extras[0] == "-" or not extras[0].startswith("-"))
    ):
        args.parts.append(extras[0])
        return args
    if extras:
        parser.error(f"unrecognized arguments: {' '.join(extras)}")
    return args


def _print_panel(status) -> None:
    states = {name: "pending" for name in status.pending}
    states.update({name: "answered" for name in status.answered})
    states.update({name: "error" for name in status.errors})
    for name in status.audience:
        print(f"{name}\t{states[name]}")
    print(
        f"quorum\t{len(status.answered) + len(status.errors)}/"
        f"{status.quorum}\t{'complete' if status.complete else 'incomplete'}"
    )
    for record in status.duplicates:
        print(f"duplicate\t{record.letter.from_agent}\t{record.letter.message_id}")


def _channel_sender(office: PostOffice, requested: str | None) -> str:
    if requested is not None:
        return resolve_identity(office, requested).name
    return identify_agent(
        office,
        Path.cwd(),
        agent=os.environ.get("AGENTPOST_AGENT"),
    ).name


def _channel_body(value: str | None) -> str:
    if value not in {None, "-"}:
        return value
    if sys.stdin.isatty():
        raise ValueError("message body is required; pass it as an argument or stdin")
    body = sys.stdin.read()
    if not body:
        raise ValueError("message body must not be empty")
    return body


def _reply_parts(
    office: PostOffice, parts: list[str], requested_sender: str | None
) -> tuple[str, str, str | None]:
    if not parts:
        raise ValueError("reply requires MESSAGE_ID")
    known = {profile.name for profile in office.list_profiles()}
    if parts[0] in known:
        if requested_sender is not None:
            raise ValueError("do not combine legacy AGENT reply syntax with --from")
        if len(parts) not in {2, 3}:
            raise ValueError("legacy reply syntax is AGENT MESSAGE_ID [BODY]")
        return parts[0], parts[1], parts[2] if len(parts) == 3 else None
    if len(parts) not in {1, 2}:
        raise ValueError("reply syntax is MESSAGE_ID [BODY]")
    sender = _channel_sender(office, requested_sender)
    return sender, parts[0], parts[1] if len(parts) == 2 else None


def _print_resolution(office: PostOffice, label: str) -> None:
    groups = office.list_groups()
    name = resolve_group(office, label)
    if name is not None:
        if not label.startswith("@"):
            try:
                identity = resolve_identity(office, label)
            except AgentPostError:
                identity = None
            if identity is not None:
                raise ValueError(
                    f"ambiguous AgentPost address {label!r}: "
                    f"agent {identity.name} or group @{name}"
                )
        print(f"group\t@{name}\t{','.join(groups[name])}")
        return
    profile = resolve_identity(office, label)
    presence = agent_presence(office, profile.name)
    print(f"agent\t{profile.name}\t{presence.state}\t{profile.display_name}")


def _print_channel_delivery(office, sender, recipients, result) -> None:
    print(f"MESSAGE\t{result.message_id}")
    print(f"FROM\t{sender}")
    failed = {recipient: error for recipient, error in result.failures}
    notify_failed = {
        recipient: error for recipient, error in result.notification_failures
    }
    for recipient in recipients:
        if recipient in failed:
            print(f"FAILED\t{recipient}\t{failed[recipient]}", file=sys.stderr)
            continue
        presence = agent_presence(office, recipient)
        is_armed, _ = armed(office, recipient)
        disposition = (
            "notified"
            if is_armed and recipient not in notify_failed
            else "queued"
        )
        print(f"TO\t{recipient}\t{presence.state}\t{disposition}")
    for recipient, error in result.notification_failures:
        print(
            f"agentpost: delivered to {recipient}; notification failed: {error}",
            file=sys.stderr,
        )


def _init_connection_mode(office: PostOffice, requested: str | None) -> str | None:
    if requested is not None or (office.root / "config.toml").exists():
        return requested
    if not sys.stdin.isatty():
        return "auto"
    answer = input(
        "Reconnect registered project mailboxes automatically when their CLI opens? "
        "[Y/n] "
    ).strip().lower()
    return "manual" if answer in {"n", "no"} else "auto"


def _launcher_args(values: list[str]) -> list[str]:
    return values[1:] if values[:1] == ["--"] else values


def _join(
    office: PostOffice,
    requested_agent: str | None,
    requested_cli: str | None,
    project: Path,
) -> int:
    project = project.expanduser().resolve()
    agent = requested_agent or _infer_join_agent(office, project, requested_cli)
    profile = office.load_profile(agent)
    cli = _join_cli(office, agent, project, requested_cli, profile.cli)
    if cli == "python":
        office.bind_agent(agent, cli, project)
    else:
        install(office, cli, agent, project)
    print(f"JOINED\t{agent}\t{cli}\t{project}")
    if cli == "python":
        print(
            "NEXT\tembed `agentpost.AgentRuntime` in the application and enqueue "
            "its Message-ID notifications into the host scheduler; "
            f"`agentpost doctor {agent} --project {project} --cli python` verifies setup"
        )
    elif cli == "claude":
        is_armed, _ = armed(office, agent)
        if not is_armed:
            print(
                "AGENTPOST-DIRECTIVE\tFor this running Claude session, invoke "
                "the Monitor tool with command `agentpost internal-claude-monitor`, "
                "description `AgentPost inbox stream`, persistent `true`."
            )
        print(
            "NEXT\trestart the session or reload through `/plugin`, and approve "
            "the AgentPost marketplace trust prompt on first load; "
            "future sessions at this root reconnect through the installed "
            "session-start hook; "
            f"`agentpost doctor {agent} --project {project} --cli claude` verifies recovery"
        )
    elif cli == "codex":
        print(
            f"NEXT\ttrust AgentPost hooks, then run "
            f"`agentpost codex --agent {agent}`"
        )
    else:
        print(
            "NEXT\trestart Antigravity CLI so it loads the AgentPost plugin, "
            f"using `agentpost antigravity --agent {agent}` so shell commands "
            "retain this mailbox identity; then send one prompt to trigger "
            "exact unread catch-up; "
            f"`agentpost doctor {agent} --project {project} --cli antigravity` "
            "verifies installation. Already-idle external wake is not yet supported."
        )
    return 0


def _infer_join_agent(
    office: PostOffice,
    project: Path,
    cli: str | None,
) -> str:
    candidates = project_candidates(office, project, cli=cli)
    if len(candidates) == 1:
        return candidates[0].name
    if candidates:
        choices = ", ".join(profile.name for profile in candidates)
        raise ValueError(
            f"multiple mailbox profiles match {project}: {choices}; "
            "run `agentpost join NAME`"
        )
    available = (
        ", ".join(profile.name for profile in office.list_profiles())
        or "none registered"
    )
    raise ValueError(
        f"no mailbox profile root matches {project}; candidates: {available}; "
        "run `agentpost join NAME`"
    )


def _warn_unarmed(office: PostOffice, recipients) -> None:
    for recipient in recipients:
        is_armed, detail = armed(office, recipient)
        if not is_armed:
            print(
                f"agentpost: delivered to {recipient}; notifier not armed: {detail}",
                file=sys.stderr,
            )


def _join_cli(
    office: PostOffice,
    agent: str,
    project: Path,
    requested: str | None,
    hint: str | None,
) -> str:
    if requested is not None:
        return requested
    exact = {
        binding.cli
        for binding in office.list_bindings()
        if binding.agent == agent and Path(binding.project) == project
    }
    if len(exact) == 1:
        return exact.pop()
    if hint is not None:
        return hint
    detected = _detect_cli()
    if detected is not None:
        return detected
    if exact:
        raise ValueError(
            f"multiple adapters already connect {agent} at {project}; pass --cli"
        )
    raise ValueError(
        "cannot infer this process's CLI; pass --cli antigravity, claude, codex, or python"
    )


def _detect_cli() -> str | None:
    if os.environ.get("AGENTPOST_CLI"):
        return os.environ["AGENTPOST_CLI"]
    if os.environ.get("CODEX_THREAD_ID") or os.environ.get("CODEX_CI"):
        return "codex"
    if os.environ.get("CLAUDECODE") or os.environ.get("CLAUDE_PLUGIN_ROOT"):
        return "claude"
    if os.environ.get("ANTIGRAVITY_CLI") or os.environ.get("AGY_SESSION_ID"):
        return "antigravity"
    return None


def _profile_adapters(
    office: PostOffice, agent: str, hint: str | None = None
) -> tuple[str, ...]:
    values = {
        binding.cli for binding in office.list_bindings() if binding.agent == agent
    }
    if hint:
        values.add(hint)
    return tuple(sorted(values))


if __name__ == "__main__":
    raise SystemExit(main())
