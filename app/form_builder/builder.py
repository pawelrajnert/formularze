"""F-07: Draft (od LLM) -> pełny JSON formularza COI. Deterministyczny poza UUID.

CLI: python -m app.form_builder.builder draft.json > form.json
"""
import json
import re
import sys
import unicodedata
import uuid
from html import escape
from pathlib import Path

from app.form_builder.draft import Draft
from app.form_builder.enrich import dictionary, enrich

CHOICE = {"SELECT", "RADIO", "CHECKBOX"}
EMPTY_HTML = "<html><head></head><body></body></html>"
FINISH_TEXT = "Zanim wyślesz wniosek, sprawdź uzupełnione dane na podglądzie. Jeśli zobaczysz błędy, wróć do edycji."


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
        self.prefilled: set[str] = set()  # klucze danych inicjalnych już użyte (tylko pierwsze pole = wnioskodawca)
        self.negate: dict[str, tuple[str, str]] = {}  # ścieżka pola słownikowego -> (opcja domyślna, druga opcja ze szkicu)
        self.sec = None  # bieżąca sekcja szkicu

    def tech(self, label: str, fallback: str) -> str:
        base = slug(label) or fallback
        name, n = base, 2
        while name in self.names:
            name, n = f"{base}_{n}", n + 1
        self.names.add(name)
        return name

    def field(self, f, order: int, tab_title: str, sec_tech: str) -> dict:
        t = f.type
        text_only = t in ("TEXT_BLOCK", "CONSENT_SECTION")  # treść idzie do description/zgody, title pusty
        out = {
            "id": _uid(), "type": t, "techName": self.tech(f.label, t.lower()),
            "title": "" if text_only else f.label,
            "description": _html(f.label) if t == "TEXT_BLOCK" else (_html(f.hint) if f.hint else ""),
            "options": [{"id": o, "name": o, "techName": slug(o) or f"opcja_{i}"} for i, o in enumerate(f.options)] if t in CHOICE else [],
            "validation": (["REQUIRED"] if f.required else []) + [v for v in f.validators if v != "REQUIRED"],
            "readOnly": f.read_only, "repeatingSectionGrid": [],
        }
        if f.default:
            out["defaultValue"] = [f.default] if t in CHOICE else f.default  # reguły: "defaultValue": [] dla list
        enrich(out, f, self.prefilled, self.sec.title, self.sec.repeating)
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
        return out

    def build(self, draft: Draft) -> dict:
        tabs = []
        for page in draft.pages:
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
        if not tabs:
            raise ValueError("szkic nie zawiera żadnego pola - nie da się zbudować formularza")
        for target, cond, sec_tech in self.pending:
            path = self.local.get((sec_tech, cond.field)) or self.paths.get(cond.field)
            if not path:  # nieznany label sterujący -> pole zawsze widoczne
                continue
            neg = self.negate.get(path)
            if neg and cond.equals == neg[1]:
                query = f"$not({json.dumps(neg[0], ensure_ascii=False)} in {path})"
            else:
                query = f"({json.dumps(cond.equals, ensure_ascii=False)} in {path})"
            target["states"].append({"type": "SHOW", "query": query})
        finish = {
            "id": _uid(), "type": "TEXT_BLOCK", "techName": self.tech("podglad", "podglad"), "title": "",
            "description": _html(draft.finish_text or FINISH_TEXT), "options": [], "validation": [],
            "readOnly": False, "repeatingSectionGrid": [], "states": [], "questionOrder": 0, "tooltipMessage": "",
        }
        finish_sec = {
            "id": _uid(), "type": "SECTION", "techName": self.tech("Podgląd uzupełnionego wniosku", "podglad"),
            "title": "Podgląd uzupełnionego wniosku", "description": EMPTY_HTML, "options": [], "validation": [],
            "readOnly": False, "repeatingSectionGrid": [_q(0, 0, 1, finish)], "states": [], "questionOrder": 0,
            "tooltipMessage": "",
        }
        tabs.append({"id": _uid(), "title": "Strona końcowa", "type": "FINISH", "questions": [_q(0, 0, 2, finish_sec)]})
        links = [{"id": _uid(), "source": a["id"], "target": b["id"]} for a, b in zip(tabs, tabs[1:])]
        return {"title": draft.title, "tabs": tabs, "flow": {"links": links}}


def build(draft: Draft) -> dict:
    return _Builder().build(draft)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("użycie: python -m app.form_builder.builder draft.json > form.json")
    d = Draft.model_validate_json(Path(sys.argv[1]).read_text("utf-8"))
    print(json.dumps(build(d), ensure_ascii=False, indent=2))
