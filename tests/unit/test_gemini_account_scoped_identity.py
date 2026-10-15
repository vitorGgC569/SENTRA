from __future__ import annotations

import pytest
from sentra_core.conversation import ConversationIdentity
from native_bridge.protocol import ChatJob, ChatResult


def test_gemini_account_scoped_url_roundtrips_without_switching_google_accounts():
    url = "https://gemini.google.com/u/7/app/abc123"
    identity = ConversationIdentity.parse(url)
    assert identity.provider == "gemini"
    assert identity.conversation_id == "abc123"
    assert identity.account_index == 7
    assert identity.canonical_url == url
    assert ConversationIdentity.parse(url + "?pageId=34") == identity
    assert ConversationIdentity.parse("https://gemini.google.com/app/abc123") != identity


def test_unscoped_gemini_identity_remains_compatible():
    url = "https://gemini.google.com/app/abc123"
    identity = ConversationIdentity.parse(url)
    assert identity.account_index is None
    assert identity.canonical_url == url
    assert ConversationIdentity.from_parts("gemini", "abc123") == identity


def test_from_parts_keeps_account_index_from_validated_url():
    expected = ConversationIdentity.parse("https://gemini.google.com/u/7/app/chat123")
    assert ConversationIdentity.from_parts("gemini", "chat123", expected.canonical_url) == expected
    with pytest.raises(ValueError):
        ConversationIdentity.from_parts("gemini", "other", expected.canonical_url)


@pytest.mark.parametrize("bad_url", [
    "https://gemini.google.com/u/9999/app/abc123",
    "https://gemini.google.com/u/foo/app/abc123",
    "https://gemini.google.com/u/7/app/",
    "https://evil.example/u/7/app/abc123",
    "http://gemini.google.com/u/7/app/abc123",
])
def test_rejects_invalid_scoped_routes(bad_url):
    with pytest.raises(ValueError):
        ConversationIdentity.parse(bad_url)


def test_relay_chat_peek_keeps_gemini_account_slot():
    url = "https://gemini.google.com/u/7/app/chat123"
    job = ChatJob(task_id="read-only-peek", kind="CHAT_PEEK", provider="gemini",
                  new_chat=False, prompt="", conversation_url=url, timeout_s=20)
    job.validate()
    assert job.conversation_url == url


def test_relay_chat_result_keeps_scoped_url():
    url = "https://gemini.google.com/u/7/app/chat123"
    result = ChatResult(job_id="job_0123456789", task_id="trace123",
                        status="COMPLETED", conversation_url=url, result="hello")
    result.validate()
    assert result.conversation_url == url
    assert result.conversation_id == "chat123"
