"""R-08: GET /api/v1/security - lista zabezpieczeń ze stanem z konfiguracji, bez sekretów."""
import dataclasses

import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import app

client = TestClient(app)
SECRETS = {"jwt_secret": "jwt-sekret-" + "x" * 24, "auth_password": "haslo-tajne-123", "llm_api_key": "klucz-llm-tajny-456"}


@pytest.fixture(autouse=True)
def env(monkeypatch):
    s = dataclasses.replace(config.settings, auth_enabled=True, auth_user="admin", approval_required=False,
                            rate_limit_per_minute=30, llm_base_url="https://llm.tajny.example/v1", **SECRETS)
    monkeypatch.setattr(config, "settings", s)
    monkeypatch.delenv("COMPLIANCE_ENABLED", raising=False)


def get(headers=None):
    if headers is None:
        t = client.post("/api/v1/auth/token", json={"username": "admin", "password": SECRETS["auth_password"]}).json()
        headers = {"Authorization": f"Bearer {t['access_token']}"}
    return client.get("/api/v1/security", headers=headers)


def by_id(r):
    assert r.status_code == 200
    return {x["id"]: x for x in r.json()}


def test_requires_auth():
    assert get(headers={}).status_code == 401
    assert get(headers={"Authorization": "Bearer zly"}).status_code == 401


def test_defaults_shape_and_states():
    items = by_id(get())
    assert set(items) >= {"auth", "rate_limit", "file_validation", "memory_only", "prompt_injection", "output_rules",
                          "no_content_logs", "compliance", "approval", "open_weights", "docker_non_root"}
    for x in items.values():
        assert set(x) == {"id", "nazwa", "stan", "opis", "jak_wlaczyc", "dowod"}
        assert x["stan"] in ("włączone", "wyłączone") and x["opis"] and x["dowod"]
        assert (x["jak_wlaczyc"] is None) == (x["stan"] == "włączone")
    assert items["auth"]["stan"] == items["rate_limit"]["stan"] == items["file_validation"]["stan"] == "włączone"
    assert items["compliance"] == {**items["compliance"], "stan": "wyłączone", "jak_wlaczyc": "COMPLIANCE_ENABLED=true"}
    assert items["approval"] == {**items["approval"], "stan": "wyłączone", "jak_wlaczyc": "APPROVAL_REQUIRED=true"}


def test_flags_on(monkeypatch):
    monkeypatch.setenv("COMPLIANCE_ENABLED", "true")
    monkeypatch.setattr(config, "settings", dataclasses.replace(config.settings, approval_required=True))
    items = by_id(get())
    assert items["compliance"]["stan"] == items["approval"]["stan"] == "włączone"
    assert items["compliance"]["jak_wlaczyc"] is None


def test_auth_and_rate_limit_off(monkeypatch):
    monkeypatch.setattr(config, "settings", dataclasses.replace(config.settings, auth_enabled=False, rate_limit_per_minute=0))
    items = by_id(get(headers={}))  # bez logowania endpoint jest otwarty jak reszta API
    assert items["auth"] == {**items["auth"], "stan": "wyłączone", "jak_wlaczyc": "AUTH_ENABLED=true"}
    assert items["rate_limit"]["stan"] == "wyłączone" and items["rate_limit"]["jak_wlaczyc"].startswith("RATE_LIMIT_PER_MINUTE=")


def test_file_size_limit_shown(monkeypatch):
    monkeypatch.setattr(config, "settings", dataclasses.replace(config.settings, max_file_size_mb=7))
    assert "7 MB" in by_id(get())["file_validation"]["opis"]


def test_no_secrets_in_response():
    text = get().text
    for v in [*SECRETS.values(), "llm.tajny.example"]:
        assert v not in text
