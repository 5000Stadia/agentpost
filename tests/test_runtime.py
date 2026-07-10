from __future__ import annotations

import asyncio
import queue
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from agentpost import (  # noqa: E402
    AgentPostError,
    AgentRuntime,
    PostOffice,
    Profile,
    agent_presence,
)
from agentpost.installer import armed  # noqa: E402


class PythonRuntimeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "post"
        self.office = PostOffice(self.root)
        self.office.register_profile(
            Profile(
                name="app",
                display_name="Application",
                cli="python",
                kind="project",
                summary="Embedded Python agent",
                projects=("application",),
            )
        )
        self.office.register_profile(
            Profile(
                name="cx",
                display_name="CX",
                cli="codex",
                kind="specialist",
                summary="Reviewer",
                specialties=("review",),
            )
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_runtime_presence_and_attention_boundaries(self) -> None:
        callbacks = queue.Queue()
        runtime = AgentRuntime(
            "app",
            root=self.root,
            on_mail=callbacks.put,
            interval=0.01,
        )
        with runtime:
            self.assertEqual(agent_presence(self.office, "app").state, "idle")
            runtime.set_state("working")
            idle = self.office.send("cx", "app", "later", notify="idle")
            immediate = self.office.send("cx", "app", "now", notify="immediate")

            first = runtime.get(timeout=1)
            self.assertEqual([item.message_id for item in first], [immediate.message_id])
            self.assertEqual(callbacks.get(timeout=1), first)
            self.assertEqual(agent_presence(self.office, "app").state, "working")

            runtime.set_state("idle")
            second = runtime.get(timeout=1)
            self.assertEqual([item.message_id for item in second], [idle.message_id])
            self.assertEqual(callbacks.get(timeout=1), second)
            self.assertEqual(len(self.office.list_messages("app", "unread")), 2)
        self.assertEqual(agent_presence(self.office, "app").state, "offline")

    def test_runtime_start_catches_up_and_never_claims(self) -> None:
        sent = self.office.send("cx", "app", "queued while offline")
        with AgentRuntime("app", root=self.root, interval=0.01) as runtime:
            batch = runtime.get(timeout=1)
            self.assertEqual(batch[0].message_id, sent.message_id)
            self.assertEqual(len(self.office.list_messages("app", "unread")), 1)

    def test_callback_failure_retries_in_order_without_duplicating_queue(self) -> None:
        callback_calls = []
        delivered = []
        complete = threading.Event()

        def flaky_callback(batch) -> None:
            callback_calls.append(tuple(item.message_id for item in batch))
            if len(callback_calls) == 1:
                raise RuntimeError("scheduler temporarily unavailable")
            delivered.extend(item.message_id for item in batch)
            if len(delivered) == 2:
                complete.set()

        with self.assertLogs("agentpost.runtime", level="ERROR"):
            with AgentRuntime(
                "app",
                root=self.root,
                on_mail=flaky_callback,
                interval=0.01,
            ) as runtime:
                first = self.office.send("cx", "app", "first")
                first_batch = runtime.get(timeout=1)
                self.assertEqual(
                    [item.message_id for item in first_batch],
                    [first.message_id],
                )

                second = self.office.send("cx", "app", "second")
                second_batch = runtime.get(timeout=1)
                self.assertEqual(
                    [item.message_id for item in second_batch],
                    [second.message_id],
                )

                self.assertTrue(complete.wait(1))
                self.assertEqual(delivered, [first.message_id, second.message_id])
                self.assertEqual(callback_calls[0], callback_calls[1])
                with self.assertRaises(queue.Empty):
                    runtime.get(timeout=0.05)
                self.assertEqual(len(self.office.list_messages("app", "unread")), 2)

    def test_callback_retry_drops_mail_claimed_through_the_queue(self) -> None:
        callback_calls = []
        failed = threading.Event()

        def unavailable_callback(batch) -> None:
            callback_calls.append(tuple(item.message_id for item in batch))
            failed.set()
            raise RuntimeError("scheduler temporarily unavailable")

        with self.assertLogs("agentpost.runtime", level="ERROR"):
            with AgentRuntime(
                "app",
                root=self.root,
                on_mail=unavailable_callback,
                interval=0.01,
            ) as runtime:
                sent = self.office.send("cx", "app", "queue consumer handles this")
                batch = runtime.get(timeout=1)
                self.assertTrue(failed.wait(1))
                self.office.claim("app", batch[0].message_id)
                time.sleep(0.2)
        self.assertEqual(callback_calls, [(sent.message_id,)])

    def test_callback_exhaustion_is_loud_and_reconcilable(self) -> None:
        def unavailable_callback(_batch) -> None:
            raise RuntimeError("scheduler unavailable")

        with self.assertLogs("agentpost.runtime", level="ERROR"):
            with AgentRuntime(
                "app",
                root=self.root,
                on_mail=unavailable_callback,
                interval=0.01,
                max_callback_attempts=2,
            ) as runtime:
                sent = self.office.send("cx", "app", "reconcile this")
                runtime.get(timeout=1)
                deadline = time.time() + 1
                presence = agent_presence(self.office, "app")
                while presence.healthy and time.time() < deadline:
                    time.sleep(0.01)
                    presence = agent_presence(self.office, "app")
                self.assertFalse(presence.healthy)
                self.assertIn("callback exhausted for 1 unread", presence.detail)
                self.assertFalse(armed(self.office, "app")[0])
                self.assertEqual(
                    [item.message_id for item in runtime.unread()],
                    [sent.message_id],
                )
                self.office.claim("app", sent.message_id)
                deadline = time.time() + 1
                while not agent_presence(self.office, "app").healthy and time.time() < deadline:
                    time.sleep(0.01)
                self.assertTrue(agent_presence(self.office, "app").healthy)
                self.assertTrue(armed(self.office, "app")[0])

    def test_async_context_and_get_bridge_to_the_runtime_queue(self) -> None:
        async def scenario() -> None:
            runtime = AgentRuntime("app", root=self.root, interval=0.01)
            async with runtime:
                sent = self.office.send("cx", "app", "async host")
                batch = await runtime.get_async(timeout=1)
                self.assertEqual([item.message_id for item in batch], [sent.message_id])
                with self.assertRaises(queue.Empty):
                    await runtime.get_async(timeout=0)
                waiter = asyncio.create_task(runtime.get_async())
                await asyncio.sleep(0)
            self.assertEqual(agent_presence(self.office, "app").state, "offline")
            with self.assertRaisesRegex(AgentPostError, "runtime is closed"):
                await asyncio.wait_for(waiter, timeout=1)

        asyncio.run(scenario())

    def test_one_python_runtime_owns_a_mailbox(self) -> None:
        first = AgentRuntime("app", root=self.root, interval=0.01).start()
        try:
            second = AgentRuntime("app", root=self.root, interval=0.01)
            with self.assertRaises(AgentPostError):
                second.start()
        finally:
            first.close()

    def test_nested_turns_remain_working_until_all_complete(self) -> None:
        with AgentRuntime("app", root=self.root, interval=0.01) as runtime:
            with runtime.turn():
                self.assertEqual(runtime.state, "working")
                with runtime.turn():
                    self.assertEqual(runtime.state, "working")
                self.assertEqual(runtime.state, "working")
            self.assertEqual(runtime.state, "idle")

    def test_unstarted_runtime_cannot_advertise_presence(self) -> None:
        runtime = AgentRuntime("app", root=self.root, interval=0.01)
        with self.assertRaises(AgentPostError):
            runtime.set_state("working")
        self.assertEqual(agent_presence(self.office, "app").state, "offline")


if __name__ == "__main__":
    unittest.main()
