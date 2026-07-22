from __future__ import annotations

import unittest

from aiflow.api.sse import EventBuffer


class EventBufferTests(unittest.TestCase):
    def test_event_ids_replay_after_last_seen_id(self) -> None:
        events = EventBuffer(limit=4)
        first = events.publish("snapshot", {"revision": 1})
        second = events.publish("run", {"status": "PAUSED"})
        third = events.publish("run", {"status": "RUNNING"})
        replay = events.replay(str(first.event_id))
        self.assertFalse(replay.reset)
        self.assertEqual([event.event_id for event in replay.events], [second.event_id, third.event_id])
        self.assertIn("id: 2", second.encode())
        self.assertIn("event: run", second.encode())

    def test_evicted_or_invalid_cursor_requires_snapshot_reset(self) -> None:
        events = EventBuffer(limit=2)
        for value in range(4):
            events.publish("run", {"revision": value})
        self.assertTrue(events.replay("1").reset)
        self.assertTrue(events.replay("not-an-id").reset)
        self.assertLessEqual(len(events.replay("").events), 2)


if __name__ == "__main__":
    unittest.main()
