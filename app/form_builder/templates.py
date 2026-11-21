"""F-14 (N-C1): standardowe sekcje COI z config/section_templates (wycięte 1:1 z wzorców 1 i 5).

Builder składa z nich stronę „Dane” i „Kontakt i zgody” wg pól sterujących szkicu; tu tylko wczytanie
i przycięcie RADIO „w czyim imieniu” / „jako kto” do dozwolonych opcji (warunki w JSONacie -> true/false).
"""
import json
import re
from pathlib import Path

DIR = Path(__file__).resolve().parents[2] / "config" / "section_templates"
_RAW = {p.stem: p.read_text("utf-8") for p in DIR.glob("*.json")}

# atom warunku na odpowiedź RADIO strony „Dane”: ("Opcja" in tabs['Dane' in title]...['tech' in field.techName].field.__userAnswer)
_ATOM = (r"\(\"([^\"]+)\" in tabs\['Dane' in title\]\.questions\['[a-z0-9_]+' in field\.techName\]"
         r"\.field\.repeatingSectionGrid\['{}' in field\.techName\]\.field\.__userAnswer\)")
_CONST = re.compile(r"(true|false|and|or|[()\s])+")


def load(name: str, **subs: str) -> list[dict]:
    """Świeża kopia bloku; {{klucz}} w treści -> subs[klucz] (już jako HTML/tekst)."""
    raw = _RAW[name]
    for k, v in subs.items():
        raw = raw.replace("{{" + k + "}}", json.dumps(v, ensure_ascii=False)[1:-1])
    qs = json.loads(raw)
    for f in walk(qs):
        f.setdefault("states", [])  # część pól we wzorcach nie ma klucza states
    return qs


def walk(qs: list[dict]):
    for q in qs:
        yield q["field"]
        yield from walk(q["field"].setdefault("repeatingSectionGrid", []))


def _const(query: str):
    """Wyrażenie bez odwołań do odpowiedzi -> True/False; inaczej None (zostaje w JSONacie)."""
    if "__userAnswer" in query:
        return None
    if not _CONST.fullmatch(query):
        raise ValueError(f"nieoczekiwany warunek w szablonie: {query!r}")
    expr = " ".join(query.split()).replace("true", "True").replace("false", "False")  # wzorce mają \r\n w środku
    return eval(expr, {"__builtins__": {}})  # tylko true/false/and/or


def _prune(qs: list[dict]) -> list[dict]:
    """Stan stale fałszywy -> element out, stale prawdziwy -> stan out; sekcja bez pól out."""
    kept = []
    for q in qs:
        f = q["field"]
        verdicts = [_const(s["query"]) for s in f["states"]]
        if False in verdicts:
            continue
        f["states"] = [s for s, v in zip(f["states"], verdicts) if v is None]
        if f["type"] in ("SECTION", "REPEATING_SECTION"):
            f["repeatingSectionGrid"] = _prune(f["repeatingSectionGrid"])
            if not f["repeatingSectionGrid"]:
                continue
        kept.append(q)
    return kept


def restrict(qs: list[dict], radio: str, allowed: list[str]) -> list[dict]:
    """Zostawia w RADIO `radio` tylko opcje `allowed`; przy jednej (albo braku pola) RADIO znika, a warunki
    na nie stają się stałymi. Elementy widoczne tylko przy usuniętej opcji wypadają."""
    field = next((f for f in walk(qs) if f["techName"] == radio), None)
    if field is None:
        allowed = []
    else:
        field["options"] = [o for o in field["options"] if o["name"] in allowed]
    single = len(allowed) <= 1
    atom = re.compile(_ATOM.format(re.escape(radio)))
    for f in walk(qs):
        for s in f["states"]:
            s["query"] = atom.sub(lambda m: "true" if single and m[1] in allowed else
                                  m[0] if m[1] in allowed else "false", s["query"])
    if field is not None and single:
        field["states"] = [{"type": "SHOW", "query": "false"}]  # RADIO z jedną opcją nie ma sensu
    return _prune(qs)
