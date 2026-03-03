import unittest

from app.cli.poller import PullBridgePoller


class _FakeApiClient:
    def __init__(self, *, ack_fail_ids=None, nack_fail_ids=None):
        self.ack_calls = []
        self.nack_calls = []
        self.ack_fail_ids = set(ack_fail_ids or [])
        self.nack_fail_ids = set(nack_fail_ids or [])

    async def ack_updates(self, *, message_ids, consumer_id):
        self.ack_calls.append((list(message_ids), consumer_id))
        if message_ids[0] in self.ack_fail_ids:
            raise RuntimeError("ack failed")
        return {"ok": True}

    async def nack_updates(self, *, message_ids, consumer_id, error=None):
        self.nack_calls.append((list(message_ids), consumer_id, error))
        if message_ids[0] in self.nack_fail_ids:
            raise RuntimeError("nack failed")
        return {"ok": True}


class _TestPoller(PullBridgePoller):
    def __init__(self, *, api_client, consumer_id, outcomes):
        super().__init__(
            api_client=api_client,
            local_webhook_url="http://localhost:9999/webhook",
            consumer_id=consumer_id,
            local_timeout_sec=1.0,
        )
        self._outcomes = list(outcomes)

    async def _process_one(self, *, local_client, msg):
        message_id = int(msg["id"])
        outcome = self._outcomes.pop(0)

        if outcome == "ok":
            self.counters.forward_success_total += 1
            ack_ok, _ = await self._ack_one(message_id=message_id)
            if ack_ok:
                self.counters.acked_total += 1
            else:
                self.counters.ack_fail_total += 1
            return

        self.counters.forward_fail_total += 1
        nack_ok, _ = await self._nack_one(
            message_id=message_id,
            forward_result=type(
                "ForwardResultStub",
                (),
                {"error": "local_http_status=500; response_body_snippet=boom"},
            )(),
        )
        if nack_ok:
            self.counters.nacked_total += 1
        else:
            self.counters.nack_fail_total += 1


class PollerTests(unittest.IsolatedAsyncioTestCase):
    async def test_process_batch_ack_and_nack_per_message(self):
        api = _FakeApiClient()
        poller = _TestPoller(
            api_client=api,
            consumer_id="consumer-A",
            outcomes=["ok", "fail", "ok"],
        )
        messages = [
            {"id": 1, "bot_id": "b1", "telegram_update_id": 101, "payload": {"x": 1}},
            {"id": 2, "bot_id": "b1", "telegram_update_id": 102, "payload": {"x": 2}},
            {"id": 3, "bot_id": "b1", "telegram_update_id": 103, "payload": {"x": 3}},
        ]

        await poller.process_batch(messages)

        self.assertEqual(api.ack_calls, [([1], "consumer-A"), ([3], "consumer-A")])
        self.assertEqual(len(api.nack_calls), 1)
        self.assertEqual(api.nack_calls[0][0], [2])
        self.assertEqual(api.nack_calls[0][1], "consumer-A")
        self.assertIn("local_http_status=500", api.nack_calls[0][2])
        self.assertEqual(poller.counters.pulled_total, 3)
        self.assertEqual(poller.counters.forward_success_total, 2)
        self.assertEqual(poller.counters.forward_fail_total, 1)
        self.assertEqual(poller.counters.acked_total, 2)
        self.assertEqual(poller.counters.nacked_total, 1)
        self.assertEqual(poller.counters.ack_fail_total, 0)
        self.assertEqual(poller.counters.nack_fail_total, 0)

    async def test_ack_failure_does_not_stop_next_messages(self):
        api = _FakeApiClient(ack_fail_ids={1})
        poller = _TestPoller(
            api_client=api,
            consumer_id="consumer-A",
            outcomes=["ok", "ok"],
        )
        messages = [
            {"id": 1, "bot_id": "b1", "telegram_update_id": 101, "payload": {"x": 1}},
            {"id": 2, "bot_id": "b1", "telegram_update_id": 102, "payload": {"x": 2}},
        ]

        await poller.process_batch(messages)

        self.assertEqual(api.ack_calls, [([1], "consumer-A"), ([2], "consumer-A")])
        self.assertEqual(api.nack_calls, [])
        self.assertEqual(poller.counters.pulled_total, 2)
        self.assertEqual(poller.counters.forward_success_total, 2)
        self.assertEqual(poller.counters.acked_total, 1)
        self.assertEqual(poller.counters.ack_fail_total, 1)

    async def test_nack_failure_does_not_stop_next_messages(self):
        api = _FakeApiClient(nack_fail_ids={2})
        poller = _TestPoller(
            api_client=api,
            consumer_id="consumer-A",
            outcomes=["fail", "fail", "ok"],
        )
        messages = [
            {"id": 1, "bot_id": "b1", "telegram_update_id": 101, "payload": {"x": 1}},
            {"id": 2, "bot_id": "b1", "telegram_update_id": 102, "payload": {"x": 2}},
            {"id": 3, "bot_id": "b1", "telegram_update_id": 103, "payload": {"x": 3}},
        ]

        await poller.process_batch(messages)

        self.assertEqual(api.nack_calls[0][0], [1])
        self.assertEqual(api.nack_calls[1][0], [2])
        self.assertEqual(api.ack_calls, [([3], "consumer-A")])
        self.assertEqual(poller.counters.forward_fail_total, 2)
        self.assertEqual(poller.counters.nacked_total, 1)
        self.assertEqual(poller.counters.nack_fail_total, 1)
        self.assertEqual(poller.counters.acked_total, 1)


if __name__ == "__main__":
    unittest.main()
