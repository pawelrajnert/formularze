"""F-18: bramka zatwierdzenia i rekord audytu obok JSON-a."""
import dataclasses
import json

import pytest
from fastapi.testclient import TestClient

from app import config
from app.approval import CHECKS
from app.main import app
from tests.test_api import FILES

client = TestClient(app)


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    s = dataclasses.replace(config.settings, auth_enabled=True, auth_user="urzednik", auth_password="pw", jwt_secret="s" * 32,
                            llm_api_key="", approval_required=True, audit_dir=str(tmp_path))
    monkeypatch.setattr(config, "settings", s)


def auth():
    r = client.post("/api/v1/auth/token", json={"username": "urzednik", "password": "pw"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def converted():
    r = client.post("/api/v1/forms/convert", files={"file": (FILES["docx"].name, FILES["docx"].read_bytes())}, headers=auth())
    assert r.status_code == 200 and r.json()["approval"]["status"] == "DRAFT"
    return r.json()


def body(out, **kw):
    b = {"form": out["form"], "token": out["approval"]["token"], "checks": {k: True for k in CHECKS}, "statement": True,
         "pages_visited": [t["id"] for t in out["form"]["tabs"]], "review_seconds": 42}
    return b | kw


def test_approve_writes_record_without_pii(tmp_path):
    out = converted()
    r = client.post("/api/v1/forms/approve", json=body(out), headers=auth())
    assert r.status_code == 200, r.text
    rec = r.json()["record"]
    assert rec["status"] == "APPROVED" and rec["approved_by"] == "urzednik" and rec["rules_check"] == "OK"
    assert len(rec["source"]["sha256"]) == 64 and rec["ai"]["prompt_sha256"]
    saved = json.loads((tmp_path / f"{rec['form_sha256']}.approval.json").read_text("utf-8"))
    assert saved == rec and "tabs" not in json.dumps(saved)  # rekord obok, nie kopia formularza


@pytest.mark.parametrize("change, status", [
    (lambda b: b["checks"].update(fees=False), 400),
    (lambda b: b.update(statement=False), 400),
    (lambda b: b["pages_visited"].pop(), 400),
    (lambda b: b["form"].update(title="Zmieniony poza systemem"), 409),
    (lambda b: b.update(token="zly"), 400),
])
def test_approve_rejected(change, status, tmp_path):
    b = body(converted())
    change(b)
    assert client.post("/api/v1/forms/approve", json=b, headers=auth()).status_code == status
    assert not list(tmp_path.iterdir())


def test_approve_needs_login():
    assert client.post("/api/v1/forms/approve", json=body(converted())).status_code == 401


def test_flag_off_no_approval_block(monkeypatch):
    monkeypatch.setattr(config, "settings", dataclasses.replace(config.settings, approval_required=False))
    r = client.post("/api/v1/forms/convert", files={"file": (FILES["docx"].name, FILES["docx"].read_bytes())}, headers=auth())
    assert "approval" not in r.json()
