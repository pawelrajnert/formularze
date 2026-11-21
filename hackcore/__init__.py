"""hackcore — wspólny rdzeń COI + UZP: dokument -> tekst -> klasyfikacja -> ekstrakcja -> JSON.

Źródło prawdy: repo `formularze` (COI). Do UZP kopiowane skryptem `scripts/sync-core.sh` — tam nie edytować.
"""
from hackcore.classes import DocClass, TraceItem
from hackcore.classify import classify
from hackcore.document import Document, IngestError, MissingDependency, UnsupportedFormat, load_document
from hackcore.extract import extract
from hackcore.llm import LLMClient, LLMError
from hackcore.models import (MissingAPIKey, ModelRegistryError, ModelSpec, Registry, UnknownModel, load_registry,
                             select_client, selected_model_id)

__all__ = [
    "Document", "UnsupportedFormat", "IngestError", "MissingDependency", "load_document",
    "LLMClient", "LLMError",
    "ModelSpec", "Registry", "ModelRegistryError", "UnknownModel", "MissingAPIKey", "load_registry",
    "select_client", "selected_model_id",
    "DocClass", "TraceItem", "classify", "extract",
]
