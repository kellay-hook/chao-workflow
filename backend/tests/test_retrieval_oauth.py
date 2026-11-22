from __future__ import annotations

from datetime import timedelta

import pytest

from app.models import OAuthConnection, utcnow
from app.schemas import Citation, SearchHit
from app.services import oauth
from app.services.rag import _keyword_rerank, _matches_filters


def _hit(chunk_id: str, text: str, score: float) -> SearchHit:
    return SearchHit(
        chunk_id=chunk_id,
        document_id="doc-1",
        title="doc",
        text=text,
        score=score,
        citation=Citation(chunk_id=chunk_id, document_id="doc-1", title="doc"),
    )


def test_metadata_filters_eq_contains_in_and_paths():
    metadata = {"category": "faq", "tags": ["billing", "refund"], "source": {"team": "support"}}
    assert _matches_filters(metadata, [{"key": "category", "operator": "eq", "value": "faq"}])
    assert not _matches_filters(metadata, [{"key": "category", "operator": "eq", "value": "legal"}])
    assert _matches_filters(metadata, [{"key": "category", "operator": "ne", "value": "legal"}])
    assert _matches_filters(metadata, [{"key": "source.team", "operator": "contains", "value": "SUP"}])
    assert _matches_filters(metadata, [{"key": "category", "operator": "in", "value": ["faq", "guide"]}])
    assert not _matches_filters(metadata, [{"key": "missing", "operator": "eq", "value": None}])


def test_metadata_filters_numeric_comparison():
    metadata = {"priority": 3, "score": "8.5"}
    assert _matches_filters(metadata, [{"key": "priority", "operator": "gte", "value": 2}])
    assert not _matches_filters(metadata, [{"key": "priority", "operator": "lte", "value": 2}])
    assert _matches_filters(metadata, [{"key": "score", "operator": "lte", "value": 9}])


def test_metadata_filters_coerce_ui_string_values():
    metadata = {"priority": 2, "rating": 4.5, "active": True, "tags": ["billing", "refund"]}
    assert _matches_filters(metadata, [{"key": "priority", "operator": "eq", "value": "2"}])
    assert _matches_filters(metadata, [{"key": "rating", "operator": "eq", "value": "4.5"}])
    assert _matches_filters(metadata, [{"key": "active", "operator": "eq", "value": "true"}])
    assert not _matches_filters(metadata, [{"key": "active", "operator": "eq", "value": "false"}])
    assert _matches_filters(metadata, [{"key": "priority", "operator": "in", "value": ["1", "2"]}])
    assert _matches_filters(metadata, [{"key": "tags", "operator": "contains", "value": "bill"}])


def test_metadata_filters_require_all_conditions():
    metadata = {"category": "faq", "lang": "zh"}
    filters = [
        {"key": "category", "operator": "eq", "value": "faq"},
        {"key": "lang", "operator": "eq", "value": "en"},
    ]
    assert not _matches_filters(metadata, filters)


def test_keyword_rerank_boosts_lexical_overlap():
    hits = [
        _hit("a", "退款流程说明", 0.8),
        _hit("b", "如何申请退款以及退款到账时间", 0.7),
    ]
    ranked = _keyword_rerank("退款 到账 时间", hits)
    assert [hit.chunk_id for hit in ranked] == ["b", "a"]


def _connection() -> OAuthConnection:
    item = OAuthConnection(
        name="demo",
        auth_url="https://idp.example.com/oauth/authorize?audience=crm",
        token_url="https://idp.example.com/oauth/token",
        client_id="client-abc",
        client_secret_ciphertext="cipher",
        scopes=["read:contacts", "write:contacts"],
        tenant_id="tenant-1",
    )
    item.id = "conn-1"
    return item


def test_oauth_authorize_url_contains_required_params():
    url = oauth.authorize_url(_connection(), "user-1")
    assert url.startswith("https://idp.example.com/oauth/authorize?")
    assert "audience=crm" in url
    assert "response_type=code" in url
    assert "client_id=client-abc" in url
    assert "redirect_uri=" in url
    assert "state=" in url


def test_oauth_state_roundtrip_and_tamper_rejected():
    state = oauth.sign_state(_connection(), "user-1")
    payload = oauth.decode_state(state)
    assert payload["connection_id"] == "conn-1"
    assert payload["tenant_id"] == "tenant-1"
    assert payload["user_id"] == "user-1"

    with pytest.raises(oauth.OAuthError):
        oauth.decode_state(state + "tampered")


def test_oauth_token_request_supports_basic_auth(monkeypatch):
    import asyncio

    import httpx as http_client

    from app.security import encrypt_secret

    connection = _connection()
    connection.token_auth_method = "client_secret_basic"
    connection.client_secret_ciphertext = encrypt_secret("secret-1")
    captured = {}

    class FakeResponse:
        status_code = 200
        text = ""

        def json(self):
            return {"access_token": "token-1"}

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, data=None, headers=None, auth=None):
            captured.update(url=url, data=data, headers=headers, auth=auth)
            return FakeResponse()

    monkeypatch.setattr(oauth.httpx, "AsyncClient", FakeClient)
    result = asyncio.run(oauth._token_request(connection, {"grant_type": "authorization_code", "code": "c"}))
    assert result["access_token"] == "token-1"
    assert isinstance(captured["auth"], http_client.BasicAuth)
    assert "client_secret" not in captured["data"]
    assert captured["data"]["client_id"] == "client-abc"


def test_oauth_token_request_defaults_to_post_body(monkeypatch):
    import asyncio

    from app.security import encrypt_secret

    connection = _connection()
    connection.client_secret_ciphertext = encrypt_secret("secret-1")
    captured = {}

    class FakeResponse:
        status_code = 200
        text = ""

        def json(self):
            return {"access_token": "token-1"}

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, data=None, headers=None, auth=None):
            captured.update(url=url, data=data, headers=headers, auth=auth)
            return FakeResponse()

    monkeypatch.setattr(oauth.httpx, "AsyncClient", FakeClient)
    asyncio.run(oauth._token_request(connection, {"grant_type": "authorization_code", "code": "c"}))
    assert captured["auth"] is None
    assert captured["data"]["client_secret"] == "secret-1"


def test_oauth_access_token_refreshes_when_expired(monkeypatch):
    from app.security import encrypt_secret

    connection = _connection()
    connection.access_token_ciphertext = encrypt_secret("stale-token")
    connection.refresh_token_ciphertext = encrypt_secret("refresh-token")
    connection.expires_at = utcnow() - timedelta(minutes=1)

    async def fake_refresh(item: OAuthConnection) -> None:
        item.access_token_ciphertext = encrypt_secret("fresh-token")
        item.expires_at = utcnow() + timedelta(hours=1)
        item.status = "refreshed"

    monkeypatch.setattr(oauth, "refresh", fake_refresh)
    import asyncio

    assert asyncio.run(oauth.access_token(connection)) == "fresh-token"
    assert connection.status == "refreshed"
