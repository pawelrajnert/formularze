"""F-06: szkic z LLM (fałszywy klient), post-processing, fallback heurystyczny na formularzach 1..9."""
import json
from pathlib import Path

import pytest

from app.form_builder.builder import build
from app.form_builder.draft import Draft
from app.form_builder.draft_heuristic import heuristic_draft
from app.form_builder.draft_llm import (
    MAX_CHUNK_CHARS, DraftResult, chunks, coerce_draft, compress, make_draft, merge, system_prompt, user_prompt,
)
from app.form_builder.draft_postprocess import normalize_title, postprocess
from app.rules_check import check
from hackcore import Document, LLMError

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "draft_form1.json"
DATA = ROOT / "data"


class FakeLLM:
    """Podmiana LLMClient: zwraca kolejne odpowiedzi (dict -> Draft) albo rzuca podany wyjątek."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    def complete_model(self, system, user, model_cls, coerce=None):
        self.calls.append((system, user))
        r = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(r, Exception):
            raise r
        return model_cls.model_validate(coerce(r) if coerce else r)


def fixture_dict() -> dict:
    return json.loads(FIXTURE.read_text("utf-8"))


def doc_of(text: str) -> Document:
    return Document.from_pages(text.split("\n\f\n"), "pdf")


def fields(d: Draft):
    return [f for p in d.pages for s in p.sections for f in s.fields]


def assert_valid(r: DraftResult):
    assert r.draft.pages and all(p.sections for p in r.draft.pages) and fields(r.draft)
    assert check(build(r.draft)) == []


def small(**over) -> dict:
    base = {"title": "Wniosek o test", "pages": [{"title": "Dane", "sections": [{"title": "Sekcja", "fields": [
        {"label": "Imię", "type": "TEXT_FIELD", "required": True}]}]}]}
    base["pages"][0]["sections"][0]["fields"] += over.pop("extra", [])
    return base | over


# --- prompt / kontrakt --------------------------------------------------------------------------------------
def test_fewshot_copy_in_sync_with_fixture():
    # F-14: few-shot = strona merytoryczna fixture'a (szkic starego promptu) + pola sterujące
    copy = json.loads((ROOT / "config/fewshot/form1_draft.json").read_text("utf-8"))
    fx = fixture_dict()
    assert copy["title"] == fx["title"] and copy["organ"] and copy["applicant_kinds"]
    assert copy["pages"] == [p for p in fx["pages"] if p["title"] == "Informacje o budynku"]


def test_coerce_draft_fixes_bad_values():
    # port testów clean() z llm_draft.py (P): złe enumy, listy/liczby zamiast tekstu, puste sekcje
    raw = {"title": "T", "finish_text": {"type": "TEXT_BLOCK", "content": "RODO"}, "pages": [
        {"title": "Pusta", "sections": [{"title": "S", "fields": []}]},
        {"title": "Dane", "sections": [{"title": "S", "show_if": {"field": "Pełnomocnik", "equals": True}, "fields": [
            {"label": "Pełnomocnik", "type": "RADIO", "options": ["Tak", 2], "default": ["Tak"]},
            {"label": "Kwota", "type": "NUMBER", "default": 17, "show_if": {"field": "Pełnomocnik", "equals": ["Tak"]}},
            {"label": "Telefon", "type": "PHONE", "validators": ["PHONE", "EMAIL"], "dictionary": "Miasta"},
            "śmieć"]}]}]}
    d = Draft.model_validate(coerce_draft(raw))
    s = d.pages[0].sections[0]
    assert d.finish_text == "RODO" and len(d.pages) == 1 and s.show_if.equals == "Tak"
    assert [f.default for f in s.fields[:2]] == ["Tak", "17"] and s.fields[0].options == ["Tak", "2"]
    assert s.fields[1].show_if.equals == "Tak"
    assert (s.fields[2].type, s.fields[2].validators, s.fields[2].dictionary) == ("TEXT_FIELD", ["EMAIL"], "")


def test_prompt_fits_free_mistral_budget():
    sys_p = system_prompt()
    assert "Wniosek" in sys_p and '"pages"' in sys_p and "\n  " not in sys_p.split("Poprawny szkic")[1]
    # ~3 znaki/token PL: system + max część + odpowiedź mieszczą się w 40k tokenów/min
    assert (len(sys_p) + MAX_CHUNK_CHARS) / 3 < 12_000


def test_compress_shrinks_leaders_and_rodo():
    text = "Imię……………………………… nazwisko ______\nKLAUZULA INFORMACYJNA\n" + ("Państwa dane są przetwarzane. " * 300)
    out = compress(text)
    assert "……" not in out and "___" not in out and out.count("…") >= 2 and len(out) < 1000 and "pominięta" in out


def test_chunks_split_long_document_and_truncate():
    pages = [("Pole numer %d: ……\n" % i) * 600 for i in range(5)]  # 5 stron po ~9k znaków
    parts, truncated = chunks(Document.from_pages(pages, "pdf"))
    assert len(parts) == 2 and truncated and all(len(p) <= MAX_CHUNK_CHARS for p in parts)


# --- ścieżka LLM (fałszywy klient) ----------------------------------------------------------------------------
def test_llm_path_returns_fixture_draft():
    llm = FakeLLM(fixture_dict())
    r = make_draft(doc_of("WNIOSEK O USTALENIE NUMERU\nImię ……\n(podpis wnioskodawcy)"), llm)
    assert r.source == "llm" and len(llm.calls) == 1
    assert r.draft.title == "Wniosek o ustalenie numeru porządkowego nieruchomości"
    assert len(fields(r.draft)) == len(fields(Draft.model_validate(fixture_dict())))  # nic nie zgubione
    assert any("Podpis" in x for x in r.removed_paper_elements)
    assert_valid(r)


def test_llm_error_falls_back_to_heuristic():
    r = make_draft(doc_of("WNIOSEK O COŚ\nNazwisko: ……\nUzasadnienie: ……"), FakeLLM(LLMError("429")))
    assert r.source == "heuristic" and any("LLM niedostępny" in w for w in r.warnings)
    assert_valid(r)


def test_unexpected_exception_falls_back():
    r = make_draft(doc_of("WNIOSEK\nAdres ……"), FakeLLM(RuntimeError("boom")))
    assert r.source == "heuristic"
    assert_valid(r)


def test_no_llm_and_empty_document_still_valid():
    for doc in (doc_of(""), Document.from_pages([], "png")):
        r = make_draft(doc, None)
        assert r.source == "heuristic"
        assert_valid(r)


def test_llm_two_chunks_are_merged_before_contact_page():
    main = small()
    main["pages"].append({"title": "Kontakt z urzędem", "sections": [{"title": "Dane do kontaktu", "fields": [
        {"label": "Adres e-mail", "type": "TEXT_FIELD", "required": False, "validators": ["EMAIL"]}]}]})
    extra = {"title": "x", "pages": [{"title": "Nieruchomość", "sections": [{"title": "Działka", "fields": [
        {"label": "Numer działki", "type": "TEXT_FIELD", "required": True}]}]}]}
    llm = FakeLLM(main, extra)
    long_doc = Document.from_pages([("Linia ……\n" * 1500), ("Działka ……\n" * 1500)], "pdf")
    r = make_draft(long_doc, llm)
    assert len(llm.calls) == 2 and "CZĘŚĆ 2 z 2" in llm.calls[1][1]
    assert [p.title for p in r.draft.pages] == ["Dane", "Nieruchomość", "Kontakt z urzędem"]
    assert_valid(r)


def test_merge_same_page_title_merges_sections():
    a = Draft.model_validate(small())
    b = Draft.model_validate(small(extra=[{"label": "Nazwisko", "type": "TEXT_FIELD", "required": True}]))
    m = merge(a, b)
    assert len(m.pages) == 1 and [f.label for f in fields(m)] == ["Imię", "Nazwisko"]


def test_user_prompt_mentions_ocr():
    d = Document.from_pages(["abc"], "jpg", ocr_used=True)
    assert "OCR" in user_prompt(d, "abc")


# --- post-processing --------------------------------------------------------------------------------------------
@pytest.mark.parametrize("raw,expected", [
    ("WNIOSEK O WYDANIE ZAŚWIADCZENIA", "Wniosek o wydanie zaświadczenia"),
    ("Deklaracja o wysokości opłaty (na podstawie art. 6m ustawy o utrzymaniu czystości)", "Deklaracja o wysokości opłaty"),
    ("Podanie o przyznanie stypendium", "Wniosek o przyznanie stypendium"),
    ("Zezwolenie na zajęcie pasa drogowego", "Wniosek o zezwolenie na zajęcie pasa drogowego"),
    ("", "Wniosek"),
])
def test_normalize_title(raw, expected):
    assert normalize_title(raw, []) == expected


def test_title_max_255():
    t = normalize_title("Wniosek o " + "bardzo długą sprawę " * 30, w := [])
    assert len(t) <= 255 and w


def test_postprocess_structure_hygiene_only():
    # sprzątanie treści (podpis/data/pieczęć, zgody, typy, nieznane show_if) robi tidy() F-15 Pawła w builderze
    d = Draft.model_validate(small(extra=[
        {"label": "Czytelny podpis wnioskodawcy", "type": "TEXT_FIELD", "required": True},
        {"label": "Opis", "type": "TEXTAREA", "required": False, "options": ["śmieć"]},
        {"label": "Rodzaj", "type": "RADIO", "required": True, "options": ["A", "B", "A", " "]},
        {"label": "Zależne", "type": "TEXT_FIELD", "required": False, "show_if": {"field": "Nie ma mnie", "equals": "x"}},
        {"label": "Zależne 2", "type": "TEXT_FIELD", "required": False, "show_if": {"field": "rodzaj", "equals": "b"}},
        {"label": "Lista", "type": "SELECT", "required": False},
    ]))
    d.pages.append(Draft.model_validate(small()).pages[0].model_copy(update={"title": "Pusta", "sections": []}))
    out = postprocess(d, [], [])
    by = {f.label: f for f in fields(out)}
    assert "Czytelny podpis wnioskodawcy" in by  # zostaje dla tidy()
    assert by["Opis"].options == [] and by["Rodzaj"].options == ["A", "B"] and by["Lista"].type == "TEXT_FIELD"
    assert by["Zależne"].show_if.field == "Nie ma mnie"  # nieznane pole -> decyduje F-15 (e)
    assert (by["Zależne 2"].show_if.field, by["Zależne 2"].show_if.equals) == ("Rodzaj", "B")  # wielkość liter
    assert [p.title for p in out.pages] == ["Dane"]
    form_notes = []
    assert check(build(out, form_notes)) == [] and any("podpis" in n for n in form_notes)


def test_llm_all_paper_draft_falls_back():
    d = {"title": "Wniosek", "pages": [{"title": "A", "sections": [{"title": "B", "fields": [
        {"label": "Podpis", "type": "TEXT_FIELD", "required": True}]}]}]}
    r = make_draft(doc_of("WNIOSEK\nNazwa działki: ……"), FakeLLM(d))
    assert r.source == "heuristic"
    assert_valid(r)


# --- heurystyka na prawdziwych formularzach 1..9 -----------------------------------------------------------------
def _form_text(n: int) -> str:
    folder = next((DATA / str(n)).iterdir())
    docx_files = [f for f in folder.iterdir() if f.suffix.lower() == ".docx" and "wizualizacja" not in f.name]
    if docx_files:
        import docx
        d = docx.Document(str(docx_files[0]))
        text = "\n".join(p.text for p in d.paragraphs if p.text.strip())
        text += "\n" + "\n".join(" | ".join(dict.fromkeys(c.text.strip() for c in r.cells if c.text.strip()))
                                 for t in d.tables for r in t.rows)
        if len(text.strip()) > 200:
            return text
    import pypdfium2 as pdfium
    pdf = next(f for f in folder.iterdir() if f.suffix.lower() == ".pdf")
    return "\n\f\n".join(p.get_textpage().get_text_range() for p in pdfium.PdfDocument(str(pdf)))


needs_data = pytest.mark.skipif(not (DATA / "9").exists(), reason="brak katalogu data/ z formularzami")


@needs_data
@pytest.mark.parametrize("n", range(1, 10))
def test_heuristic_on_real_forms(n):
    pytest.importorskip("docx")
    pytest.importorskip("pypdfium2")
    text = _form_text(n)
    r = make_draft(doc_of(text), None)
    assert r.source == "heuristic"
    assert r.draft.title.split()[0] in ("Wniosek", "Zgłoszenie", "Deklaracja", "Oświadczenie")
    assert len(fields(r.draft)) >= 3  # same pola z dokumentu; standardowe dokłada builder (F-14)
    assert any("odpis" in x or "Podpis" in x for x in r.removed_paper_elements)
    assert not any(f.label.lower().startswith("podpis") for f in fields(r.draft))
    assert_valid(r)


@needs_data
def test_heuristic_finds_known_fields_form1():
    pytest.importorskip("docx")
    labels = {f.label for f in fields(heuristic_draft(doc_of(_form_text(1)))[0])}
    assert "Nr ewidencyjny działki" in labels and not {"Imię", "Nazwisko", "Adres e-mail"} & labels  # F-14: z szablonów


def test_heuristic_boxes_become_choice():
    text = "WNIOSEK O WYDANIE ZAŚWIADCZENIA\nProszę o wydanie zaświadczenia o:*\n ilości użytków\n okresie posiadania\n" \
           "Płeć: ☐ kobieta ☐ mężczyzna\nCzy posiadasz psa? ☐ Tak ☐ Nie"
    d, _ = heuristic_draft(doc_of(text))
    by = {f.label: f for f in fields(d)}
    assert by["Proszę o wydanie zaświadczenia o"].type == "CHECKBOX"
    assert by["Proszę o wydanie zaświadczenia o"].options == ["Ilości użytków", "Okresie posiadania"]
    assert by["Proszę o wydanie zaświadczenia o"].required
    assert by["Czy posiadasz psa?"].type == "RADIO"


def test_heuristic_table_repeating_section():
    doc = Document.from_pages(["WNIOSEK O COŚ"], "docx", tables=[[["Lp.", "Imię i nazwisko", "PESEL"], ["1", "", ""], ["2", "", ""]]])
    d, _ = heuristic_draft(doc)
    rep = [s for p in d.pages for s in p.sections if s.repeating]
    assert rep and [f.label for f in rep[0].fields] == ["Imię i nazwisko", "PESEL"]
    assert rep[0].fields[1].validators == ["PESEL"]


# --- F-16 (P7): załącznik jako RADIO Tak/Nie -> FILE_UPLOADER -------------------------------------------------
def test_attachment_yes_no_becomes_upload_and_drops_dependent_show_if():
    from app.form_builder.draft_llm import attachments_as_uploads
    d = Draft.model_validate({"title": "Deklaracja o wysokości opłaty", "pages": [{"title": "Załączniki", "sections": [
        {"title": "Załączniki", "fields": [
            {"label": "Załącznik A (część nieruchomości bez mieszkańców)", "type": "RADIO", "options": ["Tak", "Nie"]},
            {"label": "Kwota z załącznika A", "type": "NUMBER", "show_if": {"field": "Załącznik A (część nieruchomości bez mieszkańców)", "equals": "Tak"}},
            {"label": "Czy nieruchomość jest zamieszkana?", "type": "RADIO", "options": ["Tak", "Nie"]},
        ]}]}]})
    warnings: list[str] = []
    fields = attachments_as_uploads(d, warnings).pages[0].sections[0].fields
    assert (fields[0].type, fields[0].options) == ("FILE_UPLOADER", [])
    assert fields[1].show_if is None          # FILE_UPLOADER nie steruje widocznością
    assert fields[2].type == "RADIO"          # zwykłe pytanie Tak/Nie zostaje
    assert warnings and "Załącznik A" in warnings[0]
    assert check(build(d)) == []


def test_prompt_has_f16_rules():
    s = system_prompt()
    for phrase in ("Czego dotyczy wniosek", "NIE wymyślaj", "Imię kandydata", "nigdy RADIO", "od 45 do 60 m²",
                   # F-16+++ (v4): warianty w treści, osoba trzecia = upload, negatywny przykład, warunkowe „dodatkowe”
                   "Tytuł z wariantem NIE zastępuje", "nigdy CONSENT_SECTION wnioskodawcy", "BŁĄD:", "Czy … więcej niż jeden"):
        assert phrase in s
