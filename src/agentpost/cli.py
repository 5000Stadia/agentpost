from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .core import (
    AgentPostError,
    MessageNotFoundError,
    PostOffice,
    Profile,
    UnknownAgentError,
)
from .routing import (
    find_agents,
    identify_agent,
    identify_agent_source,
    project_profiles,
    project_candidates,
    qualified_addresses,
    resolve_channel_recipients,
    resolve_group,
    resolve_identity,
    resolve_recipients,
    workspace_seats,
)
from .panels import ask, panel_status, wait_for_panel
from .adapters import MailboxWatcher
from .codex_session import attach_codex_session
from .installer import armed, doctor, install, uninstall, upgrade
from .ownership import ConsumerLease
from .presence import agent_presence
from .review import prepare_review, render_review_request
from .native import (
    acknowledge_notifications,
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
  projects           Stable dot-free project names and aliases users will use
                     in PROJECT.SEAT addresses.
  specialties        Specific reusable technical or domain expertise.
  handles            Two to five concrete request categories. Put a simple
                     local seat handle first (nav, build, codereview).
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
    profile.add_argument(
        "name",
        help="stable short dot-free mailbox address; dot is reserved",
    )
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
    profile.add_argument(
        "--projects",
        default="",
        help="comma-separated dot-free project names or aliases",
    )
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
    profiles.add_argument("--project")

    find = commands.add_parser("agents-find")
    find.add_argument("query", nargs="?")
    find.add_argument("--role")
    find.add_argument("--project")
    find.add_argument("--specialty")
    find.add_argument("--all", action="store_true")

    identities = commands.add_parser("identities")
    identities.add_argument("--project")
    resolve = commands.add_parser("resolve")
    resolve.add_argument("label")
    resolve.add_argument("--project")

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
    connect.add_argument("--confirm-codex-sessions-closed", action="store_true")
    join = commands.add_parser("join")
    join.add_argument("agent", nargs="?")
    join.add_argument("--cli", choices=("antigravity", "claude", "codex", "python"))
    join.add_argument("--project", type=Path, default=Path.cwd())
    join.add_argument("--confirm-codex-sessions-closed", action="store_true")
    attach = commands.add_parser(
        "attach",
        description=(
            "Bind this already-running Codex thread to a reachable mailbox "
            "without changing the workspace default or global plugin."
        ),
    )
    attach.add_argument("agent")
    attach.add_argument("--project", type=Path, default=Path.cwd())
    disconnect = commands.add_parser("disconnect")
    disconnect.add_argument(
        "--cli", choices=("antigravity", "claude", "codex"), required=True
    )
    disconnect.add_argument("--project", type=Path, default=Path.cwd())
    commands.add_parser("bindings")
    status = commands.add_parser("status")
    status.add_argument("agent", nargs="?")
    status.add_argument("--project")

    wipe = commands.add_parser(
        "wipe",
        description=(
            "Irreversibly remove AgentPost mailbox state. This never deletes "
            "source or bridge repositories."
        ),
    )
    wipe_targets = wipe.add_subparsers(dest="wipe_scope", required=True)
    wipe_agent = wipe_targets.add_parser("agent")
    wipe_agent.add_argument("agent", nargs="?")
    wipe_agent.add_argument("--confirm")
    wipe_project = wipe_targets.add_parser("project")
    wipe_project.add_argument("project")
    wipe_project.add_argument("--confirm")
    wipe_all = wipe_targets.add_parser("all")
    wipe_all.add_argument("--confirm")

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

    review = commands.add_parser(
        "review",
        description="Validate and send an immutable repository review request.",
    )
    review.add_argument("recipient")
    review.add_argument("body", nargs="?")
    review.add_argument("--from", dest="sender")
    review.add_argument("--repo", type=Path, required=True)
    review.add_argument("--commit", required=True)
    review.add_argument("--parent")
    review.add_argument("--path", dest="paths", action="append", required=True)
    review.add_argument("--test", dest="tests", action="append", required=True)
    review.add_argument("--subject")
    review.add_argument(
        "--notify", choices=("idle", "immediate"), default="immediate"
    )

    renotify = commands.add_parser("notify")
    renotify.add_argument("recipient")
    renotify.add_argument("message_id")
    renotify.add_argument("--from", dest="sender")
    renotify.add_argument("--mode", choices=("idle", "immediate"))

    panel = commands.add_parser("panel")
    panel.add_argument("originator")
    panel.add_argument("message_id")
    panel.add_argument("--quorum", type=int)

    listing = commands.add_parser("list")
    listing.add_argument("agent")
    listing.add_argument("--state", choices=("unread", "read", "sent"), default="unread")
    listing.add_argument("--project")

    read = commands.add_parser("read")
    read.add_argument("agent")
    read.add_argument("message_id")
    read.add_argument("--project")

    claim = commands.add_parser("next")
    claim.add_argument("agent")
    claim.add_argument("--message-id")
    claim.add_argument("--project")

    watch = commands.add_parser(
        "watch",
        description=(
            "Stream unread pointers for AGENT as a read-only fallback. This "
            "does not connect the mailbox: it acquires no inbound consumer "
            "lease, publishes no presence, and injects no native "
            "notifications. Senders still see AGENT offline while it runs, "
            "and it stops with the process. It is not a persistent monitor; "
            "use `agentpost join` or a named launcher for live receipt."
        ),
    )
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
    reply.add_argument("--notify", choices=("idle", "immediate"))

    native_claude_boundary = commands.add_parser("internal-claude-boundary")
    native_claude_boundary.add_argument("state", choices=("busy", "idle"))
    native_claude_boundary.add_argument("--delay", type=float, default=0.0)
    commands.add_parser("internal-claude-monitor")
    native_codex = commands.add_parser("internal-codex-hook")
    native_codex.add_argument(
        "event", choices=("session-start", "user-prompt-submit", "stop")
    )
    native_codex.add_argument("--generation")
    native_antigravity = commands.add_parser("internal-antigravity-hook")
    native_antigravity.add_argument("event", choices=("pre-invocation", "stop"))
    native_snapshot = commands.add_parser("internal-snapshot")
    native_snapshot.add_argument("agent")
    native_ack = commands.add_parser("internal-notification-ack")
    native_ack.add_argument("agent")
    native_ack.add_argument("request_ids", nargs="+")
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
    install_command.add_argument(
        "--confirm-codex-sessions-closed",
        action="store_true",
        help="confirm all unmanaged Codex sessions are closed before plugin replacement",
    )
    upgrade_command = commands.add_parser(
        "upgrade",
        description=(
            "Refresh every bound adapter after a package upgrade and report "
            "which ones need a restart. Command paths pick up new package code "
            "on their next invocation; only a changed plugin generation costs a "
            "restart. A binding that fails does not stop the others, so a live "
            "Codex session blocks only its own bindings."
        ),
    )
    upgrade_command.add_argument(
        "--cli", choices=("antigravity", "claude", "codex", "python")
    )
    upgrade_command.add_argument("--project", type=Path)
    upgrade_command.add_argument(
        "--dry-run",
        action="store_true",
        help="report what each binding would do without changing anything",
    )
    upgrade_command.add_argument(
        "--confirm-codex-sessions-closed",
        action="store_true",
        help="confirm all unmanaged Codex sessions are closed before plugin replacement",
    )
    doctor_command = commands.add_parser("doctor")
    doctor_command.add_argument("agent", nargs="?")
    doctor_command.add_argument("--project", type=Path, default=Path.cwd())
    doctor_command.add_argument(
        "--cli", choices=("antigravity", "claude", "codex", "python")
    )
    uninstall_command = commands.add_parser("uninstall")
    uninstall_command.add_argument("cli", choices=("antigravity", "claude", "codex"))
    uninstall_command.add_argument("--project", type=Path, required=True)
    uninstall_command.add_argument(
        "--confirm-codex-sessions-closed",
        action="store_true",
        help="confirm all unmanaged Codex sessions are closed before plugin removal",
    )
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
            profiles = (
                project_profiles(office, args.project)
                if args.project
                else office.list_profiles()
            )
            for profile in profiles:
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
            print(
                "type\taddress\tattention\tqualified\tdisplay\tprojects\t"
                "handles\tsummary"
            )
            profiles = (
                project_profiles(office, args.project)
                if args.project
                else office.list_profiles()
            )
            for profile in profiles:
                presence = agent_presence(office, profile.name)
                qualified = ",".join(qualified_addresses(profile)) or "-"
                print(
                    f"agent\t{profile.name}\t{presence.state}\t"
                    f"{qualified}\t"
                    f"{profile.display_name}\t{','.join(profile.projects)}\t"
                    f"{','.join(profile.handles)}\t{profile.summary}"
                )
            if args.project is None:
                for name, members in sorted(office.list_groups().items()):
                    print(
                        f"group\t@{name}\t-\t-\t{name}\t-\t-\t"
                        f"{','.join(members)}"
                    )
        elif args.command == "resolve":
            _print_resolution(office, args.label, project=args.project)
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
            return _join(
                office,
                args.agent,
                args.cli,
                args.project,
                confirm_codex_sessions_closed=args.confirm_codex_sessions_closed,
            )
        elif args.command == "attach":
            profile = office.load_profile(
                _resolve_mailbox_address(office, args.agent)
            )
            thread_id = os.environ.get("CODEX_THREAD_ID", "")
            project = args.project.expanduser().resolve()
            result = attach_codex_session(
                office,
                profile.name,
                thread_id,
                project,
                allowed_agents=workspace_seats(office, project),
                explicit_agent=os.environ.get("AGENTPOST_AGENT"),
                bridge_active=os.environ.get("AGENTPOST_CODEX_BRIDGE") == "1",
            )
            installed = result.installed_generation or (
                f"unknown ({result.installed_problem})"
            )
            print(
                f"{result.state.upper()}\t{profile.name}\tcodex-session\t"
                f"{result.attachment.session_digest[:12]}"
            )
            print(
                f"DELIVERY\t{result.delivery}\t"
                f"observed-hook={result.attachment.observed_generation}\t"
                f"installed-plugin={installed}"
            )
            print(
                "PRESENCE\t"
                + (
                    "managed live bridge remains wake-capable"
                    if result.delivery == "live-bridge"
                    else "boundary-only; attach publishes no presence and cannot "
                    "wake an already-idle thread"
                )
            )
            if result.delivery != "live-bridge":
                print(
                    f"NEXT\tfor already-idle wake, relaunch with `agentpost codex "
                    f"--agent {profile.name} resume {thread_id}`"
                )
        elif args.command == "disconnect":
            if not office.unbind_agent(args.cli, args.project):
                raise ValueError(
                    f"no {args.cli} binding exists for {args.project.expanduser().resolve()}"
                )
        elif args.command == "bindings":
            for binding in office.list_bindings():
                print(f"{binding.agent}\t{binding.cli}\t{binding.project}")
        elif args.command == "status":
            if args.agent:
                names = (
                    _resolve_mailbox_address(
                        office,
                        args.agent,
                        project=args.project,
                    ),
                )
            elif args.project:
                names = tuple(
                    profile.name for profile in project_profiles(office, args.project)
                )
            else:
                names = tuple(profile.name for profile in office.list_profiles())
            for name in names:
                presence = agent_presence(office, name)
                print(f"{name}\t{presence.state}\t{presence.detail}")
        elif args.command == "wipe":
            _wipe(office, args)
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
        elif args.command == "review":
            sender = _channel_sender(office, args.sender)
            recipients = resolve_channel_recipients(
                office,
                (args.recipient,),
                sender=sender,
            )
            artifact = prepare_review(
                args.repo,
                args.commit,
                args.paths,
                args.tests,
                parent=args.parent,
            )
            rendered = render_review_request(artifact, _channel_body(args.body))
            print("REVIEW-ENVELOPE-BEGIN")
            print(rendered)
            print("REVIEW-ENVELOPE-END", flush=True)
            result = office.send_many(
                sender,
                recipients,
                rendered,
                subject=args.subject or f"Review {artifact.commit[:12]}",
                kind="question",
                notify=args.notify,
                review=artifact,
            )
            _print_channel_delivery(office, sender, recipients, result)
            _warn_unarmed(office, recipients)
        elif args.command == "notify":
            sender = _channel_sender(office, args.sender)
            recipient = resolve_identity(
                office,
                args.recipient,
                sender=sender,
            ).name
            request = office.request_notification(
                sender,
                recipient,
                args.message_id,
                notify=args.mode,
            )
            print(f"NOTIFY\t{request.message_id}")
            print(f"FROM\t{sender}")
            print(f"TO\t{recipient}\t{request.notify}")
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
            agent = _resolve_mailbox_address(
                office,
                args.agent,
                project=args.project,
            )
            for record in office.list_messages(agent, args.state):
                letter = record.letter
                print(
                    f"{letter.message_id}\t{letter.from_agent}\t"
                    f"{letter.kind}\t{letter.subject or ''}"
                )
        elif args.command == "read":
            agent = _resolve_mailbox_address(
                office,
                args.agent,
                project=args.project,
            )
            record = office.read(agent, args.message_id)
            sys.stdout.buffer.write(record.path.read_bytes())
        elif args.command == "next":
            agent = _resolve_mailbox_address(
                office,
                args.agent,
                project=args.project,
            )
            record = office.claim(agent, args.message_id)
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
            try:
                result = office.reply(
                    replier,
                    message_id,
                    _channel_body(body),
                    notify=args.notify,
                )
                recipient = office.read(
                    replier, message_id, states=("read",)
                ).letter.from_agent
            except MessageNotFoundError as exc:
                raise _mailbox_miss(office, replier, args.sender, exc) from exc
            print(result.message_id)
            _warn_unarmed(office, (recipient,))
        elif args.command == "internal-claude-boundary":
            return claude_boundary(args.state, args.delay)
        elif args.command == "internal-claude-monitor":
            return claude_monitor()
        elif args.command == "internal-codex-hook":
            return codex_hook(args.event, args.generation)
        elif args.command == "internal-antigravity-hook":
            return antigravity_hook(args.event)
        elif args.command == "internal-snapshot":
            return codex_snapshot(office, args.agent)
        elif args.command == "internal-notification-ack":
            return acknowledge_notifications(office, args.agent, args.request_ids)
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
            install(
                office,
                args.cli,
                args.agent,
                args.project,
                confirm_codex_sessions_closed=args.confirm_codex_sessions_closed,
            )
        elif args.command == "upgrade":
            results = upgrade(
                office,
                cli=args.cli,
                project=args.project,
                dry_run=args.dry_run,
                confirm_codex_sessions_closed=args.confirm_codex_sessions_closed,
            )
            if not results:
                print("agentpost: no adapter bindings match", file=sys.stderr)
                return 1
            for item in results:
                print(
                    f"{item.state.upper()}\t{item.agent}\t{item.cli}\t"
                    f"{item.project}\t{item.detail}"
                )
            restarts = sorted(
                {item.cli for item in results if item.state == "upgraded"}
            )
            if restarts:
                print(
                    f"agentpost: restart {', '.join(restarts)} to load the new "
                    "plugin generation; package-only changes are already live",
                    file=sys.stderr,
                )
            return 1 if any(item.state == "failed" for item in results) else 0
        elif args.command == "doctor":
            agent = args.agent or identify_agent(
                office,
                args.project,
                cli=args.cli,
                agent=os.environ.get("AGENTPOST_AGENT"),
            ).name
            checks = doctor(office, agent, args.project, args.cli)
            for check in checks:
                print(f"{'PASS' if check.ok else 'FAIL'}\t{check.name}\t{check.detail}")
            return 0 if all(check.ok for check in checks) else 1
        elif args.command == "uninstall":
            uninstall(
                args.cli,
                args.project,
                confirm_codex_sessions_closed=args.confirm_codex_sessions_closed,
            )
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
    supports_optional_body = args.command in {"message", "question", "review"}
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


def _mailbox_miss(
    office: PostOffice,
    replier: str,
    requested: str | None,
    exc: MessageNotFoundError,
) -> AgentPostError:
    """Name the acting seat and the rule that chose it.

    A bare miss reports only which mailbox was searched, which reads as the
    letter being absent or the recipient unreachable. Acting as the wrong seat
    is the likelier cause whenever the sender was inferred rather than stated.
    """
    if requested is not None:
        source = "explicit --from"
    elif os.environ.get("AGENTPOST_AGENT"):
        source = "explicit AGENTPOST_AGENT"
    else:
        try:
            identified, source = identify_agent_source(office, Path.cwd())
            if identified.name != replier:
                source = "holding the letter in this workspace"
        except (AgentPostError, ValueError):
            source = "inferred identity"
    return AgentPostError(
        f"{exc}; this command acted as {replier} by {source}. If the letter "
        f"was addressed to a different seat in this workspace, run it from "
        f"that seat's managed launcher or pass --from NAME."
    )


def _channel_sender(office: PostOffice, requested: str | None) -> str:
    if requested is not None:
        try:
            acting = identify_agent(
                office,
                Path.cwd(),
                agent=os.environ.get("AGENTPOST_AGENT"),
            ).name
        except (AgentPostError, OSError, ValueError):
            acting = None
        return _resolve_mailbox_address(
            office,
            requested,
            sender=acting,
        )
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
    if requested_sender is None and not os.environ.get("AGENTPOST_AGENT"):
        sender = _reply_seat(office, sender, parts[0])
    return sender, parts[0], parts[1] if len(parts) == 2 else None


def _reply_seat(office: PostOffice, inferred: str, message_id: str) -> str:
    """Answer from the seat that actually holds the letter.

    Workspace inference names one default mailbox, but a notification may be
    addressed to an alternate seat sharing the project root. Searching only
    the default reports such a letter as missing, when the real condition is
    that the runtime is answering from the wrong seat. Holding the letter is
    the deterministic signal; inference stays the tiebreak.
    """
    if _holds_letter(office, inferred, message_id):
        return inferred
    holders = [
        name
        for name in workspace_seats(office, Path.cwd())
        if name != inferred and _holds_letter(office, name, message_id)
    ]
    if len(holders) > 1:
        names = ", ".join(sorted(holders))
        raise AgentPostError(
            f"{message_id} is addressed to more than one seat in this "
            f"workspace: {names}; pass --from NAME to choose the sender"
        )
    return holders[0] if holders else inferred


def _holds_letter(office: PostOffice, agent: str, message_id: str) -> bool:
    try:
        office.read(agent, message_id)
    except (AgentPostError, ValueError):
        return False
    return True


def _print_resolution(
    office: PostOffice,
    label: str,
    *,
    project: str | None = None,
) -> None:
    groups = office.list_groups()
    name = resolve_group(office, label)
    if name is not None:
        if project is not None:
            raise ValueError(
                "groups are global addresses and cannot be combined with --project; "
                "use @GROUP explicitly"
            )
        if not label.startswith("@"):
            try:
                identity = office.load_profile(
                    _resolve_mailbox_address(office, label)
                )
            except AgentPostError:
                identity = None
            if identity is not None:
                raise ValueError(
                    f"ambiguous AgentPost address {label!r}: "
                    f"agent {identity.name} or group @{name}"
                )
        print(f"group\t@{name}\t{','.join(groups[name])}")
        return
    profile = office.load_profile(
        _resolve_mailbox_address(
            office,
            label,
            project=project,
        )
    )
    presence = agent_presence(office, profile.name)
    qualified = ",".join(qualified_addresses(profile)) or "-"
    print(
        f"agent\t{profile.name}\t{presence.state}\t{qualified}\t"
        f"{profile.display_name}"
    )


def _resolve_mailbox_address(
    office: PostOffice,
    label: str,
    *,
    project: str | None = None,
    sender: str | None = None,
) -> str:
    if project is not None or "." in label:
        return resolve_identity(
            office,
            label,
            project=project,
            sender=sender,
        ).name
    if sender is None:
        try:
            sender = identify_agent(
                office,
                Path.cwd(),
                agent=os.environ.get("AGENTPOST_AGENT"),
            ).name
        except (AgentPostError, OSError, ValueError):
            sender = None
    if sender is not None:
        return resolve_identity(office, label, sender=sender).name
    known = {profile.name for profile in office.list_profiles()}
    if label in known:
        return office.load_profile(label).name
    raise UnknownAgentError(
        f"unqualified AgentPost address {label!r} has no project context; "
        "use PROJECT.SEAT, --project PROJECT, or a canonical mailbox key"
    )


def _wipe(office: PostOffice, args: argparse.Namespace) -> None:
    with office._locked_mailbox_namespace():
        _wipe_locked(office, args)


def _wipe_locked(office: PostOffice, args: argparse.Namespace) -> None:
    try:
        acting = identify_agent(
            office,
            Path.cwd(),
            agent=os.environ.get("AGENTPOST_AGENT"),
        ).name
    except (AgentPostError, OSError, ValueError):
        acting = None

    missing_project_error = None
    if args.wipe_scope == "agent":
        if args.agent is None:
            if acting is None:
                raise UnknownAgentError(
                    "cannot infer this agent; name the mailbox to wipe"
                )
            targets = (acting,)
        else:
            targets = (
                _resolve_mailbox_address(
                    office,
                    args.agent,
                    sender=acting,
                ),
            )
        label = f"agent {targets[0]}"
        confirmation_required = acting != targets[0]
    elif args.wipe_scope == "project":
        try:
            targets = tuple(
                profile.name for profile in project_profiles(office, args.project)
            )
        except UnknownAgentError as exc:
            targets = ()
            missing_project_error = exc
        label = f"project {args.project}"
        confirmation_required = True
    else:
        targets = tuple(profile.name for profile in office.list_profiles())
        label = "all agents"
        confirmation_required = bool(targets)

    expected = ",".join(sorted(targets))
    if args.confirm is not None and args.confirm != expected:
        raise AgentPostError(
            f"wipe confirmation does not match the current affected mailboxes. "
            f"Affected mailboxes: {expected or '(none)'}"
        )
    if missing_project_error is not None:
        raise missing_project_error
    if confirmation_required and args.confirm != expected:
        raise AgentPostError(
            f"confirmation required before wiping {label}. Affected mailboxes: "
            f"{expected}. Ask the user to confirm this exact list, then rerun "
            f"with `--confirm '{expected}'`."
        )
    if not targets:
        if args.wipe_scope == "all":
            office._wipe_agents_locked((), purge_all_attachments=True)
        print(f"WIPED\t{args.wipe_scope}\t-")
        print("RECOVERY\tnothing was deleted")
        return

    fences = []
    try:
        for name in sorted(targets):
            fence = ConsumerLease(
                office,
                name,
                "wipe-fence",
                cwd=args.project if args.wipe_scope == "project" else Path.cwd(),
            )
            if not fence.acquire():
                owner = fence.current_owner()
                detail = (
                    f"{owner.get('adapter', 'unknown')} pid "
                    f"{owner.get('pid', '?')} instance "
                    f"{owner.get('instance_id', '?')}"
                    if owner
                    else "another live instance"
                )
                raise AgentPostError(
                    f"stop the live mailbox consumer for {name} before wiping: "
                    f"{detail}"
                )
            fences.append(fence)
        removed = office._wipe_agents_locked(
            targets,
            purge_all_attachments=args.wipe_scope == "all",
        )
    finally:
        for fence in reversed(fences):
            fence.release()
    print(f"WIPED\t{args.wipe_scope}\t{','.join(removed)}")
    print(
        "RECOVERY\tirreversible; copies held by unaffected mailboxes were not removed"
    )


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
    *,
    confirm_codex_sessions_closed: bool = False,
) -> int:
    project = project.expanduser().resolve()
    agent = requested_agent or _infer_join_agent(office, project, requested_cli)
    profile = office.load_profile(agent)
    cli = _join_cli(office, agent, project, requested_cli, profile.cli)
    if cli == "python":
        office.bind_agent(agent, cli, project)
    else:
        install(
            office,
            cli,
            agent,
            project,
            confirm_codex_sessions_closed=confirm_codex_sessions_closed,
        )
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
    # An unbound profile has no adapter to start, so promising a next adapter
    # start names a delivery path that does not exist. Bindings are the only
    # truth here: the presence detail folds profile.cli into its connected
    # adapters and reports one even when nothing is bound.
    bound = {binding.agent for binding in office.list_bindings()}
    for recipient in recipients:
        is_armed, detail = armed(office, recipient)
        if not is_armed:
            if "no live mailbox consumer" not in detail:
                disposition = (
                    "live wake unavailable; queued for the next supported boundary"
                )
            elif recipient in bound:
                disposition = "recipient offline; queued for its next adapter start"
            else:
                disposition = (
                    "recipient has no connected adapter; mail is durable but "
                    "nothing will deliver it until the mailbox is connected "
                    "with agentpost join or started by a named launcher"
                )
            print(
                f"agentpost: delivered to {recipient}; {disposition}",
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
