# Releasing AgentPost

This procedure publishes one reviewed commit without rebuilding or editing it
between approval and tag creation.

## Prepare

1. Update `pyproject.toml`, `CHANGELOG.md`, installer and documentation pins,
   Python/Node client version literals, implementation status, and roadmap.
2. Run the release consistency test and all verification commands:

   ```sh
   PYTHONPATH=src python3 -m unittest discover -s tests -v
   python3 scripts/verify_clean_install.py
   python3 -m compileall -q src tests scripts
   node --check src/agentpost/data/codex_bridge.mjs
   sh -n scripts/install.sh
   ./scripts/smoke_two_agents.sh
   git diff --check
   ```

3. Build an sdist and wheel in a clean temporary environment, inspect their
   metadata and contents, install the wheel into a clean home, and rerun the
   two-agent smoke.
4. Commit once. Record the complete SHA and obtain independent release and
   security GREEN against that immutable commit.

## Publish

The installer and published documentation pin the release tag before that tag
exists. Use this exact order:

1. Push the reviewed commit to `main`.
2. Wait for the GitHub Actions Python 3.11, 3.12, and 3.13 jobs to succeed.
3. Create an annotated `vVERSION` tag on the exact reviewed SHA and push it.
4. Verify the versioned bootstrap command end to end from a clean home.
5. Create the GitHub release from that tag and verify its source archives,
   notes, default-branch SHA, repository description, topics, security policy,
   and vulnerability-reporting path.

The versioned bootstrap URL is expected not to resolve during the brief window
between step 1 and step 3. Do not advertise the release during that window.
Developers testing the unpublished commit must set `AGENTPOST_SOURCE` to a
local checkout or explicit Git revision; the static release-consistency test
must never require the future tag to exist.

AgentPost currently publishes through GitHub releases, not PyPI. Do not claim a
PyPI release or upload package artifacts there without a separate supply-chain
specification and trusted-publisher setup.

## After publication

- Confirm `git ls-remote` and the GitHub release resolve `vVERSION` to the
  reviewed SHA.
- Run `agentpost doctor` for each locally installed adapter after upgrading.
- Keep the release commit unchanged. Any correction becomes a new patch
  release and changelog entry.
