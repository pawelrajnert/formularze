"""F-07: Draft (od LLM) -> pełny JSON formularza COI. Deterministyczny poza UUID.

Kolejność stron (wzorzec 1/5): „Dane” (szablony F-14) -> strony merytoryczne LLM -> „Kontakt i zgody” -> FINISH.

CLI: python -m app.form_builder.builder draft.json > form.json
"""
import json
import re
import sys
import unicodedata
import uuid
from html import escape
from pathlib import Path

from app.form_builder import templates
from app.form_builder.cleanup import tidy
from app.form_builder.draft import Draft
from app.form_builder.enrich import dictionary, enrich, norm

CHOICE = {"SELECT", "RADIO", "CHECKBOX"}
EMPTY_HTML = "<html><head></head><body></body></html>"
FINISH_TEXT = "Zanim wyślesz wniosek, sprawdź uzupełnione dane na podglądzie. Jeśli zobaczysz błędy, wróć do edycji."
DANE, KONTAKT = "Dane", "Kontakt i zgody"  # strony z szablonów; JSONata szablonów odwołuje się do tabs['Dane' in title]
# Draft.applicant_kinds -> opcja RADIO „Wybierz, w czyim imieniu wnioskujesz” (kolejność jak we wzorcu)
KIND_OPTION = {"osoba": "Swoim", "inna_osoba": "Innej osoby", "firma": "Osoby prawnej lub jednostki organizacyjnej"}


def _uid() -> str:
    return str(uuid.uuid4())


def _html(text: str) -> str:
    if not text.strip():
        return EMPTY_HTML
    paras = "".join(f"<p>{escape(p.strip())}</p>" for p in text.split("\n") if p.strip())
    return f"<html><head></head><body>{paras}</body></html>"


def slug(text: str, limit: int = 60) -> str:
    """'Imię i nazwisko' -> 'imie_i_nazwisko' (ASCII snake_case, ucięte do `limit` znaków)."""
    t = unicodedata.normalize("NFKD", text.replace("ł", "l").replace("Ł", "L"))
    t = re.sub(r"[^a-z0-9]+", "_", t.encode("ascii", "ignore").decode().lower()).strip("_")
    return t[:limit].rstrip("_")


def _q(x: int, y: int, rows: int, field: dict) -> dict:
    return {"x": x, "y": y, "rows": rows, "cols": 3, "field": field}


def _js(s: str) -> str:
    """Literał JSONaty w apostrofach (jak w przykładach COI: tabs['Dane' in title])."""
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"


class _Builder:
    def __init__(self):
        self.names: set[str] = set()
        self.paths: dict[str, str] = {}  # label pola -> ścieżka JSONata do __userAnswer
        self.pending: list[tuple[dict, object, str]] = []  # (pole/sekcja, show_if, sekcja pola) do rozwiązania na końcu
        self.choice: set[str] = set()  # labele, pod którymi zapisano już pole wyboru
        self.local: dict[tuple[str, str], str] = {}  # (techName sekcji, label) -> ścieżka; ma pierwszeństwo
        self.options: dict[str, list[str]] = {}  # ścieżka pola wyboru -> opcje (warunek „TAK” trafia w opcję „Tak”)
        self.negate: dict[str, tuple[str, str]] = {}  # ścieżka pola słownikowego -> (opcja domyślna, druga opcja ze szkicu)
        self.by_option: dict[str, str] = {}  # opcja -> ścieżka pierwszego pola wyboru z tą opcją
        self.notes: list[str] = []  # co builder poprawił / pominął (trace)
        self.sec = None  # bieżąca sekcja szkicu

    def tech(self, label: str, fallback: str) -> str:
        base = slug(label) or fallback
        name, n = base, 2
        while name in self.names:
            name, n = f"{base}_{n}", n + 1
        self.names.add(name)
        return name

    def insert(self, qs: list[dict]) -> list[dict]:
        """Blok z szablonu na stronę: nowe UUID i techName (bez kolizji z polami LLM), JSONata na nowe nazwy."""
        renamed = {}
        for f in templates.walk(qs):
            f["id"] = _uid()
            renamed[f["techName"]] = f["techName"] = self.tech(f["techName"], f["type"].lower())
        for f in templates.walk(qs):
            for s in f["states"]:
                s["query"] = re.sub(r"'([a-z0-9_]+)' in field\.techName",
                                    lambda m: f"'{renamed.get(m[1], m[1])}' in field.techName", s["query"])
        y = 0
        for q in qs:
            q["y"] = q["field"]["questionOrder"] = y
            q["rows"] = len(q["field"]["repeatingSectionGrid"]) + 1
            y += q["rows"]
        return qs

    def standard(self, draft: Draft) -> tuple[list[dict], list[dict]]:
        """Strona „Dane” i „Kontakt i zgody” z szablonów, przycięte wg pól sterujących szkicu."""
        kinds = [k for k in KIND_OPTION if k in draft.applicant_kinds] or ["osoba"]
        if draft.proxy_allowed and "osoba" in kinds and "inna_osoba" not in kinds:
            kinds.insert(1, "inna_osoba")  # pełnomocnik osoby fizycznej = ścieżka „Innej osoby” we wzorcu
        title = escape(draft.title)
        dane = (templates.load("organ") if draft.organ.strip() else []) + templates.load("podmiot") \
            + templates.load("wnioskodawca") + templates.load("firma") + templates.load("inna_osoba") \
            + (templates.load("pelnomocnictwo", tytul=title) if draft.proxy_allowed else [])
        # opłata za pełnomocnictwo jest już w bloku pełnomocnictwa; osobna sekcja tylko dla opłaty za sam wniosek
        if draft.fee_info.strip() and not (draft.proxy_allowed and "pelnomocn" in norm(draft.fee_info)):
            dane += templates.load("oplata", oplata=_html(draft.fee_info))
        if draft.organ.strip():
            dane[0]["field"]["repeatingSectionGrid"][0]["field"]["defaultValue"] = draft.organ.strip()
        dane = templates.restrict(dane, "wybierz_w_czyim_imieniu_wnioskujesz", [KIND_OPTION[k] for k in kinds])
        dane = templates.restrict(dane, "wybierz_jako_kto_wnioskujesz",
                                  ["Pełnomocnik", "Reprezentant"] if draft.proxy_allowed else ["Reprezentant"])
        return self.insert(dane), self.insert(templates.load("kontakt"))

    def field(self, f, order: int, tab_title: str, sec_tech: str) -> dict:
        t = f.type
        text_only = t in ("TEXT_BLOCK", "CONSENT_SECTION")  # treść idzie do description/zgody, title pusty
        out = {
            "id": _uid(), "type": t, "techName": self.tech(f.label, t.lower()),
            "title": "" if text_only else f.label,
            # LLM wkłada treść bloku do default, a label bywa tylko tytułem -> oba do description
            "description": _html(f"{f.label}\n{f.default}") if t == "TEXT_BLOCK" else (_html(f.hint) if f.hint else ""),
            "options": [{"id": o, "name": o, "techName": slug(o) or f"opcja_{i}"} for i, o in enumerate(f.options)] if t in CHOICE else [],
            "validation": [] if t == "TEXT_BLOCK" else (["REQUIRED"] if f.required else []) + [v for v in f.validators if v != "REQUIRED"],
            "readOnly": f.read_only and t != "TEXT_BLOCK", "repeatingSectionGrid": [],
        }
        if f.default and not text_only:
            out["defaultValue"] = [f.default] if t in CHOICE else f.default  # reguły: "defaultValue": [] dla list
        enrich(out, f)
        # readOnly bez wartości = pole nie do wypełnienia (blokuje wysyłkę); NUMBER tylko z danych inicjalnych
        prefilled = out.get("defaultValueType") == "EXTERNAL_SYSTEM"
        if out["readOnly"] and not (prefilled or (out.get("defaultValue") and out["type"] != "NUMBER")):
            out["readOnly"] = False
        if out["type"] == "SELECT" and len(out["options"]) > 15:
            out["searchEnabled"] = True
        if t == "CONSENT_SECTION":
            out["consentSectionConfig"] = {"consents": [{"description": _html(f.label), "required": f.required}], "files": []}
        out |= {"states": [], "questionOrder": order, "tooltipMessage": ""}
        if f.show_if:
            self.pending.append((out, f.show_if, sec_tech))
        if t != "TEXT_BLOCK":
            path = (f"tabs[{_js(tab_title)} in title].questions[{_js(sec_tech)} in field.techName]"
                    f".field.repeatingSectionGrid[{_js(out['techName'])} in field.techName].field.__userAnswer")
            self.local.setdefault((sec_tech, f.label), path)
            # słownik zastąpił opcje "Polska"/"Inny kraj" -> warunek na drugą opcję to $not(domyślna)
            if out.get("dictionaryName") and len(f.options) == 2 and f.default in f.options:
                self.negate[path] = (f.default, next(o for o in f.options if o != f.default))
            # globalnie przy powtórzonym labelu wygrywa pierwsze pole wyboru, potem pierwsze w ogóle
            if f.label not in self.paths or (t in CHOICE and f.label not in self.choice):
                self.paths[f.label] = path
                if t in CHOICE:
                    self.choice.add(f.label)
            if t in CHOICE:
                self.options[path] = f.options
                for o in f.options:  # show_if bywa na opcję zamiast labela pola
                    self.by_option.setdefault(o, path)
        return out

    def build(self, draft: Draft) -> dict:
        draft = tidy(draft, self.notes)
        # same szablony to nie formularz: szkic bez pól merytorycznych (np. tylko „Podpis”) -> błąd, fallback w F-06
        if not any(s.fields for p in draft.pages for s in p.sections or []):
            raise ValueError("szkic nie zawiera żadnego pola - nie da się zbudować formularza")
        dane, kontakt = self.standard(draft)  # najpierw szablony: zachowują techName ze wzorca
        tabs = [{"id": _uid(), "title": DANE, "type": "MAIN", "questions": dane}]
        for page in draft.pages:
            if page.title in (DANE, KONTAKT):  # tytuł strony musi być unikalny (JSONata: tabs['Dane' in title])
                page.title += " (cd.)"
            questions, y = [], 0
            for sec in page.sections or []:
                # województwo/powiat/gmina/... -> jedno pole-drzewo TERYT na sekcję, kolejne poziomy pomijamy
                fields, teryt = [], False
                for f in sec.fields or []:
                    is_teryt = dictionary(f).startswith("TERYT")
                    if not (is_teryt and teryt):
                        fields.append(f)
                    teryt |= is_teryt
                self.sec = sec
                if not fields:
                    continue
                sec_tech = self.tech(sec.title, "sekcja")
                children = [_q(0, i, 1, self.field(f, i, page.title, sec_tech)) for i, f in enumerate(fields)]
                section = {
                    "id": _uid(), "type": "REPEATING_SECTION" if sec.repeating else "SECTION",
                    "techName": sec_tech, "title": sec.title, "description": EMPTY_HTML, "options": [],
                    "validation": [], "readOnly": False, "repeatingSectionGrid": children,
                    "states": [], "questionOrder": y, "tooltipMessage": "",
                }
                if sec.show_if:
                    self.pending.append((section, sec.show_if, ""))
                questions.append(_q(0, y, len(children) + 1, section))
                y += len(children) + 1
            if questions:
                tabs.append({"id": _uid(), "title": page.title, "type": "MAIN", "questions": questions})
        tabs.append({"id": _uid(), "title": KONTAKT, "type": "MAIN", "questions": kontakt})
        for target, cond, sec_tech in self.pending:
            # warunek nie może wskazywać na samo pole ani na pole z tej samej sekcji-celu (wtedy nigdy się nie pokaże)
            own = f"[{_js(target['techName'])} in field.techName]"
            # po samej opcji tylko, gdy coś znaczy: „Tak”/„Nie” ma pół formularza
            by_opt = self.by_option.get(cond.equals) if norm(cond.equals) not in ("tak", "nie") else None
            path = next((p for p in (self.local.get((sec_tech, cond.field)), self.paths.get(cond.field),
                                     by_opt, self.by_option.get(cond.field)) if p and own not in p), None)
            if not path:  # nieznany label sterujący -> pole zawsze widoczne, więc nie może być wymagane
                for x in [target] + [q["field"] for q in target["repeatingSectionGrid"]]:
                    x["validation"] = [v for v in x["validation"] if v != "REQUIRED"]
                self.notes.append(f"show_if: nie znaleziono pola {cond.field!r} dla {target['title']!r}, warunek pominięty, zdjęto REQUIRED")
                continue
            equals = next((o for o in self.options.get(path, []) if o.casefold() == cond.equals.casefold()), cond.equals)
            neg = self.negate.get(path)
            if neg and equals == neg[1]:
                query = f"$not({json.dumps(neg[0], ensure_ascii=False)} in {path})"
            else:
                query = f"({json.dumps(equals, ensure_ascii=False)} in {path})"
            target["states"].append({"type": "SHOW", "query": query})
        # F-17: reguły COI - na stronie FINISH wyłącznie INFO_SECTION (wzorce 1/5 mają SECTION + TEXT_BLOCK)
        finish = {
            "id": _uid(), "type": "INFO_SECTION", "techName": self.tech("Podgląd uzupełnionego wniosku", "podglad"),
            "title": "Podgląd uzupełnionego wniosku", "description": _html(FINISH_TEXT), "options": [], "validation": [],
            "readOnly": False, "repeatingSectionGrid": [], "states": [], "questionOrder": 0, "tooltipMessage": "",
        }
        tabs.append({"id": _uid(), "title": "Strona końcowa", "type": "FINISH", "questions": [_q(0, 0, 2, finish)]})
        links = [{"id": _uid(), "source": a["id"], "target": b["id"]} for a, b in zip(tabs, tabs[1:])]
        return {"title": draft.title, "tabs": tabs, "flow": {"links": links}}


def build(draft: Draft, notes: list | None = None) -> dict:
    """`notes` (opcjonalnie) dostaje listę poprawek sprzątania i pominiętych warunków."""
    b = _Builder()
    form = b.build(draft)
    if notes is not None:
        notes += b.notes
    return form


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("użycie: python -m app.form_builder.builder draft.json > form.json")
    d = Draft.model_validate_json(Path(sys.argv[1]).read_text("utf-8"))
    print(json.dumps(build(d), ensure_ascii=False, indent=2))
