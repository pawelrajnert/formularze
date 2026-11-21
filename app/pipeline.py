"""Dokument -> hackcore.Document -> Draft (F-06: LLM, a w razie problemu heurystyka) -> JSON formularza COI -> walidacja."""
import re
from functools import lru_cache

from hackcore import IngestError, LLMClient, MissingDependency, load_document

from app import config
from app.form_builder.builder import build
from app.form_builder.draft_llm import draft_summary, make_draft
from app.form_builder.draft_postprocess import paper_reason
from app.rules_check import check

__all__ = ["ConversionError", "IngestError", "convert_document"]


class ConversionError(Exception):
    """Nie udało się zbudować poprawnego formularza -> 422."""


@lru_cache(maxsize=4)
def _llm(base_url: str, api_key: str, model: str) -> LLMClient | None:
    """Jeden klient na konfigurację (proces), nie na żądanie."""
    if not (base_url and api_key and model):
        return None
    return LLMClient(base_url, api_key, model)


def _removed_from_notes(notes: list[str]) -> list[str]:
    """Pola usunięte przez tidy() (F-15) -> wpisy N-C4 „co zmieniliśmy przy cyfryzacji” z uzasadnieniem."""
    out = []
    for n in notes:
        if m := re.match(r"usunięto (pole|sekcję) '(.+)'", n):
            reason = paper_reason(m.group(2), "TEXT_FIELD") or "element formularza papierowego"
            out.append(f"{m.group(1).capitalize()} „{m.group(2)}” — pominięte; {reason}.")
    return out


def _reason(result) -> str:
    if result.source == "llm":
        return ""
    if not (config.settings.llm_base_url and config.settings.llm_api_key and config.settings.llm_model):
        return "brak konfiguracji LLM"
    return next((w for w in result.warnings if "heurystyk" in w), "")[:300]


def convert_document(data: bytes, ext: str, debug: bool, title_hint: str = "") -> dict:
    try:
        doc = load_document(data, f"plik.{ext}")
    except MissingDependency as e:  # brak Tesseracta/LibreOffice -> 422 z komunikatem, co doinstalować
        raise IngestError(str(e)) from e
    s = config.settings
    result = make_draft(doc, _llm(s.llm_base_url, s.llm_api_key, s.llm_model))
    if title_hint and not doc.text.strip():  # pusty dokument: tytuł z nazwy pliku zamiast „Wniosek”
        result.draft.title = title_hint[:255]
    notes: list[str] = []
    form = build(result.draft, notes)
    if errs := check(form):  # make_draft już to sprawdza — tu tylko bezpiecznik
        raise ConversionError(f"Formularz nie przeszedł walidacji: {'; '.join(errs[:5])}")
    if not debug:
        return {"form": form}
    removed = list(dict.fromkeys(result.removed_paper_elements + _removed_from_notes(notes)))
    return {"form": form, "draft": result.draft.model_dump(), "trace": {
        "source": result.source, "reason": _reason(result), "seconds": draft_summary(result)["seconds"],
        "text_chars": len(doc.text), "ocr_used": doc.ocr_used, "rules_errors": [],
        "cleanup": notes, "removed_paper_elements": removed, "warnings": result.warnings}}
