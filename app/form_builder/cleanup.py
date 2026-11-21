"""F-15: deterministyczne sprzątanie szkicu od LLM przed builderem (reguły w config/field_rules.yaml -> cleanup).

Usuwa pola papierowe, oświadczenia zamienia na zgody, poprawia typy pól wyboru i kwot.
Zwraca kopię szkicu; każda zmiana trafia do `notes` (trace w /convert?debug=true).
"""
import re

from app.form_builder.draft import Draft
from app.form_builder.enrich import CFG, dictionary, norm

C = CFG["cleanup"]
DROP = re.compile(C["drop"])
CONSENT = re.compile(C["consent"])
NUMBER = re.compile(C["number"])


def tidy(draft: Draft, notes: list) -> Draft:
    d = draft.model_copy(deep=True)
    for page in d.pages:
        kept_secs = []
        for sec in page.sections or []:
            if DROP.search(norm(sec.title)):
                notes.append(f"usunięto sekcję {sec.title!r} (pole papierowe/instrukcja)")
                continue
            kept = []
            for f in sec.fields or []:
                if DROP.search(norm(f.label)):
                    notes.append(f"usunięto pole {f.label!r} (pole papierowe/instrukcja)")
                    continue
                _fix_type(f, sec.title, notes)
                kept.append(f)
            sec.fields = kept
            kept_secs.append(sec)
        page.sections = kept_secs
    return d


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
