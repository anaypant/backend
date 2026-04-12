import os

import pytest

from store import browser_cors


class _Req:
    def __init__(self, method: str, path: str, origin: str | None = None):
        self.method = method
        self.path = path
        self.headers = {}
        if origin:
            self.headers["Origin"] = origin


@pytest.fixture(autouse=True)
def clear_cors_env(monkeypatch):
    monkeypatch.delenv("ACS_BROWSER_CORS_ORIGINS", raising=False)
    yield


def test_preflight_allowed(monkeypatch):
    monkeypatch.setenv("ACS_BROWSER_CORS_ORIGINS", "https://oauth.automatedconsultancy.com")
    r = _Req("OPTIONS", "/integrations/followupboss/oauth/start", "https://oauth.automatedconsultancy.com")
    out = browser_cors.cors_preflight_response(r)
    assert out is not None
    body, status, headers = out
    assert status == 204
    assert headers["Access-Control-Allow-Origin"] == "https://oauth.automatedconsultancy.com"


def test_preflight_origin_not_listed(monkeypatch):
    monkeypatch.setenv("ACS_BROWSER_CORS_ORIGINS", "https://oauth.automatedconsultancy.com")
    r = _Req("OPTIONS", "/integrations/followupboss/oauth/start", "https://evil.example")
    out = browser_cors.cors_preflight_response(r)
    assert out is not None
    assert out[1] == 403


def test_merge_get_adds_headers(monkeypatch):
    monkeypatch.setenv("ACS_BROWSER_CORS_ORIGINS", "https://oauth.automatedconsultancy.com")
    r = _Req("GET", "/integrations/followupboss/oauth/start", "https://oauth.automatedconsultancy.com")
    base = ('{"ok":true}', 200, {"Content-Type": "application/json"})
    out = browser_cors.merge_browser_cors(r, base)
    assert out[2]["Access-Control-Allow-Origin"] == "https://oauth.automatedconsultancy.com"


def test_preflight_disconnect_allowed(monkeypatch):
    monkeypatch.setenv("ACS_BROWSER_CORS_ORIGINS", "https://oauth.automatedconsultancy.com")
    r = _Req("OPTIONS", "/integrations/followupboss/disconnect", "https://oauth.automatedconsultancy.com")
    out = browser_cors.cors_preflight_response(r)
    assert out is not None
    assert out[1] == 204
    assert "POST" in out[2]["Access-Control-Allow-Methods"]


def test_merge_post_disconnect_adds_headers(monkeypatch):
    monkeypatch.setenv("ACS_BROWSER_CORS_ORIGINS", "https://oauth.automatedconsultancy.com")
    r = _Req("POST", "/integrations/followupboss/disconnect", "https://oauth.automatedconsultancy.com")
    base = ('{"ok":true}', 200, {"Content-Type": "application/json"})
    out = browser_cors.merge_browser_cors(r, base)
    assert out[2]["Access-Control-Allow-Origin"] == "https://oauth.automatedconsultancy.com"
