"""Tests for the __ns__ plugin's guard. `uv run pytest` also runs the conformance suite."""

import pytest
from __ns___harness import BannedWords, BannedWordsConfig

import harnessweaver as hw

pytestmark = pytest.mark.anyio

ENV = hw.Envelope.new(tenant="test", principal="tester")


@pytest.mark.parametrize(
    ("text", "action"),
    [
        ("Please send the wire transfer today", hw.GuardAction.BLOCK),
        ("WIRE TRANSFER now", hw.GuardAction.BLOCK),
        ("A wired transfer is fine", hw.GuardAction.ALLOW),  # whole words only
        ("Nothing to see here", hw.GuardAction.ALLOW),
    ],
)
async def test_banned_words_block(text: str, action: hw.GuardAction) -> None:
    guard = BannedWords(BannedWordsConfig(words=["wire transfer", "lottery"]))
    result = await guard.check(text, ENV)
    assert result.action is action
    assert result.reason is None or text not in result.reason  # no content in reasons (R9)
