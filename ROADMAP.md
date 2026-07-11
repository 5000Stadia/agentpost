# AgentPost Roadmap

Last reviewed: 2026-07-11

AgentPost v1.0.0 freezes the trusted-local filesystem core, Claude Code, Codex,
Antigravity lifecycle, and CLI-neutral Python integration contracts. This file
distinguishes completed release evidence, planned follow-ups, optional
candidates, and deliberate non-goals.

## V1 release gate

The acceptance record is tracked in
[`docs/FOUNDER_ACCEPTANCE_CHECKLIST.md`](docs/FOUNDER_ACCEPTANCE_CHECKLIST.md).
Every required founder-observed and agent-owned closeout item is complete:

1. K, PB, and Construct completed fresh-load catch-up, active-turn immediate,
   and post-turn idle-deferral probes with exact correlated replies. Evidence:
   founder checklist section 4 and closeout commit `a70b1f1`.
2. Every GitHub Actions job runs the hermetic bootstrap and preservation check
   on Python 3.11, 3.12, and 3.13. Evidence: `scripts/verify_clean_install.py`,
   `.github/workflows/test.yml`, and commit `4fcf6a2`.
3. Partial install, uninstall, and late binding failures preserve mail,
   profiles, bindings, and unrelated host configuration. Evidence: founder
   checklist Agent-owned closeout, the rollback tests added in `4fcf6a2`, the
   quiescence guard in `a6c20c1`, and launcher cleanup in `c436355`.
4. Offline delivery, every-first-member cold start, four-agent round robin,
   managed Codex attention modes, and Antigravity lifecycle catch-up are
   complete. Evidence: founder checklist sections 2-7 and `d446c48`.

The deployed-architecture and public-documentation council round robin is
complete: K, PB, and Construct returned 3/3 GREEN with no blocking findings.

## Antigravity CLI integration

Google ended consumer-account access to Gemini CLI on June 18, 2026 and directs
those users to Antigravity CLI (`agy`). Gemini CLI remains available to some
Standard and Enterprise customers, but it is no longer AgentPost's primary
Google integration target.

The Antigravity lifecycle profile is implemented and live-accepted on local
`agy 1.1.1`. It intentionally advertises catch-up rather than an already-idle
wake capability.

Results:

1. **Done:** inspect `agy 1.1.1` and its live plugin and hook contracts.
2. **Done:** generate an AgentPost plugin from the shared skill source. Antigravity
   plugins can bundle `plugin.json`, skills, rules, MCP configuration, and
   hooks under workspace `.agents/plugins/` or the global plugin directory.
3. **Done:** map `PreInvocation` and `Stop` lifecycle hooks to truthful `working` and
   `idle` presence. Use `Stop` continuation only to inject already-unread
   Message-IDs; notification must remain non-claiming.
4. **Done:** evaluate current external-input surfaces. The Antigravity SDK can
   push turns into SDK-owned sessions; it does not document waking an arbitrary
   IDE/App-owned idle conversation, and CLI acceptance exposed no validated
   already-idle wake path. Keep that capability unsupported instead of using
   terminal keystroke injection.
5. **Done:** cover install, doctor, uninstall, packaged templates, exact Message-ID
   catch-up, truthful capability degradation, shared-workspace identity
   selection, and multiline reply input.
6. **Done:** live-test install, static doctor, plugin hook loading, queued delivery,
   next-prompt exact-ID injection, claim, and correlated reply. Generalized
   rollback automation completed in `4fcf6a2`, with install quiescence and
   launcher cleanup completed in `a6c20c1` and `c436355`.

Primary references:

- [Google consumer-account deprecation notice](https://developers.google.com/gemini-code-assist/docs/deprecations/code-assist-individuals)
- [Migrating from Gemini CLI](https://antigravity.google/docs/gcli-migration)
- [Antigravity plugins](https://antigravity.google/docs/plugins)
- [Antigravity hooks](https://antigravity.google/docs/hooks)
- [Antigravity SDK](https://github.com/google-antigravity/antigravity-sdk-python)

Legacy Gemini extension and ACP concepts in `SPEC.md` are historical design
evidence, not the current implementation plan. Enterprise-only Gemini CLI
compatibility may be reconsidered after the Antigravity adapter is complete,
but it is not scheduled.

## Planned core follow-ups

- **Opt-in live doctor:** send one uniquely identified test letter and verify
  the installed adapter's advertised catch-up and attention behavior without
  duplicating the request through another channel.
- **Panel completion notification:** notify a question originator when all or
  quorum replies become complete, without an LLM polling loop. Quorum policy
  must be durable before this can work across process restarts.
- **Machine-readable capability report:** expose adapter support and degraded
  behavior in structured output, especially for catch-up-only integrations.
- **Adapter attach and generation truth:** the Codex slice is done: all three
  lifecycle hooks stamp the exact executing generation before injection
  suppression, doctor compares it with the enabled cache and Codex's current
  hook trust, and stable dispatcher commands preserve first-install approval
  across upgrades while naming the reload boundary. Sweep Claude and
  Antigravity next, using the same running-versus-installed vocabulary and
  distinguishing failed `immediate` interruption from routine queued delivery.
  Python already exposes live runtime-instance ownership rather than a plugin
  generation.
- **Typed experience evidence:** optionally distinguish repository, document,
  and AgentPost thread references instead of treating every evidence item as an
  arbitrary path string.
- **Claim recovery:** mailbox-wide leases and atomic claim prevent concurrent
  duplicate work, but a process crash after `unread -> read` can leave started
  work without completion evidence. Consider a separate inflight lease only if
  live use requires crash recovery; do not imply exactly-once execution.

## Unscheduled candidates

- Organization and department selectors in responsibility discovery.
- An installation setting for `off`, `consider`, or `proactive` peer
  consultation posture.
- Explicit do-not-disturb state if `working` plus per-message `idle` and
  `immediate` semantics prove insufficient in real use.
- macOS and Windows native-adapter acceptance. The current release is tested
  and classified for Linux/POSIX only.
- Optional disabling of the sender archive.

These require demonstrated demand before they become milestones.

## Deliberate v1 non-goals

The following are not parked implementation work. Adding any of them changes
the trusted-local product boundary and requires a new specification:

- remote transport, synchronization, accounts, authentication, or encryption;
- a web UI, network service, required MCP server, or resident AgentPost daemon;
- launching, supervising, or keeping model processes alive;
- LLM-based routing or synthesis inside the post office;
- exactly-once work execution guarantees.

The core remains a local durable post office. Native adapters ring an already
running agent's bell; they do not become an agent platform.
