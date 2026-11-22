"""F-19 (część M): ścisła zgodność kluczy ze wzorcami COI 1 i 5 oraz z ORYGINALNYM importowanyPlikJsonSchemat.

Zestawy kluczy NIE są wpisane ręcznie — liczymy je z oficjalnych wzorców `data/1`, `data/5`:
- "zawsze" = klucze obecne w każdym obiekcie danego rodzaju we wzorcach (brak = błąd),
- "dozwolone" = klucze, które wzorce mają choć raz (spoza = błąd).
Rodzaje: korzeń, tab, question, field per `type`, option, state, consentSectionConfig, consent, flow, link.
Typ pola, którego wzorce nie zawierają (CHECKBOX, DATEPICKER, INFO_SECTION, REPEATING_SECTION — są w
„Regułach technicznych”), porównujemy z kluczami wspólnymi dla wszystkich typów pól z wzorców.

Znane odstępstwa są tu wypisane jawnie (ALLOWED_* i KNOWN_*), a rozbieżności do naprawy w builderze
(część P) są xfail(strict=True) — po naprawie test zacznie „xpass-ować” i wymusi zdjęcie xfail.
"""
import copy
import json
from collections import defaultdict
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from app.form_builder.builder import build
from app.form_builder.draft import Draft

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
TEMPLATES = sorted(DATA.glob("1/*/konfiguracja*.json")) + sorted(DATA.glob("5/*/konfiguracja*.json"))
ORIGINAL_SCHEMA_PATH = next(DATA.glob("Materiały do zadania dla Uczestników/**/importowanyPlikJsonSchemat*.json"))
ORIGINAL_SCHEMA = json.loads(ORIGINAL_SCHEMA_PATH.read_text("utf-8"))
RESULTS = sorted((ROOT / "wyniki").glob("*.json"))
DRAFT1 = Draft.model_validate_json((ROOT / "tests" / "fixtures" / "draft_form1.json").read_text("utf-8"))

# szkic pokrywający typy pól, których nie ma w fixture, sekcję powtarzalną i RADIO z wartością domyślną
DRAFT_ALL = Draft.model_validate({"title": "Wszystkie typy", "pages": [{"title": "Strona", "sections": [
    {"title": "Pola", "fields": [
        {"label": "Tekst", "type": "TEXT_FIELD", "required": True},
        {"label": "Opis sprawy", "type": "TEXTAREA"},
        {"label": "Kwota", "type": "NUMBER"},
        {"label": "Data zdarzenia", "type": "DATEPICKER"},
        {"label": "Rodzaj", "type": "SELECT", "options": ["A", "B"], "default": "A"},
        {"label": "Czy dotyczy", "type": "RADIO", "options": ["Tak", "Nie"], "default": "Nie"},
        {"label": "Zaznacz", "type": "CHECKBOX", "options": ["X", "Y"]},
        {"label": "Załącznik", "type": "FILE_UPLOADER"},
        {"label": "Informacja", "type": "TEXT_BLOCK"},
    ]},
    {"title": "Współwłaściciele", "repeating": True, "fields": [{"label": "PESEL", "type": "TEXT_FIELD", "validators": ["PESEL"]}]},
]}]})


def _rel(p: Path) -> str:
    return p.relative_to(ROOT).as_posix()


# ---------- zbieranie obiektów każdego rodzaju (z czytelną ścieżką) ----------

def objects(form):
    """Yield (rodzaj, ścieżka, obiekt) dla każdego obiektu formularza na każdym poziomie."""
    yield "root", "(korzeń)", form
    for ti, tab in enumerate(form.get("tabs") or []):
        tp = f"tabs[{ti}] '{tab.get('title')}' ({tab.get('type')})"
        yield "tab", tp, tab
        yield from _questions(tab.get("questions") or [], tp)
    flow = form.get("flow")
    if isinstance(flow, dict):
        yield "flow", "flow", flow
        for li, link in enumerate(flow.get("links") or []):
            yield "link", f"flow.links[{li}]", link


def _questions(questions, parent):
    for q in questions:
        f = q.get("field") or {}
        p = f"{parent} > {f.get('techName')}"
        yield "question", p, q
        yield f"field:{f.get('type')}", p, f
        for oi, o in enumerate(f.get("options") or []):
            yield "option", f"{p}.options[{oi}]", o
        for si, s in enumerate(f.get("states") or []):
            yield "state", f"{p}.states[{si}]", s
        c = f.get("consentSectionConfig")
        if isinstance(c, dict):
            yield "consentSectionConfig", f"{p}.consentSectionConfig", c
            for ci, x in enumerate(c.get("consents") or []):
                yield "consent", f"{p}.consentSectionConfig.consents[{ci}]", x
        yield from _questions(f.get("repeatingSectionGrid") or [], p)


def _spec():
    seen = defaultdict(list)
    for p in TEMPLATES:
        for kind, _, obj in objects(json.loads(p.read_text("utf-8"))):
            seen[kind].append(set(obj))
    spec = {k: (set.intersection(*v), set.union(*v)) for k, v in seen.items()}  # (zawsze, dozwolone)
    fields = [v for k, v in spec.items() if k.startswith("field:")]
    spec["field:*"] = (set.intersection(*(a for a, _ in fields)), set.intersection(*(u for _, u in fields)))
    return spec


SPEC = _spec()

# Odstępstwa od wzorca dozwolone świadomie (rodzaj -> klucze dodatkowo dozwolone, z uzasadnieniem):
ALLOWED_EXTRA: dict[str, set[str]] = {}
# Klucze „zawsze” we wzorcu, których brak dopuszczamy (np. występowały tylko przypadkiem): rodzaj -> klucze
ALLOWED_MISSING: dict[str, set[str]] = {}


def key_errors(form, label):
    errs = []
    for kind, path, obj in objects(form):
        if not isinstance(obj, dict):
            errs.append(f"{label}: {path}: typ {kind}: oczekiwano obiektu, jest {type(obj).__name__}")
            continue
        always, allowed = SPEC.get(kind) or SPEC["field:*"]
        keys = set(obj)
        missing = sorted(always - keys - ALLOWED_MISSING.get(kind, set()))
        extra = sorted(keys - allowed - ALLOWED_EXTRA.get(kind, set()))
        if missing or extra:
            ref = kind if kind in SPEC else f"{kind} (brak we wzorcach -> wspólne klucze pól)"
            errs.append(f"{label}: {path}: typ {ref}: brakujące {missing}, nadmiarowe {extra}")
    return errs


# ---------- sprawdzane formularze + jawne rozbieżności do naprawy (część P) ----------

RADIO_DEFAULT = ("RADIO z kluczem defaultValue: wzorce 1/5 ani „Reguły techniczne” (komponent RADIO) go nie mają; "
                 "builder.py:125 dodaje [f.default] dla każdego CHOICE — do naprawy w builderze (P)")
REPEATING_MIN_ROWS = ("question z REPEATING_SECTION bez minItemRows (wzorzec 1 ma minItemRows: 2) — F-19 część P (builder)")

KNOWN_KEY_DIFFS = {"wyniki/9.json": RADIO_DEFAULT, "builder:DRAFT_ALL": RADIO_DEFAULT}
KNOWN_MIN_ROWS = {"wyniki/7.json": REPEATING_MIN_ROWS, "builder:DRAFT_ALL": REPEATING_MIN_ROWS}


def _forms():
    out = [(_rel(p), lambda p=p: json.loads(p.read_text("utf-8"))) for p in RESULTS]
    out += [("builder:draft_form1", lambda: build(DRAFT1)), ("builder:DRAFT_ALL", lambda: build(DRAFT_ALL))]
    return out


def _params(known):
    return [pytest.param(label, load, id=label,
                         marks=[pytest.mark.xfail(strict=True, reason=known[label])] if label in known else [])
            for label, load in _forms()]


# ---------- testy ----------

def test_spec_from_templates():
    """Wzorce się wczytały i dają sensowną specyfikację (strażnik przed pustym globem)."""
    assert len(TEMPLATES) == 2 and RESULTS
    for kind in ("root", "tab", "question", "flow", "link", "option", "state", "consent",
                 "field:SECTION", "field:TEXT_FIELD", "field:SELECT", "field:RADIO", "field:CONSENT_SECTION"):
        assert kind in SPEC, kind
    assert SPEC["root"][0] == {"title", "tabs", "flow"}
    assert SPEC["question"] == ({"x", "y", "rows", "cols", "field"}, {"x", "y", "rows", "cols", "field", "minItemRows"})
    assert {"id", "type", "techName", "validation", "repeatingSectionGrid"} <= SPEC["field:*"][0]


@pytest.mark.parametrize("path", TEMPLATES, ids=lambda p: p.parts[-3])
def test_templates_match_spec(path):
    assert key_errors(json.loads(path.read_text("utf-8")), _rel(path)) == []


@pytest.mark.parametrize("label, load", _params(KNOWN_KEY_DIFFS))
def test_keys_match_templates(label, load):
    errs = key_errors(load(), label)
    assert errs == [], "\n".join(errs)


@pytest.mark.parametrize("label, load", _params(KNOWN_MIN_ROWS))
def test_repeating_section_has_min_item_rows(label, load):
    errs = [f"{label}: {path}: brak minItemRows (lub < 1) przy REPEATING_SECTION"
            for kind, path, q in objects(load())
            if kind == "question" and (q.get("field") or {}).get("type") == "REPEATING_SECTION"
            and not (isinstance(q.get("minItemRows"), int) and q["minItemRows"] >= 1)]
    assert errs == [], "\n".join(errs)


# ---------- ORYGINALNY importowanyPlikJsonSchemat ----------

_original = Draft202012Validator(ORIGINAL_SCHEMA)
# Oryginał ma literówkę "repetingSectionGrid", więc pól zagnieżdżonych (czyli prawie wszystkich) w ogóle nie
# sprawdza. Dlatego drugi test stosuje oryginalny schemat pytania do KAŻDEGO question na każdym poziomie.
_original_question = Draft202012Validator(
    ORIGINAL_SCHEMA["properties"]["tabs"]["items"]["properties"]["questions"]["items"])

# Jawne odstępstwa od oryginalnego schematu: (typ pola, ścieżka w question, uzasadnienie)
ALLOWED_SCHEMA_DEVIATIONS = {
    ("SELECT", "field/defaultValue"): "wzorce 1 i 5 + „Reguły techniczne”: lista rozwijana ma \"defaultValue\": [] (tablica)",
    ("CHECKBOX", "field/defaultValue"): "„Reguły techniczne”: pola wyboru mają \"defaultValue\": [] (tablica)",
}


def _schema_errors_every_level(form, label, allowed):
    errs = []
    for kind, path, q in objects(form):
        if kind != "question":
            continue
        for e in _original_question.iter_errors(q):
            where = "/".join(map(str, e.absolute_path))
            if ((q.get("field") or {}).get("type"), where) not in allowed:
                errs.append(f"{label}: {path}: {where or '(question)'}: {e.message}")
    return errs


@pytest.mark.parametrize("label, load", [pytest.param(label, load, id=label) for label, load in _forms()])
def test_original_schema_as_is(label, load):
    """Kryterium F-19: 0 błędów oryginalnego schematu (dosłownie, bez poprawek)."""
    errs = [f"{label}: {'/'.join(map(str, e.absolute_path)) or '(root)'}: {e.message}" for e in _original.iter_errors(load())]
    assert errs == [], "\n".join(errs)


@pytest.mark.parametrize("label, load", _params({"wyniki/9.json": RADIO_DEFAULT, "builder:DRAFT_ALL": RADIO_DEFAULT}))
def test_original_schema_every_level(label, load):
    errs = _schema_errors_every_level(load(), label, ALLOWED_SCHEMA_DEVIATIONS)
    assert errs == [], "\n".join(errs)


def test_templates_original_schema_deviations_are_known():
    """Wzorce COI same łamią oryginalny schemat na poziomie zagnieżdżonym — dokładnie w znanych miejscach."""
    e1 = _schema_errors_every_level(json.loads(TEMPLATES[0].read_text("utf-8")), "1", ALLOWED_SCHEMA_DEVIATIONS)
    e5 = _schema_errors_every_level(json.loads(TEMPLATES[1].read_text("utf-8")), "5", ALLOWED_SCHEMA_DEVIATIONS)
    assert len(e1) == 3 and all("field/validation: {} is not of type 'array'" in e for e in e1)  # jak fixed() w test_rules_check
    assert e5 == []


def test_key_errors_reports_file_path_type_and_keys():
    form = build(DRAFT1)
    f = form["tabs"][1]["questions"][0]["field"]
    f["bogus"] = 1
    del f["validation"]
    errs = key_errors(copy.deepcopy(form), "x.json")
    assert len(errs) == 1
    e = errs[0]
    assert e.startswith("x.json: tabs[1] ") and f["techName"] in e and f"typ field:{f['type']}" in e
    assert "brakujące ['validation']" in e and "nadmiarowe ['bogus']" in e
