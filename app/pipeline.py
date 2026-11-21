"""Dokument -> hackcore.Document -> Draft (F-06: LLM, a w razie problemu heurystyka) -> JSON formularza COI -> walidacja."""
import re
from functools import lru_cache
from pathlib import Path

from hackcore import (IngestError, LLMClient, MissingAPIKey, MissingDependency, ModelRegistryError, Registry,
                      UnknownModel, load_document, load_registry, selected_model_id)

from app import approval, config
from app.form_builder.builder import build
from app.form_builder.cleanup import unsupported_statements
from app.form_builder.draft_llm import draft_summary, make_draft
from app.form_builder.draft_postprocess import paper_reason
from app.rules_check import check

__all__ = ["ConversionError", "IngestError", "UnknownModel", "convert_document", "registry"]
MODELS_FILE = Path(__file__).resolve().parents[1] / "config" / "models.yaml"  # X-09


class ConversionError(Exception):
    """Nie udało się zbudować poprawnego formularza -> 422."""


@lru_cache(maxsize=4)
def _llm(base_url: str, api_key: str, model: str) -> LLMClient | None:
    """Jeden klient na konfigurację (proces), nie na żądanie."""
    if not (base_url and api_key and model):
        return None
    return LLMClient(base_url, api_key, model)


@lru_cache(maxsize=1)
def registry() -> Registry:
    """Rejestr modeli X-09 (ładowany leniwie: zły YAML nie psuje trybu ze starymi LLM_*)."""
    return load_registry(MODELS_FILE)


def _select_llm(model_id: str | None) -> tuple[LLMClient | None, str | None, str]:
    """(klient, model do trace, powód braku LLM). Jawne id > LLM_MODEL_ID > stare LLM_BASE_URL/API_KEY/MODEL.

    Nieznane jawne id -> UnknownModel (API: 400); nieznane LLM_MODEL_ID to błąd konfiguracji serwera.
    """
    if model_id:
        registry().get(model_id)
    if mid := selected_model_id(model_id):
        try:
            base, key, model = registry().connection(mid)
        except MissingAPIKey as e:  # model istnieje, ale brak klucza -> heurystyka z powodem w trace
            return None, mid, str(e)
        except UnknownModel as e:
            raise ModelRegistryError(f"LLM_MODEL_ID: {e}") from e
        return _llm(base, key, model), mid, ""
    s = config.settings
    if not (s.llm_base_url and s.llm_api_key and s.llm_model):
        return None, None, "brak konfiguracji LLM"
    return _llm(s.llm_base_url, s.llm_api_key, s.llm_model), s.llm_model, ""


def _removed_from_notes(notes: list[str]) -> list[str]:
    """Pola usunięte przez tidy() (F-15) -> wpisy N-C4 „co zmieniliśmy przy cyfryzacji” z uzasadnieniem."""
    out = []
    for n in notes:
        if m := re.match(r"usunięto (pole|sekcję) '(.+)'", n):
            reason = paper_reason(m.group(2), "TEXT_FIELD") or "element formularza papierowego"
            out.append(f"{m.group(1).capitalize()} „{m.group(2)}” — pominięte; {reason}.")
    return out


TYPES = {"TEXT_FIELD": "pole tekstowe", "TEXTAREA": "pole opisowe", "CHECKBOX": "pola wyboru", "RADIO": "wybór jednej opcji",
         "SELECT": "lista rozwijana", "NUMBER": "liczba", "CONSENT_SECTION": "zgoda", "DATEPICKER": "data"}
INPUTS = set(TYPES) | {"FILE_UPLOADER"}
# dlaczego sekcja standardowa doszła, choć papier jej nie ma (pierwsze pasujące słowo w tytule)
WHY_ADDED = [("organ", "adresat wniosku z góry, obywatel nie musi go szukać"),
             ("podmiot", "wniosek w imieniu własnym, firmy albo innej osoby"),
             ("twoje dane", "dane z profilu zaufanego, bez przepisywania"),
             ("adres", "adres z rejestru, z gałęzią dla adresu za granicą"),
             ("innej osoby", "wniosek za inną osobę"), ("reprezentant", "dokument, że reprezentujesz podmiot"),
             ("pełnomocn", "pełnomocnik wg KPA (art. 32–33)"), ("opłat", "opłata skarbowa wg ustawy o opłacie skarbowej"),
             ("kontakt", "kontakt do szybkiego wyjaśnienia sprawy"), ("zgod", "klauzula informacyjna RODO (art. 13)")]


def _fields(qs: list):
    for q in qs:
        yield q["field"]
        yield from _fields(q["field"]["repeatingSectionGrid"])


def changes(form: dict, removed: list[str], notes: list[str]) -> dict:
    """N-C4: „JSON ma inną zawartość niż papier” — co system usunął, dodał ze standardu i poprawił, z uzasadnieniem."""
    tabs = form["tabs"]
    out = {"removed": [r for r in removed if "pominięt" in r], "improved": [r for r in removed if "pominięt" not in r],
           "added": [], "check": []}
    for n in notes:
        if m := re.match(r"usunięto (pole|sekcję) '(.+)' \(dubluje", n):
            out["removed"].append(f"{m.group(1).capitalize()} „{m.group(2)}” — zastąpione sekcją standardową COI (bez wpisywania danych dwa razy).")
        elif m := re.match(r"'(.+)': (\w+) -> (\w+)$", n):
            a, b = TYPES.get(m.group(2), m.group(2)), TYPES.get(m.group(3), m.group(3))
            out["improved"].append(f"„{m.group(1)}”: {b} zamiast: {a} (standard COI).")
        elif m := re.match(r"pole zbiorcze '(.+)' rozbite na grupę adresową", n):
            out["improved"].append(f"„{m.group(1)}” rozbite na Kraj, Ulicę, Numer budynku, Numer lokalu, Kod pocztowy i Miejscowość.")
        elif m := re.match(r"oświadczenie '(.+)' nie występuje w dokumencie", n):
            out["check"].append(f"Oświadczenie „{m.group(1)}” nie występuje w dokumencie — mogło zostać dopisane przez AI. "
                                "Jest nieobowiązkowe; usuń je albo potwierdź z oryginałem.")
        elif m := re.match(r"show_if: (nie znaleziono pola|pusta wartość warunku) '(.+)' dla '(.+)',", n):
            why = "takiego pola nie ma" if m.group(1) == "nie znaleziono pola" else "warunek nie ma wartości"
            out["check"].append(f"„{m.group(3)}” miało się pokazywać zależnie od „{m.group(2)}”, ale {why}. "
                                "Jest zawsze widoczne i nieobowiązkowe — sprawdź z oryginałem.")
    for t in (tabs[0], tabs[-2]):  # strony „Dane” i „Kontakt i zgody” z szablonów F-14
        for q in t["questions"]:
            title = q["field"]["title"]
            why = next((w for k, w in WHY_ADDED if k in title.lower()), "standard COI")
            out["added"].append(f"„{title}” — {why} (sekcja standardowa ze wzorców COI).")
    every = [f for t in tabs for f in _fields(t["questions"]) if f["type"] in INPUTS]
    doc = [f for t in tabs[1:-2] for f in _fields(t["questions"]) if f["type"] in INPUTS]
    out["summary"] = {
        "fields": len(every), "from_document": len(doc), "from_standard": len(every) - len(doc),
        "conditional": sum(bool(f["states"]) for t in tabs for f in _fields(t["questions"])),
        "prefilled": sum(f.get("defaultValueType") == "EXTERNAL_SYSTEM" for f in every),
        "removed": len(out["removed"]), "improved": len(out["improved"]),
    }
    return out


def _reason(result, no_llm: str) -> str:
    if result.source == "llm":
        return ""
    if no_llm:
        return no_llm
    return next((w for w in result.warnings if "heurystyk" in w), "")[:300]


def convert_document(data: bytes, ext: str, debug: bool, title_hint: str = "", model_id: str | None = None) -> dict:
    """model_id: id z config/models.yaml (np. `?model=`); None -> LLM_MODEL_ID albo stare LLM_* z env."""
    llm, model_label, no_llm = _select_llm(model_id)  # przed ingestem: nieznane id = szybki błąd
    try:
        doc = load_document(data, f"plik.{ext}")
    except MissingDependency as e:  # brak Tesseracta/LibreOffice -> 422 z komunikatem, co doinstalować
        raise IngestError(str(e)) from e
    result = make_draft(doc, llm)
    if title_hint and not doc.text.strip():  # pusty dokument: tytuł z nazwy pliku zamiast „Wniosek”
        result.draft.title = title_hint[:255]
    notes: list[str] = []
    unsupported_statements(result.draft, doc.text, notes)
    form = build(result.draft, notes)
    if errs := check(form):  # make_draft już to sprawdza — tu tylko bezpiecznik
        raise ConversionError(f"Formularz nie przeszedł walidacji: {'; '.join(errs[:5])}")
    # S-02: oznaczenie AI (art. 50) OBOK formularza — `form` zostaje czystym JSON-em zgodnym ze schematem
    extra = {"ai_disclosure": result.ai_disclosure} if result.ai_disclosure else {}
    if config.settings.approval_required:  # F-18: wynik jest DRAFT, dopóki urzędnik go nie zatwierdzi
        extra["approval"] = approval.issue(data, form, model_label, result.source, title_hint)
    if not debug:
        return {"form": form, **extra}
    removed = list(dict.fromkeys(result.removed_paper_elements + _removed_from_notes(notes)))
    return {"form": form, **extra, "draft": result.draft.model_dump(), "trace": {
        "source": result.source, "model": model_label, "reason": _reason(result, no_llm), "seconds": draft_summary(result)["seconds"],
        "text_chars": len(doc.text), "ocr_used": doc.ocr_used, "rules_errors": [],
        "cleanup": notes, "removed_paper_elements": removed, "warnings": result.warnings,
        "changes": changes(form, removed, notes)}}
