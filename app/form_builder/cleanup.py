"""F-15: deterministyczne sprzątanie szkicu od LLM przed builderem (reguły w config/field_rules.yaml -> cleanup).

Usuwa pola papierowe, oświadczenia zamienia na zgody, poprawia typy pól wyboru i kwot.
F-14: usuwa też duplikaty sekcji standardowych (wnioskodawca, adres, pełnomocnik, kontakt, RODO, organ) - te są z szablonów.
Zwraca kopię szkicu; każda zmiana trafia do `notes` (trace w /convert?debug=true).
"""
import re

from app.form_builder.draft import Draft, DraftField, DraftSection
from app.form_builder.enrich import CFG, dictionary, norm

C = CFG["cleanup"]
DROP = re.compile(C["drop"])
CONSENT = re.compile(C["consent"])
NUMBER = re.compile(C["number"])
ADDRESS, ADDRESS_HINT = re.compile(C["address"]), re.compile(C["address_hint"])
ADDRESS_PARTS = [("Ulica", True), ("Numer budynku", True), ("Numer lokalu", False), ("Kod pocztowy", True), ("Miejscowość", True)]
S = {k: re.compile(v) for k, v in CFG["standard"].items()}


def tidy(draft: Draft, notes: list) -> Draft:
    d = draft.model_copy(deep=True)
    for page in d.pages:
        kept_secs = []
        for sec in page.sections or []:
            st = norm(sec.title)
            if DROP.search(st):
                notes.append(f"usunięto sekcję {sec.title!r} (pole papierowe/instrukcja)")
                continue
            if S["sections"].search(st):
                _organ(d, sec.fields or [], st)
                notes.append(f"usunięto sekcję {sec.title!r} (dubluje sekcję standardową)")
                continue
            applicant, kept = S["applicant"].search(st), []
            for f in sec.fields or []:
                n = norm(f.label)
                if DROP.search(n):
                    notes.append(f"usunięto pole {f.label!r} (pole papierowe/instrukcja)")
                    continue
                if S["fields"].search(n) or (applicant and S["applicant_fields"].search(n)):
                    _organ(d, [f], st)
                    notes.append(f"usunięto pole {f.label!r} (dubluje sekcję standardową)")
                    continue
                _fix_type(f, sec.title, notes)
                kept.append(f)
            sec.fields = kept
            if kept:
                kept_secs.append(sec)
            kept_secs += _split_addresses(sec, notes)
        page.sections = kept_secs
    d.pages = [p for p in d.pages if p.sections]
    return d


def _organ(d: Draft, fields: list, sec_title: str) -> None:
    """Stara wersja promptu wpisywała organ jako pole read_only -> przenosimy wartość do Draft.organ."""
    if d.organ.strip():
        return
    d.organ = next((f.default.strip() for f in fields if f.default.strip()
                    and S["organ"].search(f"{sec_title} {norm(f.label)}")), "")


def _fix_type(f, sec_title: str, notes: list) -> None:
    n, before = norm(f.label), f.type
    opts = {o.strip().lower() for o in f.options}
    if f.type in ("CHECKBOX", "RADIO", "TEXT_FIELD") and (CONSENT.search(n) or (f.type == "CHECKBOX" and len(opts) <= 1)):
        f.type, f.options = "CONSENT_SECTION", []
    elif f.type in ("SELECT", "RADIO", "CHECKBOX") and f.label in f.options:  # LLM wpisał opcję jako label
        notes.append(f"label {f.label!r} był opcją -> {sec_title!r}")
        f.label = sec_title
    if f.type == "CHECKBOX" and opts == {"tak", "nie"}:
        f.type = "RADIO"
    elif f.type == "SELECT" and 2 <= len(f.options) <= 5 and not dictionary(f):
        f.type = "RADIO"  # standard COI: do 5 opcji -> radio
    elif f.type == "RADIO" and len(f.options) > 15:
        f.type = "SELECT"  # >15 -> lista rozwijana z wyszukiwarką (searchEnabled w builderze)
    elif f.type == "TEXT_FIELD" and NUMBER.search(n) and not dictionary(f):
        f.type = "NUMBER"
    if f.type == "NUMBER" and not re.fullmatch(r"-?\d+([.,]\d+)?", f.default.strip()):
        f.default = ""  # "0 zł" itp. -> pole do wpisania
    if f.type != before:
        notes.append(f"{f.label!r}: {before} -> {f.type}")


def _split_addresses(sec: DraftSection, notes: list) -> list[DraftSection]:
    """Adres w jednym polu -> osobna sekcja z grupą pól (tytuł = label, ten sam show_if) wstawiana za `sec`.
    Gdy adres był jedynym polem sekcji, grupa zastępuje go w miejscu."""
    out = []
    for f in list(sec.fields):
        if f.type not in ("TEXT_FIELD", "TEXTAREA") or not (ADDRESS.search(norm(f.label)) or ADDRESS_HINT.search(norm(f.hint))):
            continue
        parts = [DraftField(label=label, type="TEXT_FIELD", required=f.required and req) for label, req in ADDRESS_PARTS]
        notes.append(f"pole zbiorcze {f.label!r} rozbite na grupę adresową")
        if len(sec.fields) == 1:
            sec.fields = parts
            if f.show_if and not sec.show_if:
                sec.show_if = f.show_if
            break
        sec.fields.remove(f)
        out.append(DraftSection(title=f.label, repeating=sec.repeating, fields=parts, show_if=f.show_if or sec.show_if))
    return out
