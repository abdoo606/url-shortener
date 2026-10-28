from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from shortener.api import create_app
from shortener.store import LinkStore
from shortener.urls import CODE_LENGTH, UrlRejected, generate_code, is_valid_code, normalise


# -------------------------------------------------------------------- urls
def test_normalise_adds_https():
    assert normalise("example.com/path") == "https://example.com/path"


def test_normalise_lowercases_host():
    assert normalise("HTTPS://Example.COM/A").startswith("https://example.com/")


def test_normalise_strips_fragment():
    assert "#" not in normalise("https://example.com/a#section")


@pytest.mark.parametrize("bad", ["", "   ", "javascript:alert(1)", "ftp://example.com", "file:///etc/passwd"])
def test_rejects_dangerous_urls(bad):
    with pytest.raises(UrlRejected):
        normalise(bad)


@pytest.mark.parametrize("bad", ["http://localhost:8000", "http://127.0.0.1", "http://printer.local"])
def test_rejects_ssrf_targets(bad):
    with pytest.raises(UrlRejected):
        normalise(bad)


def test_rejects_overlong_url():
    with pytest.raises(UrlRejected, match="2048"):
        normalise("https://example.com/" + "a" * 2100)


def test_codes_are_alphanumeric_and_unique():
    codes = {generate_code() for _ in range(500)}
    assert len(codes) == 500
    assert all(len(c) == CODE_LENGTH and c.isalnum() for c in codes)


def test_codes_never_numeric_or_reserved():
    assert not any(generate_code().isdigit() for _ in range(100))
    assert not is_valid_code("api")


# ------------------------------------------------------------------- store
def test_create_is_idempotent_per_url():
    store = LinkStore()
    a = store.create("https://example.com/x")
    b = store.create("https://example.com/x")
    assert a.code == b.code


def test_custom_code_conflict():
    store = LinkStore()
    store.create("https://a.com", code="mine")
    with pytest.raises(ValueError, match="already taken"):
        store.create("https://b.com", code="mine")


def test_stats_counts_visits():
    store = LinkStore()
    link = store.create("https://example.com")
    store.record_visit(link.code, referrer="https://news.site")
    store.record_visit(link.code)
    stats = store.stats(link.code)
    assert stats["clicks"] == 2
    assert stats["referrers"]["direct"] == 1


def test_delete_cascades_visits():
    store = LinkStore()
    link = store.create("https://example.com")
    store.record_visit(link.code)
    assert store.delete(link.code)
    assert store.stats(link.code) is None
    assert store.delete(link.code) is False


# --------------------------------------------------------------------- api
@pytest.fixture()
def client():
    store = LinkStore()
    with TestClient(create_app(store, base_url="http://sho.rt")) as c:
        yield c
    store.close()


def test_create_link(client):
    response = client.post("/api/links", json={"url": "https://example.com/article"})
    assert response.status_code == 201
    body = response.json()
    assert body["short_url"].startswith("http://sho.rt/")
    assert body["url"] == "https://example.com/article"


def test_reject_bad_url_returns_422(client):
    assert client.post("/api/links", json={"url": "javascript:alert(1)"}).status_code == 422


def test_custom_code_conflict_returns_409(client):
    client.post("/api/links", json={"url": "https://a.com", "code": "custom"})
    response = client.post("/api/links", json={"url": "https://b.com", "code": "custom"})
    assert response.status_code == 409


def test_redirect_and_click_tracking(client):
    code = client.post("/api/links", json={"url": "https://example.com"}).json()["code"]
    response = client.get(f"/{code}", follow_redirects=False, headers={"referer": "https://news.site"})
    assert response.status_code == 302
    assert response.headers["location"] == "https://example.com/"
    assert client.get(f"/api/links/{code}").json()["clicks"] == 1


def test_unknown_code_404(client):
    assert client.get("/nope1234", follow_redirects=False).status_code == 404
    assert client.get("/api/links/nope1234").status_code == 404


def test_top_orders_by_clicks(client):
    first = client.post("/api/links", json={"url": "https://a.com"}).json()["code"]
    second = client.post("/api/links", json={"url": "https://b.com"}).json()["code"]
    for _ in range(3):
        client.get(f"/{first}", follow_redirects=False)
    client.get(f"/{second}", follow_redirects=False)
    assert client.get("/api/top").json()[0]["code"] == first


def test_delete_link(client):
    code = client.post("/api/links", json={"url": "https://a.com"}).json()["code"]
    assert client.delete(f"/api/links/{code}").status_code == 204
    assert client.delete(f"/api/links/{code}").status_code == 404


def test_limit_is_clamped(client):
    assert client.get("/api/top?limit=1000").status_code == 200


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}
