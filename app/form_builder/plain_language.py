"""N-C3: asystent prostego języka (część reguł).

check_plain_language(form) -> lista sugestii dla tekstów widocznych dla obywatela w JSON-ie formularza COI
(tytuł formularza, tytuły stron, etykiety, opisy, podpowiedzi, opcje, treść zgód).
Reguły: config/plain_language.yaml (z odnośnikami do rozdziału 1 Standardu). Deterministycznie, bez LLM.
Funkcja niczego nie zmienia w formularzu — zwraca tylko sugestie (pole `zamiana` = gotowa podmiana fragmentu,
gdy jest prosta; UI może z niej zrobić przycisk „zastosuj”).

CLI: python -m app.form_builder.plain_language wyniki/4.json [--json]
"""
import html
import json
import re
import sys
from functools import lru_cache
from pathlib import Path

import yaml

RULES_PATH = Path(__file__).resolve().parents[2] / "config" / "plain_language.yaml"

_BLOCK_TAGS = re.compile(r"<\s*(?:br|/p|/li|/div|/h\d|/tr|li)\b[^>]*>", re.I)
_TAGS = re.compile(r"<[^>]+>")
_HEAD = re.compile(r"<head\b.*?</head>", re.I | re.S)
_TECH_VALUE = re.compile(r"^[A-Z]+\.\w+$")  # MLPZ.name, PESEL.pesel — źródło danych, nie tekst
_SENT_END = re.compile(r"(?<=[.!?])\s+(?=[^\s])|\n+")
_VOWELS = "aeiouyąęó"


def html_to_text(s: str) -> str:
    """HTML z opisu pola -> zwykły tekst (bloki = nowe linie, encje rozwinięte, białe znaki znormalizowane)."""
    if not s:
        return ""
    s = _HEAD.sub("", s)
    s = _BLOCK_TAGS.sub("\n", s)
    s = html.unescape(_TAGS.sub(" ", s)).replace("\xa0", " ")
    lines = (" ".join(line.split()) for line in s.split("\n"))
    return "\n".join(line for line in lines if line)


def syllables(word: str) -> int:
    """Przybliżona liczba sylab: samogłoski minus „i” przed samogłoską (nie-, -cja, -ści-)."""
    w = word.lower()
    n = sum(ch in _VOWELS for ch in w)
    return n - len(re.findall(rf"i(?=[{_VOWELS}])", w))


class Rule:
    def __init__(self, raw: dict):
        self.id: str = raw["id"]
        self.raw = raw
        self.check: str | None = raw.get("sprawdzenie")
        self.where: set[str] | None = set(raw["dotyczy"]) if raw.get("dotyczy") else None
        self.level: str = raw.get("poziom", "ostrzeżenie")
        self.message: str = raw["komunikat"]
        self.hint: str = raw.get("propozycja", "")
        self.source: str = raw.get("zrodlo", "")
        self.replacements = {str(k).lower(): str(v) for k, v in (raw.get("zamiany") or {}).items()}
        self.skip_proper = bool(raw.get("pomijaj_nazwy_wlasne"))
        self.regex = re.compile(rf"(?<!\w)(?:{raw['regex']})(?!\w)", re.I | re.M) if raw.get("regex") else None
        exc = raw.get("wyjatki")
        if isinstance(exc, str):
            self.exception = re.compile(exc, re.I)
            self.exception_words: set[str] = set()
        else:
            self.exception = None
            self.exception_words = {w.lower() for w in (exc or [])}

    def applies(self, where: str) -> bool:
        return self.where is None or where in self.where


@lru_cache(maxsize=4)
def load_rules(path: str = str(RULES_PATH)) -> tuple[Rule, ...]:
    data = yaml.safe_load(Path(path).read_text("utf-8"))
    return tuple(Rule(r) for r in data["reguly"])


def _match_case(src: str, repl: str) -> str:
    if src.isupper() and len(src) > 1:
        return repl.upper()
    if src[:1].isupper():
        return repl[:1].upper() + repl[1:]
    return repl


def _sentence_start(text: str, pos: int) -> bool:
    before = text[:pos].rstrip(" \t\"„'(")
    return not before or before[-1] in ".!?:\n"


# --- reguły strukturalne -----------------------------------------------------------------------------

_CHUNK = re.compile(r"\S+")
_LETTERS = re.compile(r"[^\W\d_]+")


def _caps_runs(text: str, rule: Rule):
    """-> (fragment, pozycja) dla ciągów słów pisanych WERSALIKAMI (bez znanych skrótów i krótkich akronimów)."""
    known = {a.upper() for a in rule.raw.get("akronimy", [])}
    min_len = int(rule.raw.get("min_liter", 4))
    run: list[tuple[int, int]] = []
    for m in _CHUNK.finditer(text):
        word = m.group(0).strip(".,;:!?()\"„”'–-")
        caps = (_LETTERS.fullmatch(word) is not None and word.isupper() and len(word) >= min_len
                and word not in known)  # „_”, cyfry, kropki w środku -> nazwa techniczna, nie wersaliki
        if caps:
            start = m.start() + m.group(0).find(word)
            run.append((start, start + len(word)))
        elif run:
            yield text[run[0][0]:run[-1][1]], run[0][0]
            run = []
    if run:
        yield text[run[0][0]:run[-1][1]], run[0][0]


def _structural(rule: Rule, text: str):
    """-> (fragment, zamiana | None) dla reguł bez regexu."""
    if rule.check == "wersaliki":
        for frag, pos in _caps_runs(text, rule):
            low = frag.lower()
            yield frag, (low[:1].upper() + low[1:]) if _sentence_start(text, pos) else low
    elif rule.check == "dlugosc":
        limit = int(rule.raw.get("max_znakow", 80))
        if len(text) > limit:
            yield text, None
    elif rule.check == "dlugie_zdanie":
        limit = int(rule.raw.get("max_slow", 25))
        for sent in _SENT_END.split(text):
            if len(sent.split()) > limit:
                yield sent, None
    elif rule.check == "dlugie_slowo":
        limit = int(rule.raw.get("min_sylab", 7))
        for m in _LETTERS.finditer(text):
            w = m.group(0)
            if w.isupper() or w.lower() in rule.exception_words:
                continue
            if syllables(w) >= limit:
                yield w, None


def _regex_hits(rule: Rule, text: str):
    for m in rule.regex.finditer(text):
        frag = m.group(0)
        if rule.exception and rule.exception.fullmatch(frag):
            continue
        if rule.skip_proper and frag[:1].isupper() and not _sentence_start(text, m.start()):
            continue
        repl = rule.replacements.get(" ".join(frag.lower().split()))
        yield frag, (_match_case(frag, repl) if repl else None)


def check_text(text: str, where: str, rules: tuple[Rule, ...] | None = None) -> list[dict]:
    """Sugestie dla jednego tekstu (już bez HTML). where: title/description/tooltip/opcja/zgoda/wartosc/strona/formularz."""
    rules = rules if rules is not None else load_rules()
    out, seen = [], set()
    if not text or not text.strip():
        return out
    for rule in rules:
        if not rule.applies(where):
            continue
        hits = _regex_hits(rule, text) if rule.regex else _structural(rule, text)
        for frag, repl in hits:
            key = (rule.id, frag.lower())
            if key in seen:
                continue
            seen.add(key)
            out.append({"fragment": frag, "regula": rule.id, "poziom": rule.level, "komunikat": rule.message,
                        "propozycja": rule.hint, "zamiana": repl, "zrodlo": rule.source})
    return out


# --- przejście po formularzu --------------------------------------------------------------------------

def _texts(form: dict):
    """(kontekst, gdzie, ścieżka JSON, tekst) dla wszystkich tekstów widocznych dla obywatela."""
    if isinstance(form.get("title"), str):
        yield {"techName": None, "fieldId": None, "typ": "FORM", "strona": None, "pole": None}, "formularz", "title", form["title"]
    for ti, tab in enumerate(form.get("tabs") or []):
        tab_title = tab.get("title") or ""
        yield ({"techName": None, "fieldId": tab.get("id"), "typ": "TAB", "strona": tab_title, "pole": None},
               "strona", f"tabs[{ti}].title", tab_title)
        yield from _walk(tab.get("questions") or [], f"tabs[{ti}].questions", tab_title)


def _walk(questions: list, path: str, tab_title: str):
    for qi, q in enumerate(questions):
        f = q.get("field") if isinstance(q, dict) else None
        if not isinstance(f, dict):
            continue
        p = f"{path}[{qi}].field"
        ctx = {"techName": f.get("techName"), "fieldId": f.get("id"), "typ": f.get("type"),
               "strona": tab_title, "pole": f.get("title") or ""}
        if isinstance(f.get("title"), str):
            yield ctx, "title", f"{p}.title", f["title"]
        if isinstance(f.get("description"), str):
            yield ctx, "description", f"{p}.description", html_to_text(f["description"])
        if isinstance(f.get("tooltipMessage"), str):
            yield ctx, "tooltip", f"{p}.tooltipMessage", html_to_text(f["tooltipMessage"])
        dv = f.get("defaultValue")
        if isinstance(dv, str) and not _TECH_VALUE.match(dv.strip()):
            yield ctx, "wartosc", f"{p}.defaultValue", dv
        if not f.get("dictionaryName"):  # opcji ze słowników centralnych urzędnik i tak nie zmieni
            for oi, opt in enumerate(f.get("options") or []):
                if isinstance(opt, dict) and isinstance(opt.get("name"), str):
                    yield ctx, "opcja", f"{p}.options[{oi}].name", opt["name"]
        consents = (f.get("consentSectionConfig") or {}).get("consents") or []
        for ci, c in enumerate(consents):
            if isinstance(c, dict) and isinstance(c.get("description"), str):
                yield ctx, "zgoda", f"{p}.consentSectionConfig.consents[{ci}].description", html_to_text(c["description"])
        yield from _walk(f.get("repeatingSectionGrid") or [], f"{p}.repeatingSectionGrid", tab_title)


def check_plain_language(form: dict, rules: tuple[Rule, ...] | None = None) -> list[dict]:
    """Sugestie prostego języka dla całego formularza COI. Nie modyfikuje `form`.

    Każda sugestia: techName, fieldId, typ, strona, pole, gdzie, sciezka, tekst, fragment, regula, poziom,
    komunikat, propozycja, zamiana (str | None), zrodlo.
    """
    rules = rules if rules is not None else load_rules()
    out: list[dict] = []
    for ctx, where, path, text in _texts(form):
        for hit in check_text(text, where, rules):
            out.append({**ctx, "gdzie": where, "sciezka": path, "tekst": text[:300], **hit})
    return out


def summary(suggestions: list[dict]) -> dict:
    """Liczniki do karty w UI / trace."""
    by_rule: dict[str, int] = {}
    for s in suggestions:
        by_rule[s["regula"]] = by_rule.get(s["regula"], 0) + 1
    return {"razem": len(suggestions), "bledy": sum(s["poziom"] == "błąd" for s in suggestions),
            "ostrzezenia": sum(s["poziom"] != "błąd" for s in suggestions), "wg_reguly": by_rule}


def _print(path: str, suggestions: list[dict]) -> None:
    s = summary(suggestions)
    print(f"== {path}: {s['razem']} sugestii (błędy: {s['bledy']}, ostrzeżenia: {s['ostrzezenia']})")
    for x in suggestions:
        where = x["techName"] or x["strona"] or "formularz"
        repl = f" → „{x['zamiana']}”" if x["zamiana"] else ""
        print(f"  [{x['poziom']}] {x['regula']} | {where} ({x['gdzie']}): „{x['fragment'][:90]}”{repl}")
        print(f"      {x['komunikat']} {x['propozycja']}")


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    if not args:
        print("użycie: python -m app.form_builder.plain_language plik.json [plik2.json ...] [--json]", file=sys.stderr)
        return 2
    result = {}
    for p in args:
        result[p] = check_plain_language(json.loads(Path(p).read_text("utf-8")))
    if "--json" in argv:
        print(json.dumps(result, ensure_ascii=False, indent=1))
    else:
        for p, sug in result.items():
            _print(p, sug)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
