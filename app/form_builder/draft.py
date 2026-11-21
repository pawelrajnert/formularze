"""Kontrakt F-06 -> F-07: kompaktowy szkic formularza, który zwraca LLM (structured output).

LLM opisuje tylko treść merytoryczną + pola sterujące (organ, applicant_kinds, proxy_allowed, fee_info).
Standardowe strony „Dane” i „Kontakt i zgody” builder wstawia z szablonów (F-14, N-C1).
Builder (F-07) dokłada resztę: UUID, techName, siatkę x/y/rows/cols, questionOrder, flow.links, tab FINISH, opisy HTML i JSONatę ze `show_if`.
Schemat dla LLM: Draft.model_json_schema().
"""
from typing import Literal

from pydantic import BaseModel, Field

FieldType = Literal[
    "TEXT_FIELD", "TEXTAREA", "NUMBER", "DATEPICKER", "SELECT", "RADIO", "CHECKBOX",
    "FILE_UPLOADER", "CONSENT_SECTION", "TEXT_BLOCK",
]
Validator = Literal["EMAIL", "PESEL", "NIP", "REGON", "ZIP_CODE", "EPUAP", "ADE", "SERIAL_NUMBER_ID_CARD"]
# musi zgadzać się z config/field_rules.yaml -> dictionaries (pilnuje tests/test_dictionaries.py)
Dictionary = Literal["", "Kraje", "TERYT_4G_DOWODOWY", "TERYT_DOWODOWY", "Numery kierunkowe"]

ApplicantKind = Literal["osoba", "firma", "inna_osoba"]


class ShowIf(BaseModel):
    field: str = Field(description="label pola sterującego (dokładnie jak w szkicu)")
    equals: str = Field(description="wartość/opcja, przy której to pole lub sekcja jest widoczne")


class DraftField(BaseModel):
    label: str
    type: FieldType
    required: bool = Field(default=False, description="true, gdy pole oznaczone jako obowiązkowe lub gwiazdką *")
    options: list[str] = Field(default_factory=list, description="tylko dla SELECT/RADIO/CHECKBOX")
    validators: list[Validator] = Field(default_factory=list)
    hint: str = Field(default="", description="podpowiedź/tooltip z formularza")
    default: str = Field(default="", description="stała wartość z formularza, np. nazwa organu")
    read_only: bool = False
    show_if: ShowIf | None = None
    dictionary: Dictionary = Field(default="", description=(
        "predefiniowany słownik zamiast options (pole staje się SELECT): Kraje - kraj/obywatelstwo; "
        "TERYT_4G_DOWODOWY - województwo/powiat/gmina/miejscowość w Polsce; Numery kierunkowe - prefiks telefonu; "
        "puste = brak (builder sam rozpozna typowe pola po labelu)"))
    prefill: str = Field(default="", description=(
        "dane inicjalne ŹRÓDŁO.atrybut tylko dla danych wnioskodawcy, np. PESEL.pesel, PESEL.name, MLPZ.name, "
        "MLPZ.surname, MLPZ.email, MLPZ.phoneNumber, MLPZ.street, MLPZ.postCode, PESEL_ADDRESS.permanentAddressPlace; "
        "źródła: PESEL, PESEL_ADDRESS, MLPZ; puste = brak (builder sam rozpozna typowe pola po labelu)"))


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
    pages: list[DraftPage] = Field(min_length=1, description=(
        "tylko strony merytoryczne; BEZ danych wnioskodawcy, adresu, pełnomocnika, opłaty, kontaktu i zgód RODO - "
        "te builder wstawia sam ze standardu; builder sam doda też stronę FINISH"))
    organ: str = Field(default="", description="nazwa organu, do którego składa się wniosek, np. Starosta Powiatu X; puste = nieznany")
    applicant_kinds: list[ApplicantKind] = Field(default_factory=lambda: ["osoba"], description=(
        "kto może złożyć wniosek: osoba - osoba fizyczna we własnym imieniu; firma - przedsiębiorca/podmiot z NIP/REGON/KRS; "
        "inna_osoba - w imieniu innej osoby (np. dziecka, podopiecznego)"))
    proxy_allowed: bool = Field(default=True, description="false tylko, gdy formularz wprost wyklucza pełnomocnika")
    fee_info: str = Field(default="", description="opłata skarbowa: kwota i za co, np. '17 zł za pełnomocnictwo'; puste = brak opłaty")
    finish_text: str = Field(default="", description="tekst na stronę końcową, np. pouczenie / klauzula RODO")
