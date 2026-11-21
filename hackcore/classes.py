"""Typy klas dokumentów (C-05) i trace. Na etapie A tylko kontrakt — pełny loader YAML w C-05."""
from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class Keyword:
    pattern: str
    weight: float = 1.0


@dataclass
class FieldSpec:
    path: str                       # ścieżka w JSON wyjściowym, np. "odwolujacy.nip"
    regex: str | None = None
    llm: str | None = None          # opis pola dla LLM (gdy regex nie wystarcza)
    normalize: str | None = None    # date_iso | digits | nip | iban | bzp | ted | amount
    default: Any = None


@dataclass
class DocClass:
    name: str
    keywords: list[Keyword] = field(default_factory=list)
    threshold: float = 1.0
    fields: list[FieldSpec] = field(default_factory=list)
    output_template: dict = field(default_factory=dict)


@dataclass
class TraceItem:
    path: str
    value: Any
    source: Literal["regex", "llm", "default"]
    evidence: str = ""
