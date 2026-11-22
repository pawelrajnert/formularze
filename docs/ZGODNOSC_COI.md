# Zgodność ze standardem COI i rozszerzenia

Słowniki, dane inicjalne, walidacje, warunki JSONata, nowy słownik, prosty język, walidator reguł i świadome decyzje.

[← powrót do README](../README.md)

## Zrealizowane rozszerzenia

- **Słowniki i dane inicjalne** (`config/field_rules.yaml`, rozpoznawane po labelu pola).
  - Słowniki: `Kraje` (domyślnie `Polska`), `TERYT_4G_DOWODOWY` i `TERYT_DOWODOWY` (drzewo, jedno pole na sekcję), `Numery kierunkowe`. Pole ze słownikiem staje się `SELECT` z pustym `options`.
  - Dane inicjalne (`defaultValueType: EXTERNAL_SYSTEM`):
    - `PESEL.pesel`, `PESEL.familyName`, `PESEL.birthDate`, `PESEL.birthPlace`, `PESEL.fatherName`, `PESEL.motherName`,
    - `MLPZ.name`, `MLPZ.secondName`, `MLPZ.surname`, `MLPZ.email`, `MLPZ.phoneNumber`, `MLPZ.street`, `MLPZ.building`, `MLPZ.apartment`, `MLPZ.postCode`.
  - Pola z rejestrów (`PESEL`, `PESEL_ADDRESS`) oraz imię i nazwisko dostają `readOnly`.
  - Prefill trafia tylko do danych wnioskodawcy. Pomijamy sekcje pełnomocnika, współwłaściciela itp., sekcje powtarzalne i kolejne wystąpienia tego samego klucza.
- **Walidacje pól:** `PESEL`, `NIP`, `REGON`, `EMAIL`, `ZIP_CODE`, `EPUAP`, `ADE`, `SERIAL_NUMBER_ID_CARD`. Pochodzą z LLM albo z reguł po labelu. `REQUIRED` stawiamy tam, gdzie formularz oznacza pole jako obowiązkowe lub gwiazdką.
- **Zależności i stany (JSONata):** `show_if` ze szkicu zamieniamy na `states: [{type: "SHOW", query: "('opcja' in tabs['Strona' in title].questions[...]....__userAnswer)"}]`. Gdy słownik zastąpił opcje typu „Polska / Inny kraj”, powstaje warunek `$not(...)`.
- **Frontend z podglądem na żywo** (`GET /`): logowanie, upload z paskiem postępu etapów (wysyłanie → odczyt/OCR → AI tworzy szkic → walidacja), render formularza z JSON-a, działające stany JSONata (vendored `web/vendor/jsonata.min.js`), podgląd `trace` i pobranie JSON-a.
- **Nowy słownik (propozycja, F-10):** system wykrywa w formularzach zamknięte listy wyboru, które warto przenieść do słownika wspólnego (pomija Tak/Nie, sekcje standardowe i istniejące słowniki; deterministycznie, bez LLM). Propozycja = co najmniej 3 pozycje i (powtarza się w kilku polach/formularzach albo ma co najmniej 6 pozycji). Struktura: `nazwa` (np. `SPOSOB_ZWROTU_OPLATY`), `etykieta`, `opis`, `zastosowanie`, `struktura` {`multiLevelTree`, `searchEnabled`}, `pozycje` [{`kod`, `nazwa`}], `wystapienia`, `uzasadnienie`, `pewnosc`. Po akceptacji pole dostaje `dictionaryName` zamiast własnych `options`. Dla jednego formularza: `trace.proposedDictionaries` i karta w UI; dla całego zbioru: `python -m scripts.propose_dictionaries` → `wyniki/slowniki/proponowane_slowniki.json` (4 propozycje, m.in. `SPOSOB_ZWROTU_OPLATY` wspólny dla formularzy 2 i 5, `DYSCYPLINY_SPORTOWE` — 20 pozycji z wyszukiwarką).
- **Asystent prostego języka (N-C3):** 19 reguł z rozdziału 1 „Standardów i dobrych praktyk” COI (`config/plain_language.yaml`, każda z numerem strony standardu): zakazane słowa („dokonać”, „posiadać”, „informujemy”…), formy bezosobowe i strona bierna, imiesłowy na -ąc, formy zależne od płci, skróty, wersaliki, za długie etykiety i zdania. Sugestie w `trace.plain_language` i w karcie UI z przyciskiem „Zastosuj” (JSON nigdy nie zmienia się sam). Wzorce COI dają 0 sugestii (test). CLI: `python -m app.form_builder.plain_language wyniki/4.json`.

### Zgodność z regułami

Walidator można uruchomić osobno:

```bash
python -m app.rules_check wyniki/2.json   # wypisuje „OK” albo listę błędów, exit 1 przy błędach
```

Sprawdza JSON Schema i reguły techniczne:

- co najmniej 2 strony, ostatnia `FINISH` bez pól wejściowych, pozostałe `MAIN`;
- każda strona ma co najmniej jedno pole, a każde pole leży w `SECTION` lub `REPEATING_SECTION`;
- sekcje nie są zagnieżdżone;
- wszystkie id to unikalne UUID;
- każde pole ma jawne `validation`;
- słowniki i opcje występują tylko przy `SELECT`, `RADIO` i `CHECKBOX`;
- stany to wyłącznie `SHOW`/`READ_ONLY` z niepustym `query`;
- tytuł ma najwyżej 255 znaków;
- `flow.links` łączą wszystkie strony.

Świadome decyzje:

- **`repeatingSectionGrid`:** schemat ma literówkę `repetingSectionGrid`, ale przykłady COI i JSONata używają `repeatingSectionGrid`. Kopia schematu w `config/form_schema.json` ma poprawioną nazwę.
- **`validation`:** zawsze jest listą, a pusta lista oznacza pole opcjonalne. Przykład 1 ma `validation: {}`, uznajemy to za odchylenie.
- **`flow.links[].id`:** zawsze UUID. Przykład 5 ma krótkie id.
- **`defaultValue`:** to string albo tablica. Reguły techniczne podają `[]` dla pól wyboru, a schemat dopuszcza tylko string, więc kopia schematu dopuszcza oba warianty. RADIO nie dostaje `defaultValue` (jak we wzorcach 1/5), a NUMBER nigdy.
- **Dane kontaktowe z profilu (MLPZ: adres, telefon, e-mail) są edytowalne** (`defaultValueType: EXTERNAL_SYSTEM`, `readOnly: false`), tak jak w oficjalnych wzorcach COI 1 i 5. Dokument „Dane inicjalne” mówi o `readOnly` dla pól zasilanych danymi inicjalnymi — stosujemy to do danych z rejestru PESEL (imię, nazwisko, PESEL: `readOnly: true`), a dane kontaktowe zostawiamy do poprawienia przez obywatela (nieaktualny telefon czy adres korespondencyjny nie może blokować wniosku).
- **Walidatory w sekcjach standardowych:** `ZIP_CODE` (polskie kody pocztowe), `EMAIL`, `NIP`, `REGON`, `PESEL` — wzorce mają tu `[]`, reguły techniczne dopuszczają walidatory, więc je dodajemy (lepsze dane dla urzędu). Warianty zagraniczne bez `ZIP_CODE`.
