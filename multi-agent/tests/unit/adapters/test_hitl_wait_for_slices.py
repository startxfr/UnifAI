"""R-567: RedisInputCapableChannel.wait_for cuts its wait into BLPOP slices of 5 s. Redis reads BLPOP timeout=0 as "block
forever", so no slice may ever be 0: with MAS_HITL_TIMEOUT_SECONDS=300.5 the last slice was 0.5, int(0.5) = 0, and an
unanswered approval would wait for ever instead of timing out."""
import json

import pytest

from outbound.channels.redis.input_channel import RedisInputCapableChannel


class _FakeRedis:
    """Records the timeout of every BLPOP; answers nothing, or `answer` on the call number `answer_at`."""

    def __init__(self, answer=None, answer_at=None):
        self.blpop_timeouts = []
        self.answer, self.answer_at = answer, answer_at

    def delete(self, *a, **k):
        return 0

    def sadd(self, *a, **k):
        return 1

    def blpop(self, key, timeout=0):
        self.blpop_timeouts.append(timeout)
        if self.answer_at is not None and len(self.blpop_timeouts) == self.answer_at:
            return key, json.dumps(self.answer)
        return None


def _wait(timeout, **fake):
    redis = _FakeRedis(**fake)
    result = _channel(redis).wait_for("req-1", timeout)
    return result, redis.blpop_timeouts


def _channel(redis):
    return RedisInputCapableChannel("s1", redis)


def test_a_wait_of_300_5_seconds_never_blocks_for_ever_and_ends_on_a_one_second_slice():
    result, slices = _wait(300.5)
    assert result is None
    assert 0 not in slices
    assert slices[-1] == 1
    assert slices[:-1] == [5] * 60  # the first 300 s are cut as before


def test_a_wait_of_300_seconds_is_unchanged_60_slices_of_5_seconds():
    result, slices = _wait(300)
    assert result is None
    assert slices == [5] * 60


@pytest.mark.parametrize("timeout", [0.3, 0.5, 1.0, 4.2, 5.5, 12.5, 300.5, 600.7])
def test_no_slice_is_ever_zero_and_the_wait_is_not_cut_short(timeout):
    _, slices = _wait(timeout)
    assert slices and all(isinstance(s, int) and s >= 1 for s in slices)
    assert sum(slices) >= timeout  # never gives up before the timeout...
    assert sum(slices) < timeout + 5  # ...and does not wait a whole extra slice


def test_an_answer_ends_the_wait_and_is_decoded():
    result, slices = _wait(300.5, answer={"decision": "approve"}, answer_at=3)
    assert result == {"decision": "approve"}
    assert slices == [5, 5, 5]
