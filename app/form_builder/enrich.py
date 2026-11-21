"""F-08: wzbogacenie zbudowanego pola wg config/field_rules.yaml: słownik, dane inicjalne, walidatory.

Jawne ustawienia ze szkicu (validators, dictionary, prefill, default) wygrywają; reguły tylko uzupełniają.
Wyjątek: prefill (jawny też) tylko w sekcjach wnioskodawcy i tylko raz na klucz.
"""
import re
import unicodedata
from pathlib import Path

import yaml

CFG = yaml.safe_load((Path(__file__).resolve().parents[2] / "config" / "field_rules.yaml").read_text("utf-8"))
RULES = [(re.compile(r["match"]), r) for r in CFG["rules"]]
SKIP_SECTIONS = re.compile(CFG["prefill_skip_sections"])
CHOICE = {"SELECT", "RADIO", "CHECKBOX"}


def norm(text: str) -> str:
    """'Adres e-mail *' -> 'adres e mail'."""
    t = unicodedata.normalize("NFKD", text.replace("ł", "l").replace("Ł", "L")).encode("ascii", "ignore").decode().lower()
    return " ".join(re.findall(r"[a-z0-9]+", t))


def rule(label: str) -> dict:
    n = norm(label)
    return next((r for rx, r in RULES if rx.search(n)), {})


def dictionary(f) -> str:
    """Słownik dla pola szkicu: jawny (f.dictionary) albo z reguły - tylko dla TEXT_FIELD/SELECT (listy rozwijane)."""
    if f.dictionary:
        return f.dictionary
    r = rule(f.label)
    if r.get("dictionary") and (f.type == "SELECT" or (f.type == "TEXT_FIELD" and r.get("convert", True))):
        return r["dictionary"]
    return ""


def enrich(out: dict, f, used: set, section: str, repeating: bool) -> None:
    """Modyfikuje `out` w miejscu. `used` - klucze prefill już przypisane w formularzu."""
    r = rule(f.label)
    d = dictionary(f)
    if d and out["type"] in CHOICE | {"TEXT_FIELD"}:
        cfg = CFG["dictionaries"].get(d, {})
        if out["type"] == "TEXT_FIELD":
            out["type"] = "SELECT"
        # reguły techniczne: pole ze słownikiem ma pustą tablicę options, defaultValue jako lista
        out |= {"options": [], "dictionaryName": d, "multiLevelTree": cfg.get("multiLevelTree", False),
                "searchEnabled": cfg.get("searchEnabled", True),
                "defaultValue": [f.default] if f.default else list(cfg.get("default", []))}
        return
    if out["type"] == "TEXT_FIELD":
        out["validation"] += [v for v in r.get("validators", []) if v not in out["validation"]]
    # jawny prefill ze szkicu też tylko dla wnioskodawcy (LLM wpisywał MLPZ/PESEL w dane sportowca, osoby odpowiedzialnej)
    key = f.prefill or ("" if f.default else r.get("prefill", ""))
    if key in used or repeating or SKIP_SECTIONS.search(norm(section)):
        key = ""
    src = key.split(".")[0]
    if key and src in CFG["sources"] and out["type"] in ("TEXT_FIELD", "DATEPICKER"):
        used.add(key)
        out |= {"defaultValue": key, "defaultValueType": "EXTERNAL_SYSTEM",
                "readOnly": out["readOnly"] or r.get("read_only", False) or src in CFG["registry_sources"]}
