"""Pipeline end-to-end: hackcore ingest -> make_draft (F-06) -> build (F-07 + tidy F-15) -> rules_check."""
import dataclasses
import json
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config, pipeline
from app.main import app
from app.pipeline import convert_document
from app.rules_check import check
from hackcore import LLMError
from hackcore.ingest.tools import find_soffice, find_tesseract

DIR = next((Path(__file__).resolve().parent.parent / "data" / "1").glob("1.*"))
NAME = "Wniosek o ustalenie numeru porządkowego nieruchomości"
FILES = {e: DIR / f"{NAME}.{e}" for e in ("pdf", "docx", "doc", "ods", "xlsx", "jpg", "jpeg")} | {"png": DIR / f"{NAME} (1).png"}
DRAFT = json.loads((Path(__file__).parent / "fixtures" / "draft_form1.json").read_text("utf-8"))

TESS = find_tesseract()
LANGS = subprocess.run([TESS, "--list-langs"], capture_output=True, text=True).stdout.split() if TESS else []
SOFFICE = find_soffice()
NEEDS = {"doc": SOFFICE, "ods": SOFFICE, "jpg": TESS, "jpeg": TESS, "png": TESS}
client = TestClient(app)


class FakeLLM:
    def __init__(self, response):
        self.response, self.calls = response, 0

    def complete_model(self, system, user, model_cls, coerce=None):
        self.calls += 1
        if isinstance(self.response, Exception):
            raise self.response
        return model_cls.model_validate(coerce(self.response) if coerce else self.response)


@pytest.fixture(autouse=True)
def env(monkeypatch):
    s = dataclasses.replace(config.settings, auth_enabled=False, llm_base_url="", llm_api_key="", llm_model="")
    monkeypatch.setattr(config, "settings", s)
    monkeypatch.setenv("OCR_LANG", "pol" if "pol" in LANGS else "eng")  # lokalnie bywa tylko eng; Docker ma pol


def _llm_on(monkeypatch, fake):
    monkeypatch.setattr(config, "settings", dataclasses.replace(config.settings, llm_base_url="http://x", llm_api_key="k", llm_model="m"))
    monkeypatch.setattr(pipeline, "_llm", lambda *a: fake)


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


def test_llm_draft_used(monkeypatch):
    fake = FakeLLM(DRAFT)
    _llm_on(monkeypatch, fake)
    out = convert_document(FILES["pdf"].read_bytes(), "pdf", True)
    assert out["trace"]["source"] == "llm" and check(out["form"]) == [] and fake.calls == 1
    assert out["form"]["title"] == DRAFT["title"]
    assert out["trace"]["removed_paper_elements"]  # N-C4: co zmieniliśmy przy cyfryzacji


def test_llm_error_falls_back(monkeypatch):
    _llm_on(monkeypatch, FakeLLM(LLMError("429 po 3 próbach")))
    out = convert_document(FILES["pdf"].read_bytes(), "pdf", True)
    assert out["trace"]["source"] == "heuristic" and "429" in out["trace"]["reason"]
    assert check(out["form"]) == []


def test_heuristic_empty_text_still_valid():
    from app.form_builder.draft_llm import make_draft
    from hackcore import Document
    r = make_draft(Document.from_pages([""], "pdf"), None)
    assert r.source == "heuristic" and check(pipeline.build(r.draft)) == []


def test_llm_client_cached_per_config():
    pipeline._llm.cache_clear()
    assert pipeline._llm("", "", "") is None
    a, b = pipeline._llm("http://x/v1", "k", "m"), pipeline._llm("http://x/v1", "k", "m")
    assert a is b and a.model == "m"


def test_changes_summary_n_c4():
    """N-C4: „co zmieniliśmy względem papieru” w trace — usunięte, dodane ze standardu, poprawione, do sprawdzenia."""
    out = convert_document(FILES["docx"].read_bytes(), "docx", True)
    form = out["form"]
    ch = pipeline.changes(form, ["Podpis — pominięty: podpis elektroniczny.", "Pole zbiorcze „A” rozbite na: B, C."], [
        "usunięto sekcję 'Twoje dane' (dubluje sekcję standardową)", "'Kwota': TEXT_FIELD -> NUMBER",
        "pole zbiorcze 'Adres psa' rozbite na grupę adresową",
        "show_if: nie znaleziono pola 'Rodzaj' dla 'Dane trenera', warunek pominięty, zdjęto REQUIRED"])
    assert len(ch["removed"]) == 2 and "zastąpione sekcją standardową" in ch["removed"][1]
    assert ch["improved"][1] == "„Kwota”: liczba zamiast: pole tekstowe (standard COI)." and len(ch["improved"]) == 3
    assert any("profilu zaufanego" in a for a in ch["added"]) and any("RODO" in a for a in ch["added"])
    assert "„Dane trenera”" in ch["check"][0]
    s = ch["summary"]
    assert s["fields"] == s["from_document"] + s["from_standard"] and s["from_standard"] > 0 and s["prefilled"] > 0
    assert out["trace"]["changes"]["summary"]["fields"] == s["fields"]
