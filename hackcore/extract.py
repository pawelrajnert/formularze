"""Ekstrakcja pól klasy (C-05): regexy -> jedno wywołanie LLM -> normalizery. Etap A: tylko regexy."""
import copy
import re

from hackcore.classes import DocClass, TraceItem
from hackcore.document import Document
from hackcore.llm import LLMClient


def _set(out: dict, path: str, value) -> None:
    node = out
    *parents, last = path.split(".")
    for p in parents:
        node = node.setdefault(p, {})
    node[last] = value


def extract(doc: Document, cls: DocClass, llm: LLMClient | None = None) -> tuple[dict, list[TraceItem]]:
    out = copy.deepcopy(cls.output_template)
    trace: list[TraceItem] = []
    for f in cls.fields:
        m = re.search(f.regex, doc.text, re.IGNORECASE | re.MULTILINE) if f.regex else None
        if m:
            value = m.group(1) if m.groups() else m.group(0)
            trace.append(TraceItem(f.path, value, "regex", m.group(0)[:200]))
        else:
            value = f.default
            trace.append(TraceItem(f.path, value, "default"))
        _set(out, f.path, value)
    return out, trace
