# Founder Acceptance Checklist

Last updated: 2026-07-11

This is the single manual release checklist for the local K/PB/C/Cx deployment.
Automated tests remain the agents' responsibility. Check a manual item only
after observing its stated result; record Message-IDs for mail-flow evidence.

## Automated evidence already complete

- [x] AgentPost 0.0.11 includes the managed Codex bridge startup correction
  and the Claude monitor startup correction;
  the earlier 0.0.9 generation-truth release is recorded at `69fa7db`.
- [x] The full Python suite passes: 112 tests.
- [x] The suite also passes with unrelated `AGENTPOST_AGENT` and
  `AGENTPOST_ROOT` values inherited from another connected shell.
- [x] A clean 0.0.11 wheel install materializes Claude plugin 0.0.5 plus the
  Codex and Antigravity integrations and passes the executable two-agent smoke.
- [x] Codex reports all three stable AgentPost hooks trusted; reinstalling the
  same dispatchers preserves `3/3` trust.
- [x] Isolated Codex acceptance observed current `SessionStart`,
  `UserPromptSubmit`, and `Stop` generation markers without claiming mail.
- [x] Kernos independently returned full-diff GREEN, then focused GREEN after
  both review notes were implemented; its final independent run passed all 112
  tests.
- [x] Automated cold-start coverage queues mail with zero consumers, rotates
  K, PB, C, and Cx through every first-member position, permits all four
  mailbox-local leases concurrently, and verifies non-claiming catch-up.

## Agent-owned closeout

These are not founder manual tests. Release closeout remains open until the
agents record them complete in `IMPLEMENTATION_STATUS.md`.

- [ ] Automate the clean-install matrix for available Python 3.11, 3.12, and
  3.13 environments rather than relying only on the completed manual wheel
  check.
- [ ] Prove partial-install and uninstall rollback: remove only AgentPost-owned
  integration state while preserving unrelated hooks/configuration, profiles,
  bindings, unread mail, read history, and sent history.
- [x] Reload the long-lived K, PB, and Construct Claude sessions onto the
  current plugin, then record restart catch-up, immediate delivery, and idle
  deferral for each.

## 1. Cx reconnect and generation truth

Completed 2026-07-10. The first founder probe found the integration already
past the former `unobserved` precondition: all three current-generation events
had executed.

- [x] End the old remote Codex process and reconnect Cx from
  `/home/k/agentpost`.
- [x] Confirm exactly three enabled AgentPost hooks are trusted:
  `SessionStart`, `UserPromptSubmit`, and `Stop`.
- [x] Submit one ordinary prompt and allow the response to complete.
- [x] Run:

  ```sh
  agentpost doctor cx --project /home/k/agentpost --cli codex
  ```

  Pass: every check reports `PASS`, and `codex-generation` says all three hooks
  observed installed generation `0.0.3+codex.20260710221500`.

Evidence/date: 2026-07-10 — founder-provided `doctor` output reported every
check `PASS`, `codex-hook-trust` at `3/3`, and all three hooks observing
installed generation `0.0.3+codex.20260710221500`.

## 2. Ordinary Codex next-prompt catch-up

- [x] Leave a freshly reconnected ordinary Codex session idle, without the
  managed `agentpost codex` launcher.
- [x] From K, PB, or Construct, send one uniquely worded AgentPost question to
  Cx and retain its Message-ID.
- [x] Confirm delivery alone does not start a model turn while Cx is idle.
- [x] Submit a user prompt in Cx after delivery.
- [x] Confirm the exact unread Message-ID is surfaced before that requested
  turn, then claim only that letter, answer it by `In-Reply-To`, and provide a
  short synopsis in the user chat.
- [x] Confirm the letter remains unread until the explicit claim; the hook
  itself must not move it.

Message-ID/result: 2026-07-10 — question
`<df69caa1-4120-4d66-affe-2d8018be7fa2@agentpost.local>` queued without a
turn. `UserPromptSubmit` generation `0.0.3+codex.20260710221500` then executed;
two pre-claim listings around a side-effect-free `read` both showed the letter
unread. Cx explicitly claimed it and sent correlated answer
`<3d682f96-4272-43c5-b1b3-8d3ceb4cc7ac@agentpost.local>`. The Cx unread tray
was empty afterward.

## 3. Managed Codex attention modes

### CLI-neutral contract and adapter-specific evidence

Every adapter test must preserve the same durable semantics: delivery succeeds
while closed, native notification names exact IDs without claiming them,
`immediate` interrupts only at that adapter's documented safe boundary, `idle`
waits for completion, one consumer claims each letter once, replies correlate,
and shutdown releases mailbox ownership. Waiting and notification checks are
token-free; a legitimately started or steered model turn has normal model usage.

Fresh-load evidence differs by runtime:

| Runtime | Required fresh-load observation |
| --- | --- |
| Claude Code | Project-local current plugin starts a monitor, becomes `ARMED`, and emits queued exact IDs before any user prompt. |
| Managed Codex | Launcher starts its bridge, becomes `ARMED`, and uses `turn/start` or `turn/steer` for the documented attention mode. |
| Ordinary Codex | Current lifecycle hooks inject queued IDs at startup or the next prompt; already-idle wake is not claimed. |
| Antigravity | Current plugin injects queued IDs at the first `PreInvocation`; already-idle wake is not claimed. |
| Embedded Python | Runtime starts its watcher; its host scheduler supplies the turn boundary and wake policy. |

Launch from `/home/k/agentpost`:

```sh
agentpost codex --agent cx
```

Bridge startup evidence: 2026-07-10 — after the 0.0.10 fresh-install fix,
`agentpost armed cx` reported `ARMED` with bridge pid 135853 and instance
`d3ba30f6`.

- [x] **Idle mail while idle:** send one `--notify idle` question. Pass: one
  new turn starts after the idle boundary and processes the exact Message-ID.
- [x] **Immediate mail during a turn:** while Cx is visibly working, send one
  `--notify immediate` question. Pass: it steers the active turn once; no
  duplicate follow-up turn starts for the same letter.
- [x] **Idle mail during a turn:** while Cx is working, send one `--notify idle`
  question. Pass: it does not interrupt; one turn starts after completion.
- [ ] Exit the launcher. Pass: child processes and the live bridge marker are
  removed, and `agentpost armed cx` returns `QUEUED` rather than claiming a
  live consumer remains.

Message-IDs/results: 2026-07-10 — idle question
`<fbd7f61c-496c-47b3-a8aa-488d23a0d3c4@agentpost.local>` automatically
started a turn without a user prompt; Cx claimed that exact Message-ID and sent
correlated answer `<3c753249-984d-4859-a02c-10d53ca800fb@agentpost.local>`.
Immediate question `<e8316bcb-039e-4e78-aa48-6a351c1c1cdd@agentpost.local>`
produced exactly one bridge `steered` event on the existing turn and correlated
answer `<0be9931c-9363-4417-b4c5-7ece80f3a86e@agentpost.local>`. Idle-deferral
question `<8b2c3e39-6417-4681-97e3-8ad161958937@agentpost.local>` was delivered
during that active turn, produced one `deferred-idle` bridge event, and then
appeared in one post-completion `turn-start-request`; correlated answer
`<03c7aa78-1f6c-4c5a-b3b8-d1327053ca20@agentpost.local>` completed the test.

## 4. Claude agents K, PB, and Construct

For each agent, reload its project session and run its doctor command:

```sh
agentpost doctor k  --project /home/k/Kernos         --cli claude
agentpost doctor pb --project /home/k/pattern-buffer --cli claude
agentpost doctor c  --project /home/k/Newproject     --cli claude
```

- [x] All three doctors pass identity, mailbox, project, and current 0.0.5
  project-local plugin checks.
- [x] Each agent receives one exact-ID restart catch-up letter.
- [x] Each agent receives one immediate letter while working without losing
  its current task.
- [x] Each agent defers one idle letter until its current turn completes.
- [x] No test letter is processed twice, and every response correlates to the
  original Message-ID.

Queued fresh-load IDs:

- K: `<5f2c3184-c281-4409-819d-8131e6c16ddc@agentpost.local>`
- PB: `<d2a83dbd-8c9d-49ea-858e-3e53f94b7831@agentpost.local>`
- C: `<ff9969e6-a693-47a3-b02c-29f053cf46ec@agentpost.local>`

K evidence: fresh plugin 0.0.5 monitor became `ARMED` as pid 153120, started a
turn before any user prompt, and surfaced the exact notification set including
probe `<5f2c3184-c281-4409-819d-8131e6c16ddc@agentpost.local>`. K claimed only
the listed IDs and returned correlated answer
`<52bf00b1-317e-4bf0-bc00-55db41903960@agentpost.local>`. Active-window probe
`<4b566aa5-41eb-481b-89d5-df7395ad74f3@agentpost.local>` held a 15-second turn;
immediate probe `<fe83c197-7d6b-4ab7-b6bd-4a8590e4a1a7@agentpost.local>` was
answered in that same turn by
`<f33940f7-07ad-4330-9062-af80dfb0dd92@agentpost.local>`, while idle probe
`<87bc0904-bafb-493d-9de3-8c1c80cb255d@agentpost.local>` waited for a fresh
follow-up turn and answer
`<e854581a-5d19-4abe-b27e-822cff82545b@agentpost.local>`.

PB evidence: the original queued probe was consumed by the explicitly
deprecated interim shell watcher in PB's old long-lived session, not by the
native plugin. PB reported that distinction in correlated answer
`<84173a3b-167f-414a-8e67-2f05f0edb00c@agentpost.local>`. The shell watcher was
restarted once by that old session and intercepted the first successor as well;
both are invalidated fixture evidence. After the old session exited, fresh
plugin 0.0.5 monitor pid 155352 became `ARMED` and idle. It woke before any user
prompt for final probe
`<2cf946ee-f66e-42ff-9f9c-5ed8b7f44cfc@agentpost.local>`, claimed that exact ID
once, and sent correlated answer
`<8950ac72-ad0a-4d35-b4f6-3ea9a63b3d72@agentpost.local>`. Active-window probe
`<9a256182-ffc5-4ed4-8705-7c67a52136a9@agentpost.local>` held a 15-second turn;
immediate probe `<aa18d741-a4ff-4e11-b3a4-921f9446e9e6@agentpost.local>` was
answered during it by
`<e2b2317e-c804-4b22-9886-d5cc3df7058a@agentpost.local>`, while idle probe
`<cc490d7b-35ae-4392-98aa-21b5be996e23@agentpost.local>` waited until completion
and answer `<626071b5-e0fd-4b25-99de-225366fd352d@agentpost.local>`.

C evidence: fresh plugin 0.0.5 native monitor woke before any user prompt and
surfaced an exact notification set containing probe
`<ff9969e6-a693-47a3-b02c-29f053cf46ec@agentpost.local>`. C processed that set
first and sent correlated answer
`<74bb7358-152b-4644-b117-e76e77f58b60@agentpost.local>`. Immediate probe
`<b959c4cb-93aa-4090-985b-892b2441b84d@agentpost.local>` entered C's existing
real-work turn and produced correlated answer
`<b52244bc-b114-482a-98c1-d5c9f7fdab43@agentpost.local>`. Idle probe
`<824d6a3e-d608-4bef-84bc-8b49492ad72c@agentpost.local>` did not interrupt
that real-work turn; it arrived batched at the next Monitor wake after the
active turn completed and produced correlated answer
`<63257da5-9bd8-41dd-bc25-9df6ded6f4e5@agentpost.local>`.

## 4A. Antigravity adapter

- [x] Fresh install/doctor passes CLI 1.1.1 and plugin checks.
- [x] A queued letter is injected at the first fresh-load `PreInvocation`
  without claiming it in the hook.
- [x] The Antigravity agent claims the exact ID once and sends a correlated
  reply.
- [x] Already-idle external wake remains explicitly unsupported rather than
  being reported as armed.

Evidence: question `<9e6419e7-0478-48ac-94ee-d0c8c3a3d05a@agentpost.local>`
was injected at `PreInvocation`; correlated answer
`<822b7040-31bc-4e11-a6a2-d9bab819f061@agentpost.local>` confirmed that
boundary. The later CLI quota message did not invalidate the completed,
durably correlated lifecycle exchange.

## 5. Durable offline delivery

- [ ] Stop one recipient so `agentpost armed RECIPIENT` reports `QUEUED`.
- [ ] Send one uniquely worded question. Pass: delivery succeeds with a queued
  warning and the Message-ID exists in the recipient's `unread` directory.
- [ ] Restart the recipient. Pass: the exact existing Message-ID is surfaced;
  no resend or fallback copy is required.
- [ ] Inspect with `list` and `read`. Pass: both are side-effect-free.
- [ ] Claim with `next --message-id`. Pass: exactly that letter moves from
  `unread` to `read`, then a correlated reply reaches the sender.

Message-ID/result: __________________________

## 6. Round-robin completion

- [ ] K -> PB -> C -> Cx -> K each sends one short question through AgentPost.
- [ ] Every receiver reports a short synopsis in its active user chat when the
  letter is processed.
- [ ] `agentpost list AGENT` is empty for all four agents after the test.
- [ ] No actionable copy appears in any retired legacy inbox.
- [ ] `agentpost status` and `agentpost armed AGENT` describe actual live or
  queued capability without treating historical lifecycle markers as presence.

Message-IDs/results: ________________________

## 7. Zero-agent and first-member independence

For each first member in the order K, PB, C, then Cx:

- [ ] Close all four agent processes. Pass: `agentpost status` reports every
  member offline, while `agentpost identities`, `list`, `read`, and durable
  delivery still work without a daemon or coordinator.
- [ ] Send one uniquely identified letter to the selected first member while
  all members are closed. Pass: it commits to that mailbox with a queued
  receipt.
- [ ] Start only the selected member through its installed adapter. Pass: that
  member becomes armed (or lifecycle-attached where the adapter honestly lacks
  wake capability) and surfaces its exact queued Message-ID without requiring
  any named peer to be online.
- [ ] Stop that member before testing the next first-member case. Pass: no
  stale presence or global owner prevents the next member from attaching.

K-first evidence: ___________________________

PB-first evidence: __________________________

C-first evidence: ___________________________

Cx-first evidence: __________________________

## Final release gate

- [ ] Every founder test above is checked with evidence.
- [ ] Every agent-owned closeout item is recorded complete.
- [ ] `agentpost doctor` passes for each connected adapter.
- [ ] All mailboxes are drained or contain only explicitly deferred work.
- [ ] `main` is clean and matches `origin/main`.

Only after all five final-gate checks pass is AgentPost local deployment
acceptance complete.
