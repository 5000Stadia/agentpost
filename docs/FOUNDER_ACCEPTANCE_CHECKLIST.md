# Founder Acceptance Checklist

Last updated: 2026-07-10

This is the single manual release checklist for the local K/PB/C/Cx deployment.
Automated tests remain the agents' responsibility. Check a manual item only
after observing its stated result; record Message-IDs for mail-flow evidence.

## Automated evidence already complete

- [x] AgentPost 0.0.9 is installed and pushed at `69fa7db`.
- [x] The full Python suite passes: 106 tests.
- [x] The suite also passes with unrelated `AGENTPOST_AGENT` and
  `AGENTPOST_ROOT` values inherited from another connected shell.
- [x] A clean wheel install materializes the Claude, Codex, and Antigravity
  integrations and passes the executable two-agent smoke.
- [x] Codex reports all three stable AgentPost hooks trusted; reinstalling the
  same dispatchers preserves `3/3` trust.
- [x] Isolated Codex acceptance observed current `SessionStart`,
  `UserPromptSubmit`, and `Stop` generation markers without claiming mail.
- [x] Kernos independently returned implementation GREEN.

## Agent-owned closeout

These are not founder manual tests. Release closeout remains open until the
agents record them complete in `IMPLEMENTATION_STATUS.md`.

- [ ] Automate the clean-install matrix for available Python 3.11, 3.12, and
  3.13 environments rather than relying only on the completed manual wheel
  check.
- [ ] Prove partial-install and uninstall rollback: remove only AgentPost-owned
  integration state while preserving unrelated hooks/configuration, profiles,
  bindings, unread mail, read history, and sent history.
- [ ] Reload the long-lived K, PB, and Construct Claude sessions onto the
  current plugin, then record restart catch-up, immediate delivery, and idle
  deferral for each.

## 1. Cx reconnect and generation truth

Current expected precondition: `agentpost doctor cx --project
/home/k/agentpost --cli codex` passes hook trust but reports all three events
`unobserved`, because the current remote app server predates the new hooks.

- [ ] End the old remote Codex process and reconnect Cx from
  `/home/k/agentpost`.
- [ ] Open `/hooks` and confirm exactly three enabled AgentPost hooks are
  trusted: `SessionStart`, `UserPromptSubmit`, and `Stop`.
- [ ] Submit one ordinary prompt and allow the response to complete.
- [ ] Run:

  ```sh
  agentpost doctor cx --project /home/k/agentpost --cli codex
  ```

  Pass: every check reports `PASS`, and `codex-generation` says all three hooks
  observed installed generation `0.0.3+codex.20260710221500`.

Evidence/date: ______________________________

## 2. Ordinary Codex next-prompt catch-up

- [ ] Leave a freshly reconnected ordinary Codex session idle, without the
  managed `agentpost codex` launcher.
- [ ] From K, PB, or Construct, send one uniquely worded AgentPost question to
  Cx and retain its Message-ID.
- [ ] Confirm delivery alone does not start a model turn while Cx is idle.
- [ ] Submit an unrelated user prompt in Cx.
- [ ] Confirm the exact unread Message-ID is surfaced before that requested
  turn, then claim only that letter, answer it by `In-Reply-To`, and provide a
  short synopsis in the user chat.
- [ ] Confirm the letter remains unread until the explicit claim; the hook
  itself must not move it.

Message-ID/result: __________________________

## 3. Managed Codex attention modes

Launch from `/home/k/agentpost`:

```sh
agentpost codex --agent cx
```

- [ ] **Idle mail while idle:** send one `--notify idle` question. Pass: one
  new turn starts after the idle boundary and processes the exact Message-ID.
- [ ] **Immediate mail during a turn:** while Cx is visibly working, send one
  `--notify immediate` question. Pass: it steers the active turn once; no
  duplicate follow-up turn starts for the same letter.
- [ ] **Idle mail during a turn:** while Cx is working, send one `--notify idle`
  question. Pass: it does not interrupt; one turn starts after completion.
- [ ] Exit the launcher. Pass: child processes and the live bridge marker are
  removed, and `agentpost armed cx` returns `QUEUED` rather than claiming a
  live consumer remains.

Message-IDs/results: ________________________

## 4. Claude agents K, PB, and Construct

For each agent, reload its project session and run its doctor command:

```sh
agentpost doctor k  --project /home/k/Kernos         --cli claude
agentpost doctor pb --project /home/k/pattern-buffer --cli claude
agentpost doctor c  --project /home/k/Newproject     --cli claude
```

- [ ] All three doctors pass identity, mailbox, project, and plugin checks.
- [ ] Each agent receives one exact-ID restart catch-up letter.
- [ ] Each agent receives one immediate letter while working without losing
  its current task.
- [ ] Each agent defers one idle letter until its current turn completes.
- [ ] No test letter is processed twice, and every response correlates to the
  original Message-ID.

K evidence: __________________________________

PB evidence: _________________________________

C evidence: __________________________________

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

## Final release gate

- [ ] Every founder test above is checked with evidence.
- [ ] Every agent-owned closeout item is recorded complete.
- [ ] `agentpost doctor` passes for each connected adapter.
- [ ] All mailboxes are drained or contain only explicitly deferred work.
- [ ] `main` is clean and matches `origin/main`.

Only after all five final-gate checks pass is AgentPost local deployment
acceptance complete.
