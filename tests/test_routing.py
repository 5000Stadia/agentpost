from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from agentpost import (  # noqa: E402
    Experience,
    PostOffice,
    Profile,
    UnknownAgentError,
    find_agents,
    identify_agent,
    project_candidates,
    resolve_channel_recipients,
    resolve_identity,
    resolve_recipients,
)


class RoutingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.office = PostOffice(Path(self.temp.name) / "post")
        profiles = (
            Profile(
                name="k",
                display_name="Kernos",
                cli="claude",
                kind="project",
                summary="Member policy and onboarding",
                projects=("kernos",),
                specialties=("onboarding",),
            ),
            Profile(
                name="pb",
                display_name="Pattern Buffer",
                cli="claude",
                kind="hybrid",
                summary="Persistent world state substrate",
                roles=("world model engineer",),
                projects=("pattern-buffer",),
                specialties=("temporal identity", "ingestion fidelity"),
                handles=("world state storage",),
                experience=(
                    Experience(
                        topic="bounded temporal reads",
                        summary="Implemented frame-scoped state reads",
                        projects=("construct",),
                        evidence=("/evidence/bounded-reads.md",),
                    ),
                ),
            ),
            Profile(
                name="c",
                display_name="Construct",
                cli="claude",
                kind="project",
                summary="Interactive fiction orchestration",
                projects=("construct",),
            ),
            Profile(
                name="marketing",
                display_name="Marketing",
                cli="codex",
                kind="role",
                summary="Positioning and launches",
                roles=("marketing",),
                specialties=("positioning",),
            ),
            Profile(
                name="cx",
                display_name="Codex",
                cli="codex",
                kind="specialist",
                summary="Cross-project implementation and review",
                specialties=("code review",),
            ),
        )
        for item in profiles:
            self.office.register_profile(item)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_exact_selectors_find_role_project_and_specialty(self) -> None:
        self.assertEqual(
            [
                item.profile.name
                for item in find_agents(self.office, role="marketing", include_offline=True)
            ],
            ["marketing"],
        )
        self.assertEqual(
            [
                item.profile.name
                for item in find_agents(self.office, project="construct", include_offline=True)
            ],
            ["c"],
        )
        self.assertEqual(
            [
                item.profile.name
                for item in find_agents(
                    self.office, specialty="temporal identity", include_offline=True
                )
            ],
            ["pb"],
        )

    def test_evidence_backed_experience_is_visible(self) -> None:
        match = find_agents(
            self.office, "bounded temporal reads", include_offline=True
        )[0]
        self.assertEqual(match.profile.name, "pb")
        self.assertIn("/evidence/bounded-reads.md", match.evidence)
        self.assertTrue(any("evidence-backed" in reason for reason in match.reasons))

    def test_resolve_deduplicates_groups_selectors_and_skips_sender(self) -> None:
        result = resolve_recipients(
            self.office,
            ("@world", "@project:construct", "pb,c"),
            sender="cx",
            groups={"world": ("cx", "k", "pb")},
        )
        self.assertEqual(result, ("k", "pb", "c"))

    def test_familiarity_does_not_affect_responsibility_match(self) -> None:
        matches = find_agents(
            self.office, "temporal identity", include_offline=True
        )
        self.assertEqual(matches[0].profile.name, "pb")
        self.assertNotEqual(matches[0].profile.name, "k")

    def test_project_binding_uses_longest_matching_root(self) -> None:
        broad = Profile(
            name="broad",
            display_name="Broad",
            cli="claude",
            kind="project",
            summary="Broad root",
            projects=("broad",),
            project_roots=(self.temp.name,),
        )
        nested_root = Path(self.temp.name) / "nested"
        nested = Profile(
            name="nested",
            display_name="Nested",
            cli="claude",
            kind="project",
            summary="Nested root",
            projects=("nested",),
            project_roots=(str(nested_root),),
        )
        self.office.register_profile(broad)
        self.office.register_profile(nested)
        self.office.bind_agent("broad", "claude", self.temp.name)
        self.assertEqual(
            identify_agent(self.office, nested_root / "src", cli="claude").name,
            "nested",
        )

    def test_offline_profiles_are_hidden_but_exact_addresses_still_resolve(self) -> None:
        self.assertEqual(find_agents(self.office, "marketing"), ())
        self.assertEqual(
            find_agents(self.office, "marketing", include_offline=True)[0].profile.name,
            "marketing",
        )
        self.assertEqual(
            resolve_recipients(self.office, ("marketing",), sender="cx"),
            ("marketing",),
        )

    def test_human_identity_resolves_names_projects_and_responsibilities(self) -> None:
        self.assertEqual(resolve_identity(self.office, "PB").name, "pb")
        self.assertEqual(
            resolve_identity(self.office, "Pattern Buffer").name,
            "pb",
        )

    def test_human_identity_does_not_fuzzy_route_partial_expertise(self) -> None:
        with self.assertRaisesRegex(UnknownAgentError, "agents-find"):
            resolve_identity(self.office, "world")
        self.assertEqual(resolve_identity(self.office, "pattern-buffer").name, "pb")
        self.assertEqual(
            resolve_identity(self.office, "world state storage").name,
            "pb",
        )

    def test_channel_addresses_named_groups_and_offline_identities(self) -> None:
        self.office.set_group("world-team", ("pb", "c"))
        self.assertEqual(
            resolve_channel_recipients(
                self.office,
                ("World Team, Kernos",),
                sender="cx",
            ),
            ("pb", "c", "k"),
        )

    def test_channel_rejects_group_identity_collision(self) -> None:
        self.office.set_group("pattern-buffer", ("pb", "c"))
        with self.assertRaisesRegex(ValueError, "agent pb or group @pattern-buffer"):
            resolve_channel_recipients(
                self.office,
                ("Pattern Buffer",),
                sender="cx",
            )

    def test_ambiguous_human_identity_is_not_guessed(self) -> None:
        self.office.register_profile(
            Profile(
                name="storage",
                display_name="Storage",
                cli="python",
                kind="specialist",
                summary="Additional storage specialist",
                specialties=("storage",),
                handles=("world state storage",),
            )
        )
        with self.assertRaisesRegex(ValueError, "ambiguous AgentPost identity"):
            resolve_identity(self.office, "world state storage")

    def test_explicit_binding_reconnects_in_manual_mode(self) -> None:
        root = Path(self.temp.name) / "manual-project"
        self.office.set_connection_mode("manual")
        with self.assertRaises(UnknownAgentError):
            identify_agent(self.office, root, cli="codex")
        self.office.bind_agent("cx", "codex", root)
        self.assertEqual(identify_agent(self.office, root, cli="codex").name, "cx")

    def test_per_process_agent_override_allows_shared_project(self) -> None:
        root = Path(self.temp.name) / "shared"
        self.office.bind_agent("cx", "codex", root)
        self.assertEqual(identify_agent(self.office, root, cli="codex").name, "cx")
        self.assertEqual(
            identify_agent(self.office, root, cli="codex", agent="marketing").name,
            "marketing",
        )

    def test_bare_join_candidate_uses_unique_deepest_profile_root(self) -> None:
        broad = Profile(
            name="broad_join",
            display_name="Broad Join",
            cli="claude",
            kind="project",
            summary="Broad project",
            projects=("broad",),
            project_roots=(self.temp.name,),
        )
        nested_root = Path(self.temp.name) / "join-project"
        nested = Profile(
            name="nested_join",
            display_name="Nested Join",
            cli="claude",
            kind="project",
            summary="Nested project",
            projects=("nested",),
            project_roots=(str(nested_root),),
        )
        self.office.register_profile(broad)
        self.office.register_profile(nested)
        self.assertEqual(
            [item.name for item in project_candidates(self.office, nested_root)],
            ["nested_join"],
        )


if __name__ == "__main__":
    unittest.main()
