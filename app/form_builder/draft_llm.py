"""F-06: Document (tekst formularza papierowego) -> Draft (kontrakt app/form_builder/draft.py) przez LLM.

make_draft(doc, llm) -> DraftResult — nigdy nie rzuca: przy braku LLM / LLMError / pustym wyniku -> heurystyka.

Kroki:
1. Kompresja tekstu (kropki „……” -> „…”, białe znaki, długa klauzula RODO skrócona) — oszczędza tokeny
   (darmowy Mistral: 40k tokenów/min, 2 req/min).
2. Prompt: zasady standardu COI + few-shot formularza 1 (tekst -> szkic, JSON bez wcięć).
3. Długi dokument: podział po stronach na max MAX_CHUNKS części (część 1 = cały szkic, kolejne = tylko strony
   „przedmiotu wniosku”), scalenie przed stroną „Kontakt z urzędem”. Nadmiar ucinamy z ostrzeżeniem.
4. Post-processing deterministyczny (draft_postprocess) + kontrola rules_check(build(draft)); gdy coś nie gra -> heurystyka.
"""
import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, get_args

from hackcore import Document, LLMClient, LLMError

from app.form_builder.builder import build
from app.form_builder.draft import Dictionary, Draft, FieldType, Validator
from app.form_builder.draft_heuristic import heuristic_draft
from app.form_builder.draft_postprocess import paper_elements_in_text, postprocess
from app.rules_check import check

log = logging.getLogger(__name__)

FEWSHOT = Path(__file__).resolve().parents[2] / "config" / "fewshot"  # wspólne z P (Dockerfile kopiuje config/)
MAX_CHUNK_CHARS = 18_000  # ~6-7k tokenów PL; + prompt ~4k + odpowiedź ~6k < 40k/min
MAX_CHUNKS = 2            # 2 req/min na darmowym planie
CLAUSE_KEEP_CHARS = 400

SYSTEM_RULES = """Jesteś projektantem e-formularzy mObywatel (Generator Formularzy COI). Zamieniasz tekst papierowego formularza urzędowego na szkic formularza elektronicznego w JSON.

STRUKTURA (w tej kolejności):
1. Strona „Dane”:
   - sekcja „Organ, do którego jest składany wniosek” (pole „Nazwa organu”) albo „Urząd, do którego jest składany wniosek” (pole „Nazwa urzędu”, gdy adresatem jest urząd): TEXT_FIELD, read_only=true, required=false, default = adresat z dokumentu (nazwa + adres).
   - „Podmiot wniosku” — tylko gdy wolno działać w czyimś imieniu: RADIO „Wybierz, w czyim imieniu wnioskujesz” (opcje dobierz do formularza spośród: Swoim / Innej osoby / Osoby prawnej lub jednostki organizacyjnej) i RADIO „Wybierz, jako kto wnioskujesz” (Pełnomocnik / Reprezentant) z show_if.
   - „Twoje dane” (Imię, Nazwisko; Numer PESEL z walidatorem PESEL tylko gdy dokument wymaga PESEL), adresy według wzoru z przykładu (Kraj SELECT Polska/Inny kraj, kod pocztowy z ZIP_CODE przy Polsce), oraz — jeśli formularz ich wymaga — „Dane innej osoby”, „Dane podmiotu” (Nazwa, NIP, REGON, Numer KRS), „Pełnomocnictwo”, „Opłata skarbowa” z show_if jak w przykładzie.
2. Strony „przedmiotu wniosku” (1 lub więcej, nazwane od treści, np. „Informacje o budynku”): WSZYSTKIE pola merytoryczne z dokumentu, pogrupowane w tematyczne sekcje. Niczego nie pomijaj i nie wymyślaj pól, których w dokumencie nie ma.
3. Przedostatnia strona „Kontakt z urzędem”: sekcja „Dane do kontaktu” (Numer telefonu, Adres e-mail z EMAIL; oba required=false) i sekcja „Zgoda” / „Oświadczenie” / „Zgody i oświadczenia” z polami CONSENT_SECTION (jedno pole = jedno krótkie oświadczenie lub zgoda; label = treść). Pełnej klauzuli RODO nie przepisuj — wystarczy krótka zgoda z nazwą administratora i kontaktem do IOD.
Strony końcowej (podgląd) NIE dodawaj — robi to system.

TYPY PÓL: TEXT_FIELD krótki tekst; TEXTAREA uzasadnienie/opis; NUMBER liczby i kwoty; DATEPICKER daty; RADIO jeden wybór (2–5 opcji); CHECKBOX wiele wyborów (2–5 opcji); SELECT lista >5 opcji; FILE_UPLOADER każdy załącznik z listy załączników osobno; CONSENT_SECTION oświadczenia i zgody (nigdy CHECKBOX); TEXT_BLOCK krótka informacja bez pola (np. kwota opłaty, numer konta).
- options tylko dla SELECT/RADIO/CHECKBOX. „Niepotrzebne skreślić”, kratki ☐ → RADIO/CHECKBOX z tymi opcjami.
- Tabela z wieloma pustymi wierszami (lista osób, działek, pojazdów) → jedna sekcja repeating=true z polami-kolumnami.
- required=true gdy pole jest obowiązkowe lub ma gwiazdkę *; dane wnioskodawcy zwykle obowiązkowe; inaczej false.
- validators: PESEL, NIP, REGON, EMAIL, ZIP_CODE, EPUAP, ADE, SERIAL_NUMBER_ID_CARD — gdy pole tego dotyczy.
- dictionary i prefill: zostaw puste, chyba że masz pewność (system sam rozpozna typowe pola po etykiecie). prefill TYLKO dla danych samego wnioskodawcy („Twoje dane”), nigdy dla innej osoby, pełnomocnika czy osoby odpowiedzialnej; „Imię i nazwisko” w jednym polu — bez prefill.
- show_if: {"field": dokładny label pola wyboru (RADIO/SELECT/CHECKBOX) zdefiniowanego WCZEŚNIEJ, "equals": dokładnie jedna z jego opcji}. Używaj dla pól zależnych (np. „jeśli tak, podaj…”, Polska/zagranica, osoba fizyczna/firma).

ZALEŻNOŚCI (show_if) — formularz elektroniczny pokazuje tylko to, co dotyczy wnioskodawcy. Stosuj zawsze te wzorce:
- „Jeśli tak / jeżeli tak / w przypadku odpowiedzi twierdzącej, podaj…” → wcześniej RADIO z pytaniem (opcje Tak/Nie), a pole zależne z show_if equals „Tak” (analogicznie „Nie”).
- Alternatywy „niepotrzebne skreślić” / kratki, po których są różne pola (np. sposób zwrotu: przelew → numer konta; odbiór osobiście → brak pól) → RADIO + show_if na polach każdej opcji.
- Adres: Kraj (SELECT Polska/Inny kraj); Województwo, Kod pocztowy i pola krajowe z show_if Kraj = Polska; pola zagraniczne z show_if Kraj = Inny kraj.
- Podmiot wniosku: sekcje „Dane innej osoby”, „Pełnomocnictwo” z show_if „Wybierz, w czyim imieniu wnioskujesz” = „Innej osoby”; „Dane podmiotu”, „Adres siedziby” = „Osoby prawnej lub jednostki organizacyjnej”.
- Osoba fizyczna / firma, właściciel / najemca itp. → RADIO + show_if na sekcjach właściwych dla każdej opcji.
- Listy „kolejne / dodatkowe / pozostałe / współwłaściciele / członkowie” (np. „Dodatkowe psy”) → sekcja repeating=true.

POMIJASZ (elementy papierowe): podpis, pieczęć, miejscowość i data wypełnienia, „wypełnić drukowanymi literami/czytelnie”, „niepotrzebne skreślić”, pola „wypełnia urząd”, numery stron, przypisy techniczne.

JĘZYK: prosty, druga osoba liczby pojedynczej, krótkie etykiety (np. „Numer telefonu”, „Uzasadnienie”), bez wersalików. Nie używaj: dokonać, posiadać, pragnąć, informujemy, imiesłowów na -ąc, form bezosobowych („naliczono”), form zależnych od płci. Trudne terminy objaśnij w hint.
TYTUŁ: zaczyna się od „Wniosek”, „Zgłoszenie”, „Deklaracja” lub „Oświadczenie”, potem czego dotyczy; krótki, bez odwołań do przepisów prawa, max 255 znaków. Przedmiot wniosku przepisz DOKŁADNIE słowami z tytułu dokumentu (nie zamieniaj np. „nieruchomości” na „budynku”).
finish_text: zawsze pusty (stronę końcową z podglądem robi system)."""

CONTINUATION = """To jest CZĘŚĆ {i} z {n} tego samego dokumentu (kontynuacja). Zwróć szkic tylko z pól, które występują w TEJ części:
- strony przedmiotu wniosku (bez strony „Dane” z sekcjami standardowymi i bez strony „Kontakt z urzędem”),
- oświadczenia z tej części umieść na stronie „Kontakt z urzędem” w sekcji „Zgody i oświadczenia”.
title wpisz: {title}"""


@dataclass
class DraftResult:
    draft: Draft
    source: Literal["llm", "heuristic"]
    removed_paper_elements: list[str] = field(default_factory=list)  # N-C4: co pominięto przy cyfryzacji + dlaczego
    warnings: list[str] = field(default_factory=list)
    seconds: float = 0.0


# --- naprawa surowego JSON-a od LLM (port clean() z llm_draft.py Pawła) ----------------------------------------
def _txt(v) -> str:
    if v is None:
        return ""
    if isinstance(v, list):
        return ", ".join(_txt(x) for x in v if x is not None)
    if isinstance(v, dict):
        return _txt(v.get("name") or v.get("label") or v.get("value") or "")
    return str(v)


def _fix_show_if(o: dict) -> None:
    si = o.get("show_if")
    if not isinstance(si, dict) or not si.get("field"):
        o["show_if"] = None
        return
    eq = si.get("equals")
    si["field"] = _txt(si["field"])
    si["equals"] = "Tak" if eq is True else "Nie" if eq is False else _txt(eq[0] if isinstance(eq, list) and eq else eq)


def coerce_draft(d: dict) -> dict:
    """Jeden zły enum/typ nie zabija szkicu: nieznane wartości -> domyślne, listy/liczby -> tekst, puste sekcje out."""
    d = dict(d)
    d["title"] = _txt(d.get("title"))[:255]
    if isinstance(ft := d.get("finish_text"), dict):  # bywa {"type": "TEXT_BLOCK", "content": ...}
        d["finish_text"] = "\n".join(str(v) for k, v in ft.items() if k != "type")
    elif not isinstance(ft, str):
        d["finish_text"] = _txt(ft)
    pages = []
    for page in d.get("pages") or []:
        if not isinstance(page, dict):
            continue
        page["title"] = _txt(page.get("title"))
        sections = []
        for sec in page.get("sections") or []:
            if not isinstance(sec, dict):
                continue
            sec["title"] = _txt(sec.get("title"))
            sec["repeating"] = bool(sec.get("repeating"))
            sec["fields"] = [f for f in sec.get("fields") or [] if isinstance(f, dict) and _txt(f.get("label"))]
            _fix_show_if(sec)
            for f in sec["fields"]:
                f["validators"] = [v for v in f.get("validators") or [] if v in get_args(Validator)]
                if f.get("dictionary") not in get_args(Dictionary):
                    f["dictionary"] = ""
                if f.get("type") not in get_args(FieldType):
                    f["type"] = "TEXT_FIELD"
                for k in ("label", "hint", "default", "prefill"):  # bywa lista / liczba / bool zamiast tekstu
                    if k in f:
                        f[k] = _txt(f[k])
                f["required"] = bool(f.get("required"))
                f["read_only"] = bool(f.get("read_only"))
                f["options"] = [_txt(o) for o in f.get("options") or [] if _txt(o)]
                _fix_show_if(f)
            if sec["fields"]:
                sections.append(sec)
        page["sections"] = sections
        if sections:
            pages.append(page)
    d["pages"] = pages
    return d


# --- tekst -----------------------------------------------------------------------------------------------------
_LEADERS = re.compile(r"(?:[.…_][ \t]?){4,}|…{2,}")
_CLAUSE_HEAD = re.compile(r"klauzul\w*\s+informacyjn|informacj\w*\s+o\s+przetwarzaniu\s+danych", re.I)


def compress(text: str) -> str:
    """Mniej tokenów, ta sama treść: kropki/podkreślenia -> „…”, białe znaki, skrócona klauzula RODO."""
    t = _LEADERS.sub("…", text or "")
    t = re.sub(r"[ \t ]+", " ", t)
    t = re.sub(r"[ \t]*\n[ \t]*", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    if m := _CLAUSE_HEAD.search(t):  # klauzula RODO bywa ~3k znaków; do szkicu wystarczy początek (administrator, IOD)
        rest = t[m.end():]
        iod = re.search(r"[^\n]*\b(iod|inspektor\w*)\b[^\n]*", rest, re.I)
        tail = rest[:CLAUSE_KEEP_CHARS] + ("\n" + iod.group(0)[:200] if iod and iod.start() > CLAUSE_KEEP_CHARS else "")
        if len(rest) > CLAUSE_KEEP_CHARS + 200:
            t = t[:m.end()] + tail + "\n[… dalsza treść klauzuli RODO pominięta …]"
    return t.strip()


def chunks(doc: Document, limit: int = MAX_CHUNK_CHARS, max_chunks: int = MAX_CHUNKS) -> tuple[list[str], bool]:
    """Strony dokumentu (skompresowane) sklejone w części ≤ limit. Zwraca (części, czy_ucięto)."""
    pages = [compress(p) for p in (doc.pages or [doc.text])]
    pages = [p for p in pages if p] or [compress(doc.text)]
    parts: list[str] = []
    for p in pages:
        while len(p) > limit:  # pojedyncza gigantyczna strona -> tniemy po liniach
            cut = p.rfind("\n", 0, limit)
            cut = cut if cut > limit // 2 else limit
            parts.append(p[:cut])
            p = p[cut:].lstrip()
        if parts and len(parts[-1]) + len(p) + 2 <= limit:
            parts[-1] += "\n\n" + p
        else:
            parts.append(p)
    return parts[:max_chunks], len(parts) > max_chunks


def system_prompt() -> str:
    example_text = compress((FEWSHOT / "form1.txt").read_text("utf-8"))
    example_draft = json.dumps(json.loads((FEWSHOT / "form1_draft.json").read_text("utf-8")),
                               ensure_ascii=False, separators=(",", ":"))
    return (f"{SYSTEM_RULES}\n\nPRZYKŁAD — tekst formularza:\n<<<\n{example_text}\n>>>\n"
            f"Poprawny szkic dla przykładu:\n{example_draft}")


def user_prompt(doc: Document, part: str, i: int = 1, n: int = 1, title: str = "") -> str:
    head = f"Tekst formularza (format: {doc.source_format}{', z OCR — mogą być błędy rozpoznania' if doc.ocr_used else ''}):"
    if i > 1:
        head = CONTINUATION.format(i=i, n=n, title=title or "jak w części 1") + "\n\n" + head
    elif n > 1:
        head = f"To jest CZĘŚĆ 1 z {n} dokumentu — zwróć pełny szkic (strona „Dane”, przedmiot wniosku, „Kontakt z urzędem”).\n\n" + head
    return f"{head}\n<<<\n{part}\n>>>"


# --- scalanie części -------------------------------------------------------------------------------------------
def _is_contact(title: str) -> bool:
    return bool(re.search(r"kontakt", title, re.I))


def merge(main: Draft, extra: Draft) -> Draft:
    """Strony z części 2+ wstawiamy przed „Kontakt z urzędem”; strony o tym samym tytule scalamy (sekcje dopisujemy)."""
    d = main.model_dump()
    pages = d["pages"]
    contact_idx = next((k for k, p in enumerate(pages) if _is_contact(p["title"])), len(pages))
    for page in extra.model_dump()["pages"]:
        same = next((p for p in pages if p["title"].casefold() == page["title"].casefold()), None)
        if same is not None:
            have = {s["title"].casefold() for s in same["sections"]}
            for s in page["sections"]:
                if s["title"].casefold() in have:
                    target = next(x for x in same["sections"] if x["title"].casefold() == s["title"].casefold())
                    labels = {f["label"] for f in target["fields"]}
                    target["fields"] += [f for f in s["fields"] if f["label"] not in labels]
                else:
                    same["sections"].append(s)
        else:
            pages.insert(contact_idx, page)
            contact_idx += 1
    if not d.get("finish_text") and extra.finish_text:
        d["finish_text"] = extra.finish_text
    return Draft.model_validate(d)


# --- główne API ------------------------------------------------------------------------------------------------
def _llm_draft(doc: Document, llm: LLMClient, warnings: list[str]) -> Draft:
    parts, truncated = chunks(doc)
    if truncated:
        warnings.append(f"Dokument bardzo długi — do LLM poszły pierwsze {len(parts)} części po ≤{MAX_CHUNK_CHARS} znaków; reszta pominięta.")
    system = system_prompt()
    draft = llm.complete_model(system, user_prompt(doc, parts[0], 1, len(parts)), Draft, coerce=coerce_draft)
    for i, part in enumerate(parts[1:], 2):
        try:
            extra = llm.complete_model(system, user_prompt(doc, part, i, len(parts), draft.title), Draft, coerce=coerce_draft)
            draft = merge(draft, extra)
        except LLMError as e:  # część 1 już jest — lepszy niepełny szkic LLM niż heurystyka
            warnings.append(f"Część {i}/{len(parts)} dokumentu nieprzetworzona przez LLM ({e}); pola z niej mogą brakować.")
    return draft


def _finalize(draft: Draft, removed: list[str], warnings: list[str]) -> Draft | None:
    fixed = postprocess(draft, removed, warnings)
    if fixed is None:
        return None
    errs = check(build(fixed))
    if errs:
        warnings.append("Szkic nie przeszedł kontroli reguł: " + "; ".join(errs[:5]))
        return None
    return fixed


def make_draft(doc: Document, llm: LLMClient | None) -> DraftResult:
    t0 = time.perf_counter()
    warnings: list[str] = []
    removed = paper_elements_in_text(doc.text)
    if not (doc.text or "").strip():
        warnings.append("Dokument nie zawiera tekstu (pusty lub nierozpoznany) — szkic minimalny do ręcznego uzupełnienia.")
    elif llm is None:
        warnings.append("LLM nie jest skonfigurowany (LLM_BASE_URL/LLM_MODEL) — szkic z heurystyki.")
    else:
        try:
            llm_removed = list(removed)
            if (draft := _finalize(_llm_draft(doc, llm, warnings), llm_removed, warnings)) is not None:
                return DraftResult(draft, "llm", llm_removed, warnings, time.perf_counter() - t0)
            warnings.append("LLM zwrócił pusty lub niepoprawny szkic — użyto heurystyki.")
        except LLMError as e:
            warnings.append(f"LLM niedostępny ({e}) — szkic z heurystyki.")
        except Exception as e:  # noqa: BLE001 — API nie może dać 500 przez LLM
            log.exception("Nieoczekiwany błąd szkicu LLM")
            warnings.append(f"Błąd szkicu LLM ({type(e).__name__}: {e}) — szkic z heurystyki.")

    draft, h_removed = heuristic_draft(doc)
    removed = list(dict.fromkeys(removed + h_removed))
    final = _finalize(draft, removed, warnings)
    if final is None:  # nie powinno się zdarzyć — heurystyka zawsze dokłada sekcje standardowe
        final = _finalize(heuristic_draft(Document.from_pages([""], doc.source_format))[0], removed, warnings)
    return DraftResult(final, "heuristic", removed, warnings, time.perf_counter() - t0)


def draft_summary(result: DraftResult) -> dict:
    """Do trybu debug / trace w API."""
    fields = [f for p in result.draft.pages for s in p.sections for f in s.fields]
    return {"source": result.source, "seconds": round(result.seconds, 2), "pages": len(result.draft.pages),
            "fields": len(fields), "removed_paper_elements": result.removed_paper_elements, "warnings": result.warnings}


if __name__ == "__main__":  # podgląd promptu: python -m app.form_builder.draft_llm
    print(json.dumps({"system_chars": len(system_prompt())}, ensure_ascii=False))
