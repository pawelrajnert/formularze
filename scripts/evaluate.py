"""Ewaluacja jakości konwersji względem niezależnej „prawdy” (ground truth) z eval/ground_truth/<nr>.yaml.

Deterministyczna, bez LLM. Użycie:
    python -m scripts.evaluate              # ocenia wyniki/<nr>.json (+ eval/out/<nr>.json, jeśli są)
    python -m scripts.evaluate --convert    # dodatkowo konwertuje formularze bez wyniku (1, 5) przez LLM z .env
Wynik: eval/raport.md, eval/raport.json, eval/raport.html.

Dopasowanie (uczciwe, jawne): tekst pola = znormalizowany label (app.form_builder.enrich.norm), także
z tytułem sekcji przed nim; klucz GT pasuje, gdy jakieś słowo tekstu zaczyna się od klucza ("a|b" = alternatywa,
klucz ze spacją = fraza w tekście). Pole GT jest znalezione, gdy wszystkie jego klucze pasują.
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

from app.form_builder.enrich import norm

ROOT = Path(__file__).resolve().parent.parent
GT_DIR = ROOT / "eval" / "ground_truth"
OUT_DIR = ROOT / "eval" / "out"
FORMS = ["1", "2", "3", "4", "5", "6", "7", "8", "9"]
COI_TEMPLATES = {"1", "5"}  # GT z oficjalnych wzorców COI (konfiguracja*.json)
MAX_CONVERT = 2  # limit darmowego API: 2 zapytania/min

INPUTS = {"TEXT_FIELD", "CHECKBOX", "NUMBER", "CONSENT_SECTION", "SELECT", "TEXTAREA", "FILE_UPLOADER", "RADIO", "DATEPICKER"}
CHOICE = {"SELECT", "RADIO", "CHECKBOX"}
CONTAINERS = {"SECTION", "REPEATING_SECTION"}
# pola, przy których wzorce COI używają słowników (Kraje, TERYT, Numery kierunkowe)
DICT_ELIGIBLE = re.compile(r"\b(kraj\w*|wojewodztw\w*|powiat\w*|gmin\w*|miejscowos\w*|kierunkow\w*|prefiks\w*)\b")
STOP = {"lub", "oraz", "dla", "jest", "ktory", "ktora", "ktore", "ktorego", "ktorej", "sie", "nie", "jego", "przy", "przez",
        "wybierz", "plik", "mamy", "zrobic", "dotyczy"}


# ---------------------------------------------------------------- dopasowanie
ABBR = {"nr": "numer", "ul": "ulica", "tel": "telefon"}  # skróty traktowane jak pełne słowo (po obu stronach)


def _phrase(parts: list[str], words: list[str]) -> bool:
    for i, w in enumerate(words):
        if not w.startswith(parts[0]):
            continue
        j = i
        for part in parts[1:]:
            j = next((k for k in range(j + 1, min(j + 3, len(words))) if words[k].startswith(part)), None)
            if j is None:
                break
        if j is not None:
            return True
    return False


def key_match(key: str, text: str) -> bool:
    """Klucz ('a|b' = alternatywa) pasuje do znormalizowanego tekstu: początek słowa albo fraza (ze spacją)."""
    words = [ABBR.get(w, w) for w in text.split()]
    for alt in str(key).split("|"):
        alt = " ".join(ABBR.get(w, w) for w in norm(alt).split())
        if not alt:
            continue
        if " " in alt:  # fraza: kolejne słowa jako początki słów, w tej kolejności, max 1 słowo przerwy
            if _phrase(alt.split(), words):
                return True
        elif any(w.startswith(alt) for w in words):
            return True
    return False


def keys_match(keys: list, text: str) -> bool:
    return bool(keys) and all(key_match(k, text) for k in keys)


def _texts(fld: dict) -> list[str]:
    t = [fld["label"]]
    if fld["section"]:
        t.append(f"{fld['section']} {fld['label']}")
    return t


def field_matches(keys: list, fld: dict, with_options: bool = True) -> bool:
    texts = _texts(fld) + (fld["options"] if with_options and fld["type"] in CHOICE else [])
    return any(keys_match(keys, t) for t in texts)


def options_cover(variant: dict, fld: dict) -> int:
    """Ile opcji wariantu GT ma odpowiednik w opcjach pola wyboru."""
    return sum(any(keys_match(o, on) for on in fld["options"]) for o in variant.get("opcje") or [])


# ---------------------------------------------------------------- formularz -> lista pól
def _strip(h: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", h or ""))


def _label(f: dict) -> str:
    """Tytuł pola; CONSENT_SECTION/CHECKBOX bez tytułu -> treść zgody albo opis."""
    if f.get("title"):
        return f["title"]
    consents = (f.get("consentSectionConfig") or {}).get("consents") or []
    return " ".join(_strip(c.get("description")) for c in consents) or _strip(f.get("description"))


def is_merit_tab(tab: dict) -> bool:
    title = norm(tab.get("title") or "")
    return tab.get("type") != "FINISH" and title != "dane" and not title.startswith("kontakt")


def collect(form: dict, merit_only: bool = True) -> list[dict]:
    """Płaska lista pól wejściowych: label, sekcja, typ, opcje, walidacja, states (pola i sekcji)."""
    out: list[dict] = []

    def walk(questions, tab, section, sec_states):
        for q in questions or []:
            f = q.get("field") or {}
            t = f.get("type")
            label = norm(_label(f))
            if t in CONTAINERS:
                walk(f.get("repeatingSectionGrid"), tab, label, list(f.get("states") or []))
                continue
            if t not in INPUTS:
                continue
            out.append({"label": label, "title": _label(f).strip()[:120], "section": section, "tab": tab, "type": t,
                        "options": [norm(o.get("name") or o.get("id") or "") for o in f.get("options") or []],
                        "validation": f.get("validation") or [], "dictionaryName": f.get("dictionaryName"),
                        "states": list(f.get("states") or []), "section_states": sec_states})

    for tab in form.get("tabs") or []:
        if merit_only and not is_merit_tab(tab):
            continue
        walk(tab.get("questions"), tab.get("title") or "", "", [])
    return out


# ---------------------------------------------------------------- GT z wzorców COI (1, 5)
def _label_keys(label: str) -> list[str]:
    words = [w for w in norm(label).split() if len(w) >= 4 and w not in STOP]
    return [w[:max(4, min(6, len(w) - 2))] for w in words[:2]] or [norm(label)]  # rdzeń: odmiana (ulica/ulicy)


def gt_from_coi(path: Path) -> dict:
    form = json.loads(path.read_text("utf-8"))
    fields = collect(form)
    pola, warianty, warunkowe, zal = [], [], [], []
    for f in fields:
        keys = _label_keys(f["title"])
        if f["type"] == "FILE_UPLOADER":
            zal.append(keys)
        elif f["type"] in {"RADIO", "SELECT"} and f["options"]:
            warianty.append({"nazwa": f["title"], "opcje": [_label_keys(o)[:2] for o in f["options"]]})
        else:
            pola.append({"nazwa": f["title"], "klucze": keys, "wymagane": "REQUIRED" in f["validation"]})
        for s in f["states"]:
            if s.get("type") == "SHOW":
                opt = next((o for w in warianty for o in w["opcje"] if keys_match(o, norm(s.get("query") or ""))), None)
                if opt:
                    warunkowe.append({"pole": keys, "gdy": opt})
    return {"formularz": form.get("title"), "zrodlo": f"wzorzec COI: {path.name}", "pola": pola,
            "warianty": warianty, "warunkowe": warunkowe, "zalaczniki": zal, "poza_zakresem": [], "nie_powinno_byc": []}


def ensure_coi_gt() -> None:
    for nr in sorted(COI_TEMPLATES):
        target = GT_DIR / f"{nr}.yaml"
        src = next((ROOT / "data" / nr).rglob("konfiguracja*.json"), None)
        if target.exists() or src is None:
            continue
        gt = gt_from_coi(src)
        head = (f"# Ground truth wygenerowany automatycznie z oficjalnego wzorca COI ({src.name})\n"
                f"# przez scripts/evaluate.py: zakładki inne niż „Dane”, „Kontakt…”, FINISH.\n")
        dumper = type("NoAlias", (yaml.SafeDumper,), {"ignore_aliases": lambda self, data: True})
        target.write_text(head + yaml.dump(gt, Dumper=dumper, allow_unicode=True, sort_keys=False, width=140), "utf-8")


# ---------------------------------------------------------------- poprawność techniczna
_ORIG_SCHEMA = None


def original_schema_errors(form: dict) -> list[str]:
    global _ORIG_SCHEMA
    if _ORIG_SCHEMA is None:
        p = next((ROOT / "data").rglob("importowanyPlikJsonSchemat*.json"))
        _ORIG_SCHEMA = Draft202012Validator(json.loads(p.read_text("utf-8")))
    return [f"{'/'.join(map(str, e.absolute_path))}: {e.message[:160]}" for e in _ORIG_SCHEMA.iter_errors(form)]


def rules_errors(form: dict) -> list[str]:
    from app.rules_check import check
    return check(form)


# ---------------------------------------------------------------- metryki
def pct(a: int, b: int):
    return round(100 * a / b, 1) if b else None


def _show_ok(fld: dict, gdy: list) -> bool:
    for s in fld["states"] + fld["section_states"]:
        if isinstance(s, dict) and s.get("type") == "SHOW" and keys_match(gdy, norm(s.get("query") or "")):
            return True
    return False


def evaluate(form: dict, gt: dict, tech: bool = True) -> dict:
    fields = collect(form)
    pola, warianty = gt.get("pola") or [], gt.get("warianty") or []
    warunkowe, zal = gt.get("warunkowe") or [], gt.get("zalaczniki") or []
    poza, zlych = gt.get("poza_zakresem") or [], gt.get("nie_powinno_byc") or []

    # recall pól
    found = {i: [f for f in fields if field_matches(p["klucze"], f)] for i, p in enumerate(pola)}
    brak = [p["nazwa"] for i, p in enumerate(pola) if not found[i]]
    # wymagane
    req = [i for i, p in enumerate(pola) if p.get("wymagane")]
    req_ok = [i for i in req if any("REQUIRED" in f["validation"] for f in found[i])]
    # warianty: pole wyboru zawierające wszystkie opcje GT
    var_ok, var_miss = 0, []
    for w in warianty:
        n = len(w.get("opcje") or [])
        if any(f["type"] in CHOICE and options_cover(w, f) == n for f in fields):
            var_ok += 1
        else:
            var_miss.append(w["nazwa"])
    # warunki
    cond_ok, cond_miss = 0, []
    for c in warunkowe:
        cand = [f for f in fields if field_matches(c["pole"], f, with_options=False)]
        if any(_show_ok(f, c["gdy"]) for f in cand):
            cond_ok += 1
        else:
            cond_miss.append(f"{' '.join(c['pole'])} ⇐ {' '.join(c['gdy'])}" + ("" if cand else " (brak pola)"))
    # załączniki
    uploads = [f for f in fields if f["type"] == "FILE_UPLOADER"]
    zal_ok = [z for z in zal if any(field_matches(z, f) for f in uploads)]
    # precyzja: pole wyniku dopasowane do czegoś z GT; poza_zakresem = treść standardowa COI (nie liczy się)
    matched, extra, neutral, bad = 0, [], 0, []
    for f in fields:
        hit = (any(field_matches(p["klucze"], f) for p in pola)
               or (f["type"] in CHOICE and any(options_cover(w, f) >= 1 for w in warianty))
               or (f["type"] == "FILE_UPLOADER" and any(field_matches(z, f) for z in zal)))
        if any(field_matches(z, f, with_options=False) for z in zlych):
            bad.append(f["title"])
        if hit:
            matched += 1
        elif any(field_matches(z, f, with_options=False) for z in poza):
            neutral += 1
        else:
            extra.append(f["title"])
    judged = matched + len(extra)
    recall, precision = pct(len(pola) - len(brak), len(pola)), pct(matched, judged)
    f1 = round(2 * recall * precision / (recall + precision), 1) if recall and precision else 0.0
    # słowniki
    all_fields = collect(form, merit_only=False)
    eligible = [f for f in fields if DICT_ELIGIBLE.search(f["label"])]
    res = {
        "pola_gt": len(pola), "pola_wyniku": len(fields),
        "recall": recall, "precision": precision, "f1": f1,
        "nie_powinno_byc": len(bad), "warianty": pct(var_ok, len(warianty)), "warunki": pct(cond_ok, len(warunkowe)),
        "wymagane": pct(len(req_ok), len(req)), "zalaczniki": pct(len(zal_ok), len(zal)),
        "slowniki_pol": sum(1 for f in all_fields if f["dictionaryName"]),
        "slowniki_pokrycie": pct(sum(1 for f in eligible if f["dictionaryName"]), len(eligible)),
        "szczegoly": {"brakujace_pola": brak, "nadmiarowe_pola": extra, "neutralne_poza_zakresem": neutral,
                      "zmyslenia": bad, "brakujace_warianty": var_miss, "brakujace_warunki": cond_miss,
                      "brakujace_zalaczniki": [" ".join(z) for z in zal if z not in zal_ok],
                      "wymagane_bez_REQUIRED": [pola[i]["nazwa"] for i in req if i not in req_ok]},
    }
    if tech:
        r_err, s_err = rules_errors(form), original_schema_errors(form)
        res.update({"technicznie_ok": not r_err and not s_err, "bledy_regul": len(r_err), "bledy_schematu": len(s_err),
                    "przyklady_bledow": (r_err + s_err)[:5]})
    return res


# ---------------------------------------------------------------- wejście
def result_path(nr: str) -> Path | None:
    for p in (ROOT / "wyniki" / f"{nr}.json", OUT_DIR / f"{nr}.json"):
        if p.exists():
            return p
    return None


def load_env(path: Path) -> None:
    """Aplikacja czyta konfigurację LLM tylko z os.environ (docker env_file / start.bat) — tu wczytujemy .env."""
    if not path.exists():
        return
    for line in path.read_text("utf-8").splitlines():
        k, sep, v = line.strip().partition("=")
        if sep and k and not k.startswith("#"):
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    from app import config
    config.settings = config.Settings()


def convert_missing(forms: list[str]) -> list[str]:
    load_env(ROOT / ".env")
    from app.pipeline import convert_document
    from scripts.generate_wyniki import pick
    log, done = [], 0
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for nr in forms:
        if result_path(nr) or done >= MAX_CONVERT:
            continue
        src = pick(ROOT / "data" / nr)
        print(f"konwersja {nr}: {src.name} …", flush=True)
        try:
            out = convert_document(src.read_bytes(), src.suffix.lower().lstrip("."), True)
            (OUT_DIR / f"{nr}.json").write_text(json.dumps(out["form"], ensure_ascii=False, indent=2), "utf-8")
            t = out["trace"]
            log.append(f"{nr}: {src.name} -> źródło szkicu={t['source']} model={t['model']}"
                       + (f" ({str(t.get('reason'))[:200]})" if t.get("reason") else ""))
        except Exception as e:  # noqa: BLE001 — raportujemy, nie przerywamy oceny reszty
            log.append(f"{nr}: konwersja nieudana: {e}")
        done += 1
    return log


def git_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True,
                              timeout=10).stdout.strip() or "?"
    except Exception:  # noqa: BLE001
        return "?"


METRICS = [("recall", "Kompletność pól"), ("precision", "Precyzja"), ("f1", "F1"), ("warianty", "Warianty"),
           ("warunki", "Warunki"), ("wymagane", "Wymagane"), ("zalaczniki", "Załączniki"),
           ("slowniki_pokrycie", "Słowniki (pokrycie)")]


def averages(rows: dict) -> dict:
    avg = {}
    for k, _ in METRICS:
        vals = [r[k] for r in rows.values() if r.get(k) is not None]
        avg[k] = round(sum(vals) / len(vals), 1) if vals else None
    avg["technicznie_ok"] = f"{sum(1 for r in rows.values() if r.get('technicznie_ok'))}/{len(rows)}"
    avg["nie_powinno_byc"] = sum(r["nie_powinno_byc"] for r in rows.values())
    avg["slowniki_pol"] = sum(r["slowniki_pol"] for r in rows.values())
    return avg


def run(forms: list[str], convert: bool = False) -> dict:
    ensure_coi_gt()
    log = convert_missing(forms) if convert else []
    rows, skipped = {}, []
    for nr in forms:
        gt_p, res_p = GT_DIR / f"{nr}.yaml", result_path(nr)
        if not gt_p.exists() or res_p is None:
            skipped.append(f"{nr}: brak {'GT' if not gt_p.exists() else 'wyniku konwersji'}")
            continue
        gt = yaml.safe_load(gt_p.read_text("utf-8"))
        r = evaluate(json.loads(res_p.read_text("utf-8")), gt)
        rel = res_p.relative_to(ROOT) if res_p.is_relative_to(ROOT) else res_p
        r.update({"formularz": gt.get("formularz"), "wynik": str(rel).replace("\\", "/"),
                  "gt": "wzorzec COI" if nr in COI_TEMPLATES else "dokument źródłowy"})
        rows[nr] = r
    return {"data": dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "commit": git_commit(), "formularze": rows,
            "srednia": averages(rows) if rows else {}, "pominiete": skipped, "konwersje": log}


# ---------------------------------------------------------------- raporty
def _fmt(v) -> str:
    return "—" if v is None else (f"{v:.1f}%" if isinstance(v, float) else str(v))


DEFINITIONS = [
    ("Poprawność techniczna", "app.rules_check.check(form) == [] oraz oryginalny importowanyPlikJsonSchemat (Draft 2020-12) bez błędów."),
    ("Kompletność pól (recall)", "% pól GT, dla których w części merytorycznej wyniku jest pole z labelem zawierającym wszystkie klucze GT."),
    ("Precyzja", "% pól wejściowych części merytorycznej wyniku dopasowanych do pola/wariantu/załącznika GT (pola z poza_zakresem — treść standardowa COI — nie są liczone)."),
    ("F1", "Średnia harmoniczna kompletności i precyzji."),
    ("Zmyślenia", "Liczba pól wyniku pasujących do listy nie_powinno_byc (rzeczy, których nie ma w papierze)."),
    ("Warianty", "% wyborów z papieru odwzorowanych jako RADIO/SELECT/CHECKBOX zawierające wszystkie opcje."),
    ("Warunki", "% pól warunkowych GT, których pole lub sekcja ma states SHOW z warunkiem na właściwą opcję."),
    ("Wymagane", "% pól GT oznaczonych wymagane: true, które w wyniku mają walidację REQUIRED."),
    ("Załączniki", "% pozycji listy załączników GT odwzorowanych jako FILE_UPLOADER."),
    ("Słowniki", "Liczba pól z dictionaryName w całym formularzu; pokrycie = % pól kraj/województwo/gmina/miejscowość/numer kierunkowy w części merytorycznej ze słownikiem."),
]


def to_markdown(rep: dict) -> str:
    L = [f"# Ewaluacja Form2Norm względem ground truth", "",
         f"Wygenerowano: {rep['data']} · commit `{rep['commit']}` · `python -m scripts.evaluate --convert`", "",
         "| Nr | GT | Techn. OK | Pola GT/wynik | Kompletność | Precyzja | F1 | Zmyślenia | Warianty | Warunki | Wymagane | Załączniki | Słowniki (pola / pokrycie) |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for nr, r in rep["formularze"].items():
        L.append(f"| {nr} | {r['gt']} | {'tak' if r['technicznie_ok'] else 'NIE'} | {r['pola_gt']}/{r['pola_wyniku']} | "
                 f"{_fmt(r['recall'])} | {_fmt(r['precision'])} | {_fmt(r['f1'])} | {r['nie_powinno_byc']} | "
                 f"{_fmt(r['warianty'])} | {_fmt(r['warunki'])} | {_fmt(r['wymagane'])} | {_fmt(r['zalaczniki'])} | "
                 f"{r['slowniki_pol']} / {_fmt(r['slowniki_pokrycie'])} |")
    a = rep["srednia"]
    if a:
        L.append(f"| **średnia** | | **{a['technicznie_ok']}** | | **{_fmt(a['recall'])}** | **{_fmt(a['precision'])}** | "
                 f"**{_fmt(a['f1'])}** | **{a['nie_powinno_byc']}** | **{_fmt(a['warianty'])}** | **{_fmt(a['warunki'])}** | "
                 f"**{_fmt(a['wymagane'])}** | **{_fmt(a['zalaczniki'])}** | **{a['slowniki_pol']} / {_fmt(a['slowniki_pokrycie'])}** |")
    L += ["", "## Definicje metryk", ""] + [f"- **{n}** — {d}" for n, d in DEFINITIONS]
    L += ["", "## Ograniczenia", "",
          "- GT dla formularzy 2–4 i 6–9 napisaliśmy sami z treści dokumentów źródłowych (bez zaglądania do wyników); dla 1 i 5 wygenerowano go z oficjalnych wzorców COI.",
          "- Dopasowanie po słowach kluczowych (początek słowa, alternatywy) — synonimy spoza listy kluczy liczą się jako brak, a ogólne klucze mogą zawyżać trafienia.",
          "- GT obejmuje tylko część merytoryczną; dane wnioskodawcy, kontakt, podpis, RODO, pełnomocnictwo i opłata pochodzą z szablonów standardowych COI.",
          "- Wynik LLM jest niedeterministyczny — kolejna konwersja może dać inne liczby; ocena gotowego JSON-a jest deterministyczna.",
          "", "## Szczegóły per formularz", ""]
    for nr, r in rep["formularze"].items():
        s = r["szczegoly"]
        L.append(f"### {nr}. {r['formularz']}  (`{r['wynik']}`)")
        for k, lab in [("brakujace_pola", "Brakujące pola GT"), ("wymagane_bez_REQUIRED", "Wymagane bez REQUIRED"),
                       ("brakujace_warianty", "Brakujące warianty"), ("brakujace_warunki", "Brakujące warunki"),
                       ("brakujace_zalaczniki", "Brakujące załączniki"), ("zmyslenia", "Zmyślenia"),
                       ("nadmiarowe_pola", "Pola spoza GT (obniżają precyzję)")]:
            if s[k]:
                L.append(f"- {lab}: " + "; ".join(map(str, s[k])))
        if r.get("przyklady_bledow"):
            L.append(f"- Błędy techniczne (reguły {r['bledy_regul']}, schemat {r['bledy_schematu']}): " + "; ".join(r["przyklady_bledow"]))
        L.append("")
    for k, lab in [("pominiete", "Pominięte"), ("konwersje", "Konwersje (--convert)")]:
        if rep.get(k):
            L += [f"**{lab}:** " + "; ".join(rep[k]), ""]
    return "\n".join(L)


def _bar(v) -> str:
    if v is None:
        return '<span class="na">—</span>'
    color = "#1a7f37" if v >= 80 else "#bf8700" if v >= 50 else "#cf222e"
    return (f'<div class="bar"><div class="fill" style="width:{min(v, 100):.0f}%;background:{color}"></div>'
            f'<span>{v:.1f}%</span></div>')


def to_html(rep: dict) -> str:
    e = html.escape
    head = ["Nr", "Formularz", "Techn. OK", "Pola GT / wynik"] + [lab for _, lab in METRICS] + ["Zmyślenia", "Pola ze słownikiem"]
    rows = []
    for nr, r in rep["formularze"].items():
        ok = '<b class="ok">tak</b>' if r["technicznie_ok"] else '<b class="bad">NIE</b>'
        cells = [nr, f"{e(r['formularz'] or '')}<br><small>GT: {e(r['gt'])}</small>", ok, f"{r['pola_gt']} / {r['pola_wyniku']}"]
        cells += [_bar(r[k]) for k, _ in METRICS] + [str(r["nie_powinno_byc"]), str(r["slowniki_pol"])]
        rows.append("<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
    a = rep["srednia"]
    if a:
        cells = ["", "<b>Średnia</b>", f"<b>{a['technicznie_ok']}</b>", ""] + [_bar(a[k]) for k, _ in METRICS]
        cells += [f"<b>{a['nie_powinno_byc']}</b>", f"<b>{a['slowniki_pol']}</b>"]
        rows.append('<tr class="avg">' + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
    defs = "".join(f"<li><b>{e(n)}</b> — {e(d)}</li>" for n, d in DEFINITIONS)
    return f"""<!doctype html>
<html lang="pl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Ewaluacja Form2Norm</title>
<style>
body{{font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;margin:24px;color:#1f2328;background:#fff}}
h1{{font-size:22px;margin:0 0 4px}} .meta{{color:#59636e;margin-bottom:16px}}
table{{border-collapse:collapse;width:100%;font-size:13px}} th,td{{border-bottom:1px solid #d1d9e0;padding:6px 8px;text-align:left;vertical-align:middle}}
th{{background:#f6f8fa;font-weight:600}} tr.avg td{{background:#eef4ff;border-top:2px solid #0b57d0}}
.bar{{position:relative;background:#eaeef2;border-radius:4px;height:18px;min-width:90px}}
.fill{{height:100%;border-radius:4px}} .bar span{{position:absolute;left:6px;top:1px;font-size:12px;font-weight:600;color:#1f2328}}
.ok{{color:#1a7f37}} .bad{{color:#cf222e}} .na{{color:#8c959f}} small{{color:#59636e}} li{{margin:3px 0}}
</style></head><body>
<h1>Ewaluacja Form2Norm względem ground truth</h1>
<div class="meta">Wygenerowano {e(rep['data'])} · commit <code>{e(rep['commit'])}</code> · <code>python -m scripts.evaluate --convert</code></div>
<table><thead><tr>{''.join(f'<th>{e(h)}</th>' for h in head)}</tr></thead><tbody>{''.join(rows)}</tbody></table>
<h2 style="font-size:16px">Definicje</h2><ul>{defs}</ul>
<p><small>GT dla 2–4 i 6–9 napisany ręcznie z treści dokumentów źródłowych; dla 1 i 5 z oficjalnych wzorców COI.
Dopasowanie po słowach kluczowych. Szczegóły (brakujące i nadmiarowe pola): eval/raport.md.</small></p>
</body></html>"""


def main(argv=None) -> dict:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("forms", nargs="*", default=FORMS)
    ap.add_argument("--convert", action="store_true", help="konwertuj formularze bez wyniku (max 2, LLM z .env)")
    ap.add_argument("--out", default=str(ROOT / "eval"))
    args = ap.parse_args(argv)
    rep = run(args.forms, args.convert)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "raport.json").write_text(json.dumps(rep, ensure_ascii=False, indent=2), "utf-8")
    (out / "raport.md").write_text(to_markdown(rep), "utf-8")
    (out / "raport.html").write_text(to_html(rep), "utf-8")
    print(to_markdown(rep).split("## Definicje")[0])
    return rep


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
