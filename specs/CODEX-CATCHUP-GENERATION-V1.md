# CODEX-CATCHUP-GENERATION-V1

**Status:** Implemented after live Codex acceptance and final Kernos GREEN
**Scope:** Codex lifecycle catch-up and integration-generation truth
**Evidence:** Live Cx remote-control failure on 2026-07-10
**Review:** Kernos implementation verdict GREEN on 2026-07-10

## Problem

AgentPost delivered PB message
`<de90f92f-2fd3-4adf-9500-350bfad6f3bd@agentpost.local>` durably to
`cx/unread`, but the active Cx remote-control thread did not surface it.

The failure had two causes:

1. The Codex fallback plugin checks mail only at `SessionStart` and `Stop`.
   Mail arriving while a long-lived thread is idle is therefore invisible
   until that thread completes another turn.
2. The running Codex app server retained hook generation
   `0.0.1+codex.20260710040154` while installation advanced to
   `0.0.1+codex.20260710085539` and removed the old cache directory. Static
   `doctor` still returned PASS because it checked only configuration, trust,
   and Node availability. The active turn loaded neither the current
   AgentPost skill nor a runnable current-generation hook.

Delivery remained safe, but notification health was reported incompletely.

## Invariants

1. Waiting and health checks use no model call and no LLM judgment.
2. Hooks and adapters surface Message-ID pointers but never claim mail.
3. `agentpost next AGENT --message-id ID` remains the only work-start claim.
4. One mailbox-wide consumer lease remains authoritative across adapters.
5. A lifecycle observation is not presence. Only a fresh live bridge or
   monitor heartbeat may report `idle` or `working` and `wake_capable=true`.
6. Durable delivery succeeds even when every notifier is stale or absent.
7. No timer may invoke Codex merely because time passed. A model turn may begin
   only for a real user prompt or real unread AgentPost mail.

## Decision 1: check before every Codex user turn

Codex 0.144.1 supports `UserPromptSubmit` generally but does not discover that
event from an enabled plugin's default `hooks/hooks.json`: live `/hooks`
reported plugin `SessionStart` and `Stop` as installed and
`UserPromptSubmit` as `0 installed`. AgentPost therefore uses two owned hook
surfaces that call the same deterministic Python hook:

- the plugin bundles `SessionStart` and `Stop`;
- the installer structurally merges one stable AgentPost `UserPromptSubmit`
  group into `~/.codex/hooks.json` without replacing unrelated hooks.

- `SessionStart` injects unread Message-IDs as additional context.
- `UserPromptSubmit` injects unread Message-IDs as additional context before
  the already-requested model turn.
- `Stop` preserves the existing one-continuation behavior for mail that arrived
  during a turn.

The hook performs filesystem reads, identity resolution, and an ephemeral
consumer-lease attempt only. It never starts a separate model request. The
existing `agentpost codex` bridge remains responsible for true already-idle
wake, immediate steering, and idle deferral.

This is intentionally an event hook, not a polling conversation. A separate
resident AgentPost daemon or systemd timer is not introduced.

## Decision 2: stamp the generation that actually ran

All three dispatcher commands are stable across upgrades:

```text
agentpost internal-codex-hook EVENT
```

The installed AgentPost runtime supplies a build-time Codex generation
constant that tests require to equal the bundled plugin manifest version. This
keeps every trust hash stable while still recording the exact code generation
that executed. An already-loaded stable dispatcher calls upgraded deterministic
runtime code without a model turn. A process old enough not to have loaded the
new user prompt hook remains `unobserved` until reload.

Immediately after resolving the agent identity, the hook atomically writes:

```json
{
  "adapter": "codex-hook",
  "generation": "0.0.3+codex.YYYYMMDDHHMMSS",
  "event": "user-prompt-submit",
  "observed_at": 1783720000.0,
  "session_id": "019...",
  "cwd": "/work/project"
}
```

to an event-specific marker under
`agents/AGENT/adapter/codex-hooks/EVENT.json`.

The write is unconditional for a valid AgentPost identity and occurs before
the `AGENTPOST_CODEX_BRIDGE` short-circuit, live-bridge marker check, and
consumer-lease attempt. Those gates suppress duplicate mail injection only;
they never suppress lifecycle observation. A managed bridge can therefore
continue to own the mailbox while hook generation truth remains observable.

Markers are event-specific so a current prompt hook cannot hide a stale plugin
`Stop` hook from an old process. Each means only "this generation executed at
this boundary." They are not heartbeats, do not own the mailbox between
events, and must never make the agent appear online.

## Decision 3: compare observed and installed generations

AgentPost discovers the installed Codex generation from the enabled
`agentpost@agentpost-local` plugin cache manifest. Exactly one enabled cache
generation must resolve to a readable `.codex-plugin/plugin.json`; zero,
multiple, missing, or malformed candidates classify the installed generation
as `unknown` rather than selecting by timestamp or directory order.
Diagnostics classify the result as:

- `current`: all three event markers equal the installed generation;
- `stale`: any observed event generation differs from installed generation;
- `unobserved`: installed generation exists but one or more required events
  have not executed;
- `unknown`: installed cache state is missing or ambiguous.

`agentpost doctor AGENT --project PATH --cli codex` adds a generation check:

- PASS only for `current`;
- FAIL for `stale`, `unobserved`, or `unknown` with concrete re-trust and
  reload actions.

Codex hook trust becomes `3/3`, covering `SessionStart`, `UserPromptSubmit`, and
`Stop`.

Sender-side unarmed warnings and `agentpost armed AGENT` append stale or
unobserved generation detail, but remain `QUEUED` unless a real live bridge
heartbeat exists.

No process-start-time heuristic is used as the source of truth. It may explain
a stale observation, but only an executed generation stamp proves which plugin
code a thread actually ran.

## Decision 4: installation makes the reload boundary explicit

Codex installation or upgrade refreshes the plugin and idempotently merges the
stable user-level prompt hook. Codex currently has no supported non-interactive
API to grant or renew hook trust, and live remove/add did not renew changed
plugin hook hashes. AgentPost therefore does not synthesize private
`trusted_hash` state. On first install only, it tells the user to approve all
three stable AgentPost hooks in `/hooks`; unchanged commands preserve those
approvals across later generation bumps. Doctor remains FAIL until all three
are approved.

Installation also prints that already-running Codex processes must reload.
Static plugin presence and renewed on-disk trust are not described as
successful runtime arming. Doctor remediation names the applicable actions in
order: approve the stable hooks if trust is incomplete, refresh the plugin if
its cache is stale, then reload only when required events remain unobserved.
All three generation markers become current after the first submitted turn
completes.

Old generation markers remain useful evidence until replaced. Uninstall
removes the plugin and only AgentPost's handler/group from the user hook file,
preserving unrelated hooks as well as AgentPost mail, profiles, bindings, and
history.

## Acceptance oracles

1. Plugin manifest contains stable `SessionStart` and `Stop` commands; the user
   hook contains one stable `UserPromptSubmit` command; the runtime generation
   constant equals `.codex-plugin/plugin.json`.
2. `UserPromptSubmit` with unread mail emits exact Message-ID context and does
   not move the letter out of `unread`.
3. `UserPromptSubmit` with no unread mail emits the empty hook response.
4. A live managed bridge suppresses all fallback hook injections as before,
   but the suppressed hook still records its generation marker.
5. Every hook event records its own generation marker even when no mail exists
   or the consumer lease is held elsewhere.
6. Doctor passes static plugin/trust checks but fails generation when any
   observed event generation differs from the installed manifest.
7. Zero or multiple enabled cache generations report `unknown`; no candidate
   is selected by recency.
8. Doctor reports unobserved after fresh install and passes after all three
   current-generation events execute.
9. First install fails trust until all three stable hooks are approved. A
   generation bump preserves all three trusted hashes without private config
   writes or another approval.
10. An old app server whose old cache directory was removed reports generation
    FAIL while static plugin and trust checks for the new install still PASS.
11. `armed` remains false for lifecycle-only Codex while explaining stale or
   unobserved generation state.
12. Full tests, compilation, bundled-integration rendering, and clean-wheel
   installation pass.
13. Live acceptance: `/hooks` reports all three events installed and active;
    install the new cache generation, reload the Codex remote app server,
    submit and complete a prompt, and observe three current-generation markers.
    An exact idle letter is surfaced at the next submitted turn without a
    separate polling/model loop.

## Non-goals

- No mail claiming from hooks or adapters.
- No duplicate consumer, resident AgentPost daemon, systemd timer, or terminal
  keystroke injection.
- No claim of already-idle immediate wake for ordinary Codex launches.
- No automatic killing or restarting of a user's Codex process.
- No inference that a historical hook marker means the agent is online.
- No cross-adapter generation schema in this change; the marker shape is chosen
  so Claude and Antigravity can adopt it later.
