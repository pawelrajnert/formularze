"""S-02 (M): ochrona danych osobowych przed wysłaniem tekstu do LLM i do logów (RODO art. 5 ust. 1 lit. c — minimalizacja).

Działa tylko przy COMPLIANCE_ENABLED=true (domyślnie false — tryb jury). Formularz do cyfryzacji bywa WYPEŁNIONY
(skan z danymi obywatela) — do szkicu potrzebne są etykiety pól, nie wartości, więc wartości osobowe zamieniamy
na znaczniki [PESEL], [E-MAIL]… Dane jawne urzędu (numer konta do opłat, telefon/e-mail urzędu, IOD z klauzuli RODO)
zostawiamy — to treść formularza, nie dane osobowe.
"""
import os
import re
from collections import Counter

# linie z danymi instytucji — nie maskujemy (konto do opłaty skarbowej, kontakt do urzędu, IOD)
_PUBLIC_CONTEXT = re.compile(
    r"urz[aą]d|gmin|miast|starost|powiat|wojew|sekretariat|kancelari|\biod\b|inspektor\w*\s+ochrony|"
    r"administrator\w*|konto\s+(urz|bank)|rachun\w*\s+(urz|bankow\w*\s+(urz|gmin))|op[lł]at\w*\s+skarbow", re.I)

# (nazwa znacznika, wzorzec). Kolejność: dłuższe numery najpierw, żeby PESEL nie zjadł kawałka IBAN-u.
_PII: list[tuple[str, re.Pattern]] = [
    ("IBAN", re.compile(r"\b(?:PL\s?)?\d{2}(?:[ -]?\d{4}){6}\b", re.I)),
    ("E-MAIL", re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")),
    ("PESEL", re.compile(r"(?<!\d)\d{11}(?!\d)")),
    ("NIP", re.compile(r"(?<!\d)\d{3}-?\d{3}-?\d{2}-?\d{2}(?!\d)|(?<!\d)\d{3}-\d{2}-\d{2}-\d{3}(?!\d)")),
    ("REGON", re.compile(r"(?<!\d)(?:\d{14}|\d{9})(?!\d)")),
    ("TELEFON", re.compile(r"(?<![\d-])(?:\+48[ -]?)?\d{3}[ -]?\d{3}[ -]?\d{3}(?![\d-])")),
    ("DOWÓD", re.compile(r"\b[A-Z]{3}\s?\d{6}\b")),
]


def compliance_enabled() -> bool:
    return os.environ.get("COMPLIANCE_ENABLED", "false").strip().lower() in ("1", "true", "yes", "tak")


def mask_pii(text: str) -> tuple[str, Counter]:
    """Tekst z wartościami osobowymi zamienionymi na znaczniki + licznik zamian (do trace, bez samych wartości)."""
    counts: Counter = Counter()
    out = []
    for line in (text or "").split("\n"):
        if _PUBLIC_CONTEXT.search(line):
            out.append(line)
            continue
        for name, rx in _PII:
            line, n = rx.subn(f"[{name}]", line)
            if n:
                counts[name] += n
        out.append(line)
    return "\n".join(out), counts
