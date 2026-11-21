"""Dokument -> tekst -> Draft (LLM, a w razie problemu heurystyka) -> JSON formularza COI -> walidacja."""
from app import config
from app.form_builder.builder import build
from app.form_builder.fallback import heuristic_draft
from app.form_builder.llm_draft import llm_draft
from app.ingest import extract_text
from app.rules_check import check


class ConversionError(Exception):
    """Nie udało się zbudować poprawnego formularza -> 422."""


def convert_document(data: bytes, ext: str, debug: bool, title_hint: str = "") -> dict:
    text = extract_text(data, ext)
    s = config.settings
    draft, reason, errs, notes = None, "", [], []
    if not (s.llm_base_url and s.llm_api_key and s.llm_model):
        reason = "brak konfiguracji LLM"
    else:
        try:
            draft = llm_draft(text)
            form = build(draft, notes)
            errs = check(form)  # w trace zostają błędy szkicu LLM, nawet po fallbacku
            if errs:
                reason, draft = f"walidacja odrzuciła szkic LLM ({len(errs)} błędów)", None
        except Exception as e:  # 429, timeout, zły JSON, pusty szkic -> heurystyka
            reason, draft = f"LLM: {type(e).__name__}: {e}"[:300], None
    source = "llm" if draft else "heuristic"
    if draft is None:
        draft, notes = heuristic_draft(text, title_hint), []
        form = build(draft, notes)
        if h_errs := check(form):
            raise ConversionError(f"Formularz nie przeszedł walidacji: {'; '.join(h_errs[:5])}")
    if not debug:
        return {"form": form}
    return {"form": form, "draft": draft.model_dump(), "trace": {
        "source": source, "reason": reason, "text_chars": len(text), "rules_errors": errs, "cleanup": notes}}
