"""Klasyfikacja dokumentu po treści (C-05). Etap A: punktacja słów kluczowych, bez LLM."""
import re

from hackcore.classes import DocClass
from hackcore.document import Document
from hackcore.llm import LLMClient


def score(doc: Document, cls: DocClass) -> float:
    text = doc.text.lower()
    return sum(k.weight for k in cls.keywords if re.search(k.pattern, text, re.IGNORECASE))


def classify(doc: Document, classes: list[DocClass], llm: LLMClient | None = None) -> DocClass | None:
    """Najlepsza klasa powyżej progu albo None (= dokument negatywny). LLM-fallback dojdzie w C-05."""
    best, best_score = None, 0.0
    for cls in classes:
        s = score(doc, cls)
        if s >= cls.threshold and s > best_score:
            best, best_score = cls, s
    return best
