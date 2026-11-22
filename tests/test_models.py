"""X-09: rejestr modeli (config/models.yaml) + wybór modelu. Bez sieci."""
import dataclasses
from pathlib import Path

import pytest

from app import config, pipeline
from hackcore import LLMClient
from hackcore.models import (MissingAPIKey, ModelRegistryError, UnknownModel, load_registry, select_client,
                             selected_model_id)

REAL = Path(__file__).resolve().parent.parent / "config" / "models.yaml"
BASE = """
  - id: a
    backend: mistral-api
    base_url: https://api.example/v1
    model: model-a
    api_key_env: [A_KEY, LLM_API_KEY]
    license: {lic}
    open_weights: {ow}
"""


def _write(tmp_path, body: str, default: str = "") -> Path:
    p = tmp_path / "models.yaml"
    p.write_text((f"default: {default}\n" if default else "") + "models:\n" + body, "utf-8")
    return p


def test_real_registry_loads_and_is_allowlisted():
    reg = load_registry(REAL, env={})
    assert reg.default == "ministral-14b-api" and len(reg.ids()) >= 3
    for spec in reg.models.values():
        assert spec.license in {"Apache-2.0", "MIT"} and spec.open_weights and spec.license_source


@pytest.mark.parametrize("lic", ["CC-BY-NC-4.0", "llama3", "gemma"])
def test_bad_license_rejected(tmp_path, lic):
    with pytest.raises(ModelRegistryError, match="allowlisty"):
        load_registry(_write(tmp_path, BASE.format(lic=lic, ow="true")))


def test_closed_weights_and_duplicate_rejected(tmp_path):
    with pytest.raises(ModelRegistryError, match="otwartymi wagami"):
        load_registry(_write(tmp_path, BASE.format(lic="Apache-2.0", ow="false")))
    with pytest.raises(ModelRegistryError, match="Zdublowane"):
        load_registry(_write(tmp_path, BASE.format(lic="MIT", ow="true") * 2))
    with pytest.raises(ModelRegistryError, match="default"):
        load_registry(_write(tmp_path, BASE.format(lic="MIT", ow="true"), default="nie-ma"))


def test_license_case_insensitive_and_key_fallback(tmp_path):
    reg = load_registry(_write(tmp_path, BASE.format(lic="apache-2.0", ow="true")), env={"LLM_API_KEY": "k2"})
    assert reg.get("a").license == "Apache-2.0"
    assert reg.connection("a") == ("https://api.example/v1", "k2", "model-a")
    reg.env = {"A_KEY": "k1", "LLM_API_KEY": "k2"}
    assert reg.connection("a")[1] == "k1"  # pierwsza niepusta z listy


def test_missing_key_is_clear_error_and_ollama_needs_none():
    reg = load_registry(REAL, env={})
    with pytest.raises(MissingAPIKey, match="SHERLOCK_API_KEY"):
        reg.client("pllum-12b-sherlock")
    c = reg.client("qwen3-4b-ollama")
    assert isinstance(c, LLMClient) and c.model == "qwen3:4b"
    reg.env = {"OLLAMA_BASE_URL": "http://localhost:11434/v1"}
    assert reg.connection("qwen3-4b-ollama")[:2] == ("http://localhost:11434/v1", "ollama")
    with pytest.raises(UnknownModel, match="Dostępne"):
        reg.get("gpt-4o")


def test_selection_env_first_then_legacy():
    env = {"LLM_MODEL_ID": "ministral-8b-api", "MISTRAL_API_KEY": "secret",
           "LLM_BASE_URL": "http://legacy/v1", "LLM_API_KEY": "old", "LLM_MODEL": "legacy-model"}
    reg = load_registry(REAL, env=env)
    assert selected_model_id(None, env) == "ministral-8b-api"
    assert select_client(reg).model == "ministral-8b-latest"
    assert select_client(reg, "qwen3-8b-ollama").model == "qwen3:8b"  # jawne id > env
    legacy = {k: v for k, v in env.items() if k != "LLM_MODEL_ID"}
    reg.env = legacy
    assert selected_model_id(None, legacy) is None
    assert select_client(reg).model == "legacy-model"
    reg.env = {}
    assert select_client(reg) is None  # brak konfiguracji = tryb bez LLM


def test_public_has_no_secrets():
    reg = load_registry(REAL, env={"MISTRAL_API_KEY": "sekretny-klucz", "SHERLOCK_API_KEY": "inny-sekret"})
    pub = reg.public(probe=lambda url: False)
    text = repr(pub)
    assert "sekret" not in text and "api_key" not in text and "base_url" not in text
    by_id = {m["id"]: m for m in pub}
    assert by_id["ministral-14b-api"]["default"] and by_id["ministral-14b-api"]["configured"]
    assert by_id["pllum-12b-sherlock"]["license"] == "Apache-2.0"


def test_public_ollama_configured_only_when_server_answers():
    """R-05: Ollama nie potrzebuje klucza, więc „configured” = serwer odpowiada; sondujemy raz na adres."""
    reg = load_registry(REAL, env={})
    asked = []
    pub = {m["id"]: m for m in reg.public(probe=lambda url: asked.append(url) or False)}
    assert pub["ministral-14b-ollama"]["configured"] is False
    assert len(asked) == len(set(asked)) == 1          # wszystkie wpisy Ollamy mają ten sam adres
    pub = {m["id"]: m for m in reg.public(probe=lambda url: True)}
    assert pub["qwen3-4b-ollama"]["configured"] is True
    assert pub["ministral-14b-api"]["configured"] is False   # brak klucza w env


def test_unexpected_draft_error_logs_without_document_text(caplog):
    """R-05: nieoczekiwany błąd szkicu nie trafia do logu z treścią dokumentu (PII)."""
    import logging
    from app.form_builder import draft_llm
    from hackcore import Document

    class Boom:
        model = "m"
        def complete_model(self, *a, **k):
            raise ValueError("input_value='Jan Kowalski PESEL 44051401359'")

    with caplog.at_level(logging.DEBUG, logger=draft_llm.log.name):
        res = draft_llm.make_draft(Document.from_pages(["Wniosek\nImię: ....."], "pdf"), Boom(), compliance=False)
    assert res.source == "heuristic"
    assert "Kowalski" not in caplog.text and "44051401359" not in caplog.text
    assert "ValueError" in caplog.text


# --- pipeline ---

@pytest.fixture
def no_llm_env(monkeypatch):
    monkeypatch.setattr(config, "settings", dataclasses.replace(config.settings, llm_base_url="", llm_api_key="", llm_model=""))
    for k in ("LLM_MODEL_ID", "SHERLOCK_API_KEY", "MISTRAL_API_KEY"):
        monkeypatch.delenv(k, raising=False)


def test_pipeline_unknown_model_id(no_llm_env):
    with pytest.raises(UnknownModel):
        pipeline.convert_document(b"x", "txt", True, model_id="gpt-4o")


def test_pipeline_select_llm(no_llm_env, monkeypatch):
    seen = []
    monkeypatch.setattr(pipeline, "_llm", lambda *a: seen.append(a) or "client")
    assert pipeline._select_llm(None) == (None, None, "brak konfiguracji LLM")  # stare zachowanie
    llm, label, reason = pipeline._select_llm("pllum-12b-sherlock")
    assert llm is None and label == "pllum-12b-sherlock" and "SHERLOCK_API_KEY" in reason
    monkeypatch.setenv("LLM_MODEL_ID", "ministral-8b-ollama")
    assert pipeline._select_llm(None) == ("client", "ministral-8b-ollama", "")
    assert seen[-1] == ("http://ollama:11434/v1", "ollama", "ministral-3:8b")
    monkeypatch.setenv("LLM_MODEL_ID", "nie-ma")
    with pytest.raises(ModelRegistryError, match="LLM_MODEL_ID"):
        pipeline._select_llm(None)
    monkeypatch.delenv("LLM_MODEL_ID")
    monkeypatch.setattr(config, "settings", dataclasses.replace(config.settings, llm_base_url="http://x", llm_api_key="k", llm_model="m"))
    assert pipeline._select_llm(None) == ("client", "m", "")  # wsteczna zgodność bez LLM_MODEL_ID


def test_pipeline_trace_has_model(no_llm_env):
    pdf = next((REAL.parent.parent / "data" / "1").glob("1.*/*.pdf"))
    out = pipeline.convert_document(pdf.read_bytes(), "pdf", True, model_id="pllum-12b-sherlock")
    assert out["trace"]["model"] == "pllum-12b-sherlock" and out["trace"]["source"] == "heuristic"
    assert "SHERLOCK_API_KEY" in out["trace"]["reason"]
    assert "model" not in pipeline.convert_document(pdf.read_bytes(), "pdf", False)  # czysty JSON bez trace
