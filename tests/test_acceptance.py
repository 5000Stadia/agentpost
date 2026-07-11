from __future__ import annotations

import tempfile
import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from agentpost import AgentRuntime, PostOffice, Profile
from agentpost.installer import armed
from agentpost.presence import agent_presence


AGENTS = ("k", "pb", "c", "cx")


def profile(name: str) -> Profile:
    return Profile(
        name=name,
        display_name=name.upper(),
        cli="python",
        kind="project",
        summary=f"Hermetic acceptance identity {name}",
        projects=(name,),
    )


class HermeticAcceptanceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.root = self.base / "post"
        self.office = PostOffice(self.root)
        for name in AGENTS:
            self.office.register_profile(profile(name))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def runtime(self, agent: str, *, on_mail=None) -> AgentRuntime:
        return AgentRuntime(
            agent,
            root=self.root,
            on_mail=on_mail,
            interval=0.01,
        )

    def test_offline_delivery_surfaces_original_id_and_preserves_inspection(self) -> None:
        request = self.office.send(
            "k",
            "pb",
            "OFFLINE-ACCEPTANCE: return this exact request.",
            kind="question",
        )
        self.assertEqual(agent_presence(self.office, "pb").state, "offline")
        self.assertFalse(armed(self.office, "pb")[0])
        before = request.recipient_path.read_bytes()
        self.assertEqual(self.office.list_messages("pb")[0].letter.message_id, request.message_id)
        self.assertEqual(self.office.read("pb", request.message_id).path.read_bytes(), before)
        self.assertEqual(request.recipient_path.read_bytes(), before)

        recipient = self.runtime("pb").start()
        sender = self.runtime("k").start()
        try:
            surfaced = recipient.get(timeout=2)
            self.assertEqual([item.message_id for item in surfaced], [request.message_id])
            self.assertTrue(armed(self.office, "pb")[0])
            claimed = self.office.claim("pb", request.message_id)
            self.assertEqual(claimed.letter.message_id, request.message_id)
            response = self.office.reply("pb", request.message_id, "OFFLINE-ACCEPTANCE: acknowledged.")
            returned = sender.get(timeout=2)
            self.assertEqual([item.message_id for item in returned], [response.message_id])
            self.assertEqual(returned[0].message_id, response.message_id)
            self.office.claim("k", response.message_id)
        finally:
            recipient.close()
            sender.close()

        self.assertEqual(self.office.list_messages("pb"), ())
        self.assertEqual(self.office.list_messages("k"), ())
        self.assertFalse(armed(self.office, "pb")[0])

    def test_four_agent_round_robin_drains_every_inbox(self) -> None:
        observed: dict[str, list[tuple[str, ...]]] = {name: [] for name in AGENTS}
        runtimes = {
            name: self.runtime(
                name,
                on_mail=lambda batch, recipient=name: observed[recipient].append(
                    tuple(item.message_id for item in batch)
                ),
            ).start()
            for name in AGENTS
        }
        route = (("k", "pb"), ("pb", "c"), ("c", "cx"), ("cx", "k"))
        try:
            for sender, recipient in route:
                request = self.office.send(
                    sender,
                    recipient,
                    f"ROUND-ROBIN {sender}->{recipient}",
                    kind="question",
                )
                received = runtimes[recipient].get(timeout=2)
                self.assertEqual([item.message_id for item in received], [request.message_id])
                self.office.claim(recipient, request.message_id)
                response = self.office.reply(
                    recipient,
                    request.message_id,
                    f"ROUND-ROBIN ACK {recipient}->{sender}",
                )
                returned = runtimes[sender].get(timeout=2)
                self.assertEqual([item.message_id for item in returned], [response.message_id])
                self.office.claim(sender, response.message_id)

            for name in AGENTS:
                self.assertTrue(armed(self.office, name)[0])
                self.assertEqual(self.office.list_messages(name), ())
                self.assertGreaterEqual(len(observed[name]), 2)
        finally:
            for runtime in runtimes.values():
                runtime.close()

        for name in AGENTS:
            self.assertEqual(agent_presence(self.office, name).state, "offline")
            self.assertFalse(armed(self.office, name)[0])
        self.assertFalse(any(path.name == "inbox" for path in self.base.rglob("inbox")))

    def test_each_member_can_be_the_only_first_runtime(self) -> None:
        for index, recipient in enumerate(AGENTS):
            with self.subTest(recipient=recipient):
                for name in AGENTS:
                    self.assertEqual(agent_presence(self.office, name).state, "offline")
                sender = AGENTS[(index + 1) % len(AGENTS)]
                request = self.office.send(
                    sender,
                    recipient,
                    f"FIRST-MEMBER {recipient}",
                )
                self.assertFalse(armed(self.office, recipient)[0])
                runtime = self.runtime(recipient).start()
                try:
                    surfaced = runtime.get(timeout=2)
                    self.assertEqual(
                        [item.message_id for item in surfaced],
                        [request.message_id],
                    )
                    self.assertTrue(armed(self.office, recipient)[0])
                    self.office.claim(recipient, request.message_id)
                finally:
                    runtime.close()
                self.assertEqual(agent_presence(self.office, recipient).state, "offline")
                self.assertFalse(armed(self.office, recipient)[0])
                self.assertEqual(self.office.list_messages(recipient), ())


if __name__ == "__main__":
    unittest.main()
