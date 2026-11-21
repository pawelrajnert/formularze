import dataclasses
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import app

DIR = next((Path(__file__).resolve().parent.parent / "data" / "1").glob("1.*"))
NAME = "Wniosek o ustalenie numeru porządkowego nieruchomości"
FILES = {e: DIR / f"{NAME}.{e}" for e in ("pdf", "docx", "doc", "ods", "xlsx", "jpg", "jpeg")} | {"png": DIR / f"{NAME} (1).png"}
client = TestClient(app)


@pytest.fixture(autouse=True)
def env(monkeypatch):
    s = dataclasses.replace(config.settings, auth_enabled=True, auth_user="admin", auth_password="pw", jwt_secret="s" * 32)
    monkeypatch.setattr(config, "settings", s)


def auth():
    r = client.post("/api/v1/auth/token", json={"username": "admin", "password": "pw"})
    assert r.status_code == 200 and r.json()["token_type"] == "bearer"
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def upload(name, data, headers=None):
    return client.post("/api/v1/forms/convert", files={"file": (name, data)}, headers=auth() if headers is None else headers)


def test_token_bad_password():
    assert client.post("/api/v1/auth/token", json={"username": "admin", "password": "x"}).status_code == 401


def test_token_unconfigured(monkeypatch):
    monkeypatch.setattr(config, "settings", dataclasses.replace(config.settings, jwt_secret=""))
    assert client.post("/api/v1/auth/token", json={"username": "admin", "password": "pw"}).status_code == 503


def test_convert_requires_token():
    assert upload("a.pdf", FILES["pdf"].read_bytes(), headers={}).status_code == 401
    assert upload("a.pdf", FILES["pdf"].read_bytes(), headers={"Authorization": "Bearer zly"}).status_code == 401


def test_auth_disabled(monkeypatch):
    monkeypatch.setattr(config, "settings", dataclasses.replace(config.settings, auth_enabled=False))
    assert upload("a.pdf", FILES["pdf"].read_bytes(), headers={}).status_code == 200


@pytest.mark.parametrize("ext", FILES)
def test_convert_real_files(ext):
    data = FILES[ext].read_bytes()
    r = upload(FILES[ext].name, data)
    assert r.status_code == 200, r.text
    assert r.json() == {"filename": FILES[ext].name, "ext": ext, "size": len(data)}


@pytest.mark.parametrize("name", ["a;b.pdf", "x" * 247 + ".pdf", "a$.pdf", " "])
def test_bad_name(name):
    assert upload(name, FILES["pdf"].read_bytes()).status_code == 400


def test_too_big(monkeypatch):
    monkeypatch.setattr(config, "settings", dataclasses.replace(config.settings, max_file_size_mb=0))
    assert upload("a.pdf", FILES["pdf"].read_bytes()).status_code == 413


def test_unsupported_ext():
    assert upload("a.txt", b"hello").status_code == 415


def test_pdf_with_png_content():
    assert upload("a.pdf", FILES["png"].read_bytes()).status_code == 415


def test_docx_renamed_to_xlsx():
    assert upload("a.xlsx", FILES["docx"].read_bytes()).status_code == 415
