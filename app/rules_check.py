"""Walidator JSON-a formularza COI: JSON Schema + reguły techniczne. check(form) -> lista błędów (pusta = OK)."""
import json
import re
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

# Kopia data/.../importowanyPlikJsonSchemat (1).json z poprawioną literówką
# "repetingSectionGrid" -> "repeatingSectionGrid" (przykłady i JSONata używają tej drugiej nazwy)
# oraz defaultValue string-or-array (Reguły techniczne: pola wyboru mają "defaultValue": [...]).
SCHEMA = json.loads((Path(__file__).resolve().parent.parent / "config" / "form_schema.json").read_text("utf-8"))
_validator = Draft202012Validator(SCHEMA)

UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
CONTAINERS = {"SECTION", "REPEATING_SECTION"}
INPUTS = {"TEXT_FIELD", "CHECKBOX", "NUMBER", "CONSENT_SECTION", "SELECT", "TEXTAREA", "FILE_UPLOADER", "RADIO", "DATEPICKER"}
NON_INPUTS = {"TEXT_BLOCK", "INFO_SECTION"}
CHOICE = {"SELECT", "RADIO", "CHECKBOX"}
VALIDATORS = {"REQUIRED", "EMAIL", "PESEL", "NIP", "REGON", "ZIP_CODE", "EPUAP", "ADE", "SERIAL_NUMBER_ID_CARD"}


def _f(q) -> dict:
    f = q.get("field") if isinstance(q, dict) else None
    return f if isinstance(f, dict) else {}


def _check_field(f: dict, path: str, container: bool, ids: dict, errs: list) -> None:
    t = f.get("type")
    if t not in CONTAINERS | INPUTS | NON_INPUTS:
        errs.append(f"{path}: nieznany typ pola {t!r}")
    if container and t not in CONTAINERS | {"INFO_SECTION"}:
        errs.append(f"{path}: pole {t} musi być w SECTION lub REPEATING_SECTION, a leży bezpośrednio na stronie")
    if not container and t in CONTAINERS:
        errs.append(f"{path}: sekcja {t} zagnieżdżona w innej sekcji (niedozwolone)")
    fid = f.get("id")
    if not isinstance(fid, str) or not UUID.match(fid):
        errs.append(f"{path}: id {fid!r} nie jest UUID")
    elif fid in ids:
        errs.append(f"{path}: id {fid} powtarza się (także w {ids[fid]})")
    else:
        ids[fid] = path
    if not f.get("techName"):
        errs.append(f"{path}: brak techName")
    # obligatoryjność musi być jawna: klucz "validation" jako lista (pusta = pole opcjonalne)
    val = f.get("validation")
    if not isinstance(val, list):
        errs.append(f"{path}: brak jawnej obligatoryjności: 'validation' musi być listą (pusta = opcjonalne), jest {val!r}")
    else:
        for v in val:
            if v not in VALIDATORS:
                errs.append(f"{path}: nieznany walidator {v!r}")
    if f.get("dictionaryName") and t not in CHOICE:
        errs.append(f"{path}: słownik dozwolony tylko dla SELECT/RADIO/CHECKBOX, a pole ma typ {t}")
    if f.get("options") and t not in CHOICE:
        errs.append(f"{path}: opcje dozwolone tylko dla SELECT/RADIO/CHECKBOX, a pole ma typ {t}")
    allowed_states = {"SHOW"} if t in CONTAINERS else {"SHOW", "READ_ONLY"}
    for i, s in enumerate(f.get("states") or []):
        if not isinstance(s, dict) or s.get("type") not in allowed_states:
            errs.append(f"{path}.states[{i}]: typ stanu musi być jednym z {sorted(allowed_states)}")
        elif not isinstance(s.get("query"), str) or not s["query"].strip():
            errs.append(f"{path}.states[{i}]: brak wyrażenia JSONata w 'query'")
    children = f.get("repeatingSectionGrid") or []
    if t in CONTAINERS and not children:
        errs.append(f"{path}: sekcja bez pól")
    for j, q in enumerate(children):
        _check_field(_f(q), f"{path}.repeatingSectionGrid[{j}]", False, ids, errs)


def _fields(qs: list):
    for q in qs:
        f = _f(q)
        yield f
        yield from _fields(f.get("repeatingSectionGrid") or [])


def check(form: dict) -> list[str]:
    errs = [f"schemat: {'/'.join(map(str, e.absolute_path)) or '(root)'}: {e.message}" for e in _validator.iter_errors(form)]
    if errs or not isinstance(form, dict):
        return errs or ["schemat: formularz musi być obiektem JSON"]

    title = form.get("title")
    if not isinstance(title, str) or not title.strip():
        errs.append("title: brak tytułu formularza")
    elif len(title) > 255:
        errs.append(f"title: tytuł ma {len(title)} znaków (max 255)")

    tabs = form.get("tabs") or []
    if len(tabs) < 2:
        errs.append(f"tabs: formularz musi mieć min. 2 strony, ma {len(tabs)}")
    ids: dict = {}
    for i, tab in enumerate(tabs):
        path = f"tabs[{i}]"
        want = "FINISH" if i == len(tabs) - 1 else "MAIN"
        if tab.get("type") != want:
            errs.append(f"{path}: strona musi mieć type {want}, ma {tab.get('type')!r}")
        tid = tab.get("id")
        if not isinstance(tid, str) or not UUID.match(tid):
            errs.append(f"{path}: id {tid!r} nie jest UUID")
        elif tid in ids:
            errs.append(f"{path}: id {tid} powtarza się (także w {ids[tid]})")
        else:
            ids[tid] = path
        qs = tab.get("questions") or []
        if not any(f.get("type") not in CONTAINERS for f in _fields(qs)):
            errs.append(f"{path}: strona musi zawierać min. jedno pole")
        for j, q in enumerate(qs):
            _check_field(_f(q), f"{path}.questions[{j}]", True, ids, errs)
        if tab.get("type") == "FINISH":
            for f in map(_f, qs):
                if f.get("type") != "INFO_SECTION":
                    errs.append(f"{path}: na stronie FINISH dozwolona wyłącznie INFO_SECTION, jest {f.get('type')} ({f.get('techName')})")
            for f in _fields(qs):
                if f.get("type") in INPUTS:
                    errs.append(f"{path}: na stronie FINISH niedozwolone pole wejściowe {f.get('type')} ({f.get('techName')})")

    # flow: każda strona poza pierwszą jest celem przejścia, każda poza FINISH jest jego źródłem
    links = (form.get("flow") or {}).get("links") or []
    tab_ids = [t.get("id") for t in tabs]
    seen_links = set()
    for i, link in enumerate(links):
        lid = link.get("id")
        if not isinstance(lid, str) or not UUID.match(lid):
            errs.append(f"flow.links[{i}]: id {lid!r} nie jest UUID")
        elif lid in seen_links:
            errs.append(f"flow.links[{i}]: id {lid} powtarza się")
        seen_links.add(lid)
        for end in ("source", "target"):
            if link.get(end) not in tab_ids:
                errs.append(f"flow.links[{i}].{end}: {link.get(end)!r} nie wskazuje istniejącej strony")
    sources = {l.get("source") for l in links}
    targets = {l.get("target") for l in links}
    for i, tid in enumerate(tab_ids):
        if i > 0 and tid not in targets:
            errs.append(f"flow: do strony tabs[{i}] nie prowadzi żadne przejście")
        if i < len(tab_ids) - 1 and tid not in sources:
            errs.append(f"flow: ze strony tabs[{i}] nie wychodzi żadne przejście")
    return errs


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("użycie: python -m app.rules_check plik.json")
    problems = check(json.loads(Path(sys.argv[1]).read_text("utf-8")))
    print("\n".join(problems) or "OK")
    sys.exit(1 if problems else 0)
