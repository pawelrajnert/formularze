"""Kontrakt F-06 -> F-07: kompaktowy szkic formularza, który zwraca LLM (structured output).

LLM opisuje tylko treść. Builder (F-07) dokłada resztę: UUID, techName, siatkę x/y/rows/cols,
questionOrder, flow.links, tab FINISH, opisy HTML i JSONatę ze `show_if`.
Schemat dla LLM: Draft.model_json_schema().
"""
from typing import Literal

from pydantic import BaseModel, Field

FieldType = Literal[
    "TEXT_FIELD", "TEXTAREA", "NUMBER", "DATEPICKER", "SELECT", "RADIO", "CHECKBOX",
    "FILE_UPLOADER", "CONSENT_SECTION", "TEXT_BLOCK",
]
Validator = Literal["EMAIL", "PESEL", "NIP", "REGON", "ZIP_CODE", "EPUAP", "ADE", "SERIAL_NUMBER_ID_CARD"]


class ShowIf(BaseModel):
    field: str = Field(description="label pola sterującego (dokładnie jak w szkicu)")
    equals: str = Field(description="wartość/opcja, przy której to pole lub sekcja jest widoczne")


class DraftField(BaseModel):
    label: str
    type: FieldType
    required: bool = Field(description="true, gdy pole oznaczone jako obowiązkowe lub gwiazdką *")
    options: list[str] = Field(default_factory=list, description="tylko dla SELECT/RADIO/CHECKBOX")
    validators: list[Validator] = Field(default_factory=list)
    hint: str = Field(default="", description="podpowiedź/tooltip z formularza")
    default: str = Field(default="", description="stała wartość z formularza, np. nazwa organu")
    read_only: bool = False
    show_if: ShowIf | None = None


class DraftSection(BaseModel):
    title: str
    repeating: bool = Field(default=False, description="true dla powtarzalnej listy, np. kolejni współwłaściciele")
    fields: list[DraftField] = Field(min_length=1)
    show_if: ShowIf | None = None


class DraftPage(BaseModel):
    title: str
    sections: list[DraftSection] = Field(min_length=1)


class Draft(BaseModel):
    title: str = Field(max_length=255)
    pages: list[DraftPage] = Field(min_length=1, description="strony z polami; builder sam doda stronę FINISH")
    finish_text: str = Field(default="", description="tekst na stronę końcową, np. pouczenie / klauzula RODO")
