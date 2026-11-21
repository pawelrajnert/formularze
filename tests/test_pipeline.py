import dataclasses
import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from openai import RateLimitError

from app import config, ingest
from app.form_builder import llm_draft as llm_mod
from app.main import app
from app.pipeline import convert_document
from app.rules_check import check

DIR = next((Path(__file__).resolve().parent.parent / "data" / "1").glob("1.*"))
NAME = "Wniosek o ustalenie numeru porządkowego nieruchomości"
FILES = {e: DIR / f"{NAME}.{e}" for e in ("pdf", "docx", "doc", "ods", "xlsx", "jpg", "jpeg")} | {"png": DIR / f"{NAME} (1).png"}
DRAFT = (Path(__file__).parent / "fixtures" / "draft_form1.json").read_text("utf-8")

TESS = shutil.which("tesseract")
LANGS = subprocess.run([TESS, "--list-langs"], capture_output=True, text=True).stdout.split() if TESS else []
SOFFICE = shutil.which("soffice") or Path(ingest.SOFFICE_MAC).exists()
NEEDS = {"doc": SOFFICE, "ods": SOFFICE, "jpg": TESS, "jpeg": TESS, "png": TESS}
client = TestClient(app)


@pytest.fixture(autouse=True)
def env(monkeypatch):
    s = dataclasses.replace(config.settings, auth_enabled=False, llm_base_url="", llm_api_key="", llm_model="",
                            ocr_lang="pol" if "pol" in LANGS else "eng")  # lokalnie bywa tylko eng; Docker ma pol
    monkeypatch.setattr(config, "settings", s)


@pytest.mark.parametrize("ext", FILES)
def test_convert_each_format(ext):
    if not NEEDS.get(ext, True):
        pytest.skip(f"brak narzędzia systemowego dla .{ext}")
    r = client.post("/api/v1/forms/convert?debug=true", files={"file": (FILES[ext].name, FILES[ext].read_bytes())})
    assert r.status_code == 200, r.text
    body = r.json()
    assert check(body["form"]) == []
    assert body["trace"]["source"] == "heuristic" and body["trace"]["reason"] == "brak konfiguracji LLM"


def test_corrupted_file_422():
    r = client.post("/api/v1/forms/convert", files={"file": ("a.xlsx", b"PK\x03\x04" + b"\0" * 100)})
    assert r.status_code in (415, 422)  # zależnie od tego, czy F-02 przepuści nagłówek ZIP


def _llm_on(monkeypatch, create):
    monkeypatch.setattr(config, "settings", dataclasses.replace(config.settings, llm_base_url="http://x", llm_api_key="k", llm_model="m"))
    fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(llm_mod, "_client", lambda: fake)
    monkeypatch.setattr(llm_mod.time, "sleep", lambda _: None)


def test_llm_draft_used(monkeypatch):
    calls = []

    def create(**kw):
        calls.append(kw)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=DRAFT))])
    _llm_on(monkeypatch, create)
    out = convert_document(FILES["pdf"].read_bytes(), "pdf", True)
    assert out["trace"]["source"] == "llm" and check(out["form"]) == []
    assert out["form"]["title"] == json.loads(DRAFT)["title"]
    assert calls[0]["response_format"]["type"] == "json_schema"


def test_llm_429_falls_back(monkeypatch):
    calls = []

    def create(**kw):
        calls.append(1)
        raise RateLimitError("rate limited", response=httpx.Response(429, request=httpx.Request("POST", "http://x")), body=None)
    _llm_on(monkeypatch, create)
    out = convert_document(FILES["pdf"].read_bytes(), "pdf", True)
    assert len(calls) == llm_mod.ATTEMPTS
    assert out["trace"]["source"] == "heuristic" and "RateLimitError" in out["trace"]["reason"]
    assert check(out["form"]) == []


def test_heuristic_empty_text():
    from app.form_builder.fallback import heuristic_draft
    d = heuristic_draft("", "plik")
    assert d.title == "plik" and d.pages[0].sections[0].fields[0].type == "TEXTAREA"
