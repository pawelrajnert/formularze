# COI — cyfryzacja formularzy

Usługa REST, która z pojedynczego pliku papierowego formularza urzędowego (PDF, DOC, DOCX, ODS, XLSX, JPG, JPEG, PNG) tworzy JSON formularza elektronicznego zgodny ze schematem `importowanyPlikJsonSchemat.json` i z „Regułami technicznymi konfiguracji formularzy” COI. Model językowy opisuje tylko treść formularza (strony, sekcje, pola). Całą resztę (UUID, siatkę, przejścia, stronę końcową, warunki JSONata, słowniki, dane inicjalne) dokłada deterministyczny builder. Na końcu wynik sprawdza walidator reguł. Dołączony frontend pozwala wgrać plik i od razu zobaczyć podgląd formularza.

## Jak to działa

```
plik ──► walidacja (nazwa, rozszerzenie, MIME z treści, rozmiar)          app/validation.py
     ──► ekstrakcja tekstu                                                app/ingest.py
           PDF: warstwa tekstowa (pypdfium2), skan → OCR (Tesseract, pol)
           DOCX/XLSX: python-docx / openpyxl · DOC/ODS: LibreOffice → DOCX/XLSX
           JPG/PNG: OCR
     ──► szkic LLM: few-shot (formularz 1) + structured output (JSON Schema Draft)   app/form_builder/llm_draft.py
           │  brak konfiguracji LLM / 429 / timeout / zły JSON / szkic odrzucony przez walidator
           └─► fallback heurystyczny (etykiety z „…”, „:”, nagłówków)    app/form_builder/fallback.py
     ──► builder: UUID, techName, siatka x/y/rows/cols, questionOrder,
           flow.links, strona FINISH, stany JSONata z show_if            app/form_builder/builder.py
     ──► wzbogacanie wg config/field_rules.yaml: słowniki, walidatory,
           dane inicjalne (EXTERNAL_SYSTEM, readOnly)                    app/form_builder/enrich.py
     ──► walidator reguł COI (JSON Schema + reguły techniczne)           app/rules_check.py
     ──► JSON
```

Szkic LLM (`app/form_builder/draft.py`, model pydantic `Draft`) jest celowo mały: strony → sekcje (`repeating`, `show_if`) → pola (`label`, `type`, `required`, `options`, `validators`, `hint`, `default`, `read_only`, `show_if`, `dictionary`, `prefill`). Mniejszy model popełnia wtedy mniej błędów strukturalnych, a reguły techniczne pilnuje kod.

## Szybki start (Docker)

```bash
cp .env.example .env
# uzupełnij: LLM_API_KEY, AUTH_PASSWORD, JWT_SECRET (np. openssl rand -hex 32)
docker compose up --build
```

- frontend: http://localhost:8000
- OpenAPI (Swagger): http://localhost:8000/docs

Bez `LLM_API_KEY` usługa też działa, ale tylko na szkicu heurystycznym (gorsza jakość).

## Uruchomienie bez Dockera

Wymagane narzędzia systemowe: Python 3.14, Tesseract z pakietem `pol` oraz LibreOffice (tylko dla DOC i ODS).

```bash
# macOS:  brew install tesseract tesseract-lang && brew install --cask libreoffice
# Debian: apt install tesseract-ocr tesseract-ocr-pol libreoffice-writer-nogui libreoffice-calc-nogui
uv venv --python 3.14 && source .venv/bin/activate   # albo: python3.14 -m venv .venv
uv pip install -r requirements.txt                    # albo: pip install -r requirements.txt
cp .env.example .env   # uzupełnij
uvicorn app.main:app --env-file .env --port 8000
```

Aplikacja czyta konfigurację tylko ze zmiennych środowiskowych. Sama nie wczytuje `.env`, dlatego plik przekazujemy flagą `--env-file` (przy skryptach: `set -a; source .env; set +a`). Na macOS `soffice` jest szukany także w `/Applications/LibreOffice.app`.

## Budowanie obrazu

```bash
docker build -t coi-formularze:1.0 .
docker run --rm -p 8000:8000 --env-file .env coi-formularze:1.0
```

- Bazą jest oficjalny `python:3.14.10-slim-bookworm` z przypiętą wersją (nie `latest`).
- W obrazie są `tesseract-ocr`, `tesseract-ocr-pol` i headless LibreOffice (`libreoffice-writer-nogui`, `libreoffice-calc-nogui`).
- Aplikacja działa jako użytkownik bez roota `appuser` (uid 1000). Obraz wystawia tylko port 8000.
- Sekrety podajemy wyłącznie w runtime przez zmienne środowiskowe (`env_file` w compose). `.env` jest w `.dockerignore` i nie trafia do obrazu.
- Obraz waży ok. 0,9 GB (zmierzone: 924 MB). Większość to LibreOffice, który jest potrzebny do formatów DOC i ODS.
- Dlaczego nie Alpine: Tesseract z danymi `pol`, LibreOffice i binarne wheele (pypdfium2, pillow, lxml, pydantic-core) na musl to ryzyko braków i kompilacji ze źródeł. Wymóg „lekkiego obrazu” spełniamy wariantem `slim` i instalacją `--no-install-recommends`.

## Konfiguracja (zmienne środowiskowe)

Wszystkie zmienne pochodzą z `app/config.py`. Wzór jest w `.env.example`.

| Zmienna | Opis | Domyślna |
|---|---|---|
| `LLM_BASE_URL` | Endpoint zgodny z OpenAI API (Mistral: `https://api.mistral.ai/v1`, Ollama: `http://ollama:11434/v1`) | puste (wtedy LLM wyłączony, działa tylko heurystyka) |
| `LLM_API_KEY` | Klucz API (`ollama` dla lokalnej Ollamy) | puste |
| `LLM_MODEL` | Nazwa modelu (`ministral-14b-latest` w API, `ministral-3:14b` w Ollamie) | puste |
| `OCR_LANG` | Język Tesseracta | `pol` |
| `MAX_FILE_SIZE_MB` | Maksymalny rozmiar pliku w MB | `20` |
| `AUTH_ENABLED` | `true` oznacza, że `/forms/convert` wymaga JWT. `false` wyłącza autoryzację (demo lokalne) | `true` |
| `AUTH_USER` | Login do `/auth/token` | `admin` |
| `AUTH_PASSWORD` | Hasło do `/auth/token`. Gdy jest puste, endpointy z autoryzacją zwracają 503 | puste |
| `JWT_SECRET` | Sekret do podpisu JWT. Gdy jest pusty, zwracają 503 | puste |
| `JWT_ALGORITHM` | Algorytm JWT (PyJWT) | `HS256` |
| `JWT_EXPIRE_MINUTES` | Czas ważności tokenu w minutach | `60` |

LLM jest używany tylko wtedy, gdy ustawione są wszystkie trzy zmienne `LLM_*`.

## REST API

| Metoda i ścieżka | Opis |
|---|---|
| `POST /api/v1/auth/token` | Body JSON `{"username", "password"}`. Zwraca `{"access_token", "token_type": "bearer"}` |
| `POST /api/v1/forms/convert` | `multipart/form-data`, pole `file`, nagłówek `Authorization: Bearer <token>`, query `debug=false` |
| `GET /health` | `{"status": "ok"}` (healthcheck w compose) |
| `GET /` | frontend (`web/index.html`) |
| `GET /docs` | OpenAPI / Swagger UI (FastAPI) |

Odpowiedź `200` z `/forms/convert`:

```json
{ "filename": "wniosek.pdf", "form": { "title": "…", "tabs": [ … ], "flow": { "links": [ … ] } } }
```

Przy `debug=true` odpowiedź dodatkowo zawiera:

- `draft`: szkic, z którego zbudowano formularz (LLM albo heurystyka),
- `trace`: `{"source": "llm" | "heuristic", "reason": "<dlaczego fallback>", "text_chars": <długość tekstu>, "rules_errors": [<błędy walidatora szkicu LLM>]}`.

Kody błędów:

| Kod | Kiedy |
|---|---|
| `400` | Zła nazwa pliku: pusta, dłuższa niż 250 znaków albo zawiera `; : > < / \ \| ' * % $` |
| `401` | Brak tokenu, zły lub wygasły token. Przy `/auth/token`: zły login lub hasło |
| `413` | Plik większy niż `MAX_FILE_SIZE_MB`. Sprawdzane po `Content-Length` i ponownie przy czytaniu strumienia |
| `415` | Rozszerzenie spoza whitelisty albo typ wykryty z treści nie zgadza się z rozszerzeniem |
| `422` | Brak pola `file` (walidacja FastAPI), nie udało się odczytać pliku (uszkodzony, brak OCR lub LibreOffice) albo formularz nie przeszedł walidacji reguł |
| `503` | Autoryzacja włączona, ale nie ustawiono `JWT_SECRET` lub `AUTH_PASSWORD` |

Błąd albo timeout LLM nie kończy się kodem błędu. Pipeline przechodzi wtedy na szkic heurystyczny, dlatego `504` nie jest używany.

Przykład:

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/token \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"<AUTH_PASSWORD>"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')

curl -s -X POST "http://localhost:8000/api/v1/forms/convert?debug=true" \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@wniosek.pdf" -o wynik.json
```

## LLM: API albo model lokalny

Domyślnie korzystamy z API Mistral i modelu `ministral-14b-latest`, czyli **Ministral 3 14B** z otwartymi wagami na licencji Apache-2.0. Klient to biblioteka `openai`, więc działa z każdym endpointem zgodnym z OpenAI API. Jedno żądanie to jedno wywołanie modelu z `temperature=0` i `response_format=json_schema`. Przy odpowiedzi 429 klient czeka 31 s i próbuje ponownie, najwyżej 3 razy. Timeout to 90 s, a tekst jest ucinany do 30 000 znaków.

**Przełączenie na model lokalny (Ollama):**

1. W Docker Desktop przydziel co najmniej 8 GB RAM (Settings → Resources). Na Windowsie robi się to w `.wslconfig`.
2. Uruchom usługi z profilem Ollamy:
   ```bash
   docker compose --profile local-llm up --build
   ```
3. Pobierz model:
   ```bash
   docker compose exec ollama ollama pull ministral-3:14b   # albo ministral-3:8b na maszynie z 16 GB RAM
   ```
4. Ustaw w `.env`:
   ```
   LLM_BASE_URL=http://ollama:11434/v1
   LLM_API_KEY=ollama
   LLM_MODEL=ministral-3:14b
   ```
   Przy mniejszym modelu wpisz `ministral-3:8b`.
5. Zrestartuj aplikację: `docker compose --profile local-llm up -d app`.

Ollama nie wystawia portu na hosta i jest dostępna tylko w sieci compose. Modele trzymamy w wolumenie `ollama-models`.

Czas na CPU: **TODO: X s/formularz** (jeszcze niezmierzony). Przez API Ministral 14B potrzebuje ok. 45 s na formularz 1.

**Bez LLM:** gdy brakuje konfiguracji, LLM jest niedostępny albo jego szkic nie przechodzi walidatora, formularz powstaje ze szkicu heurystycznego. Ten wynik też przechodzi przez builder i walidator, więc zwykle dostajemy poprawny JSON. 422 pojawia się tylko wtedy, gdy nie da się odczytać tekstu albo nawet szkic heurystyczny nie przejdzie walidacji.

## Bezpieczeństwo

- **Whitelista rozszerzeń:** `pdf, doc, docx, ods, xlsx, jpg, jpeg, png`.
- **Typ z treści:** sygnatura pliku przez `filetype`. DOCX, XLSX i ODS sprawdzamy przez spis plików ZIP (`word/document.xml`, `xl/workbook.xml`, `mimetype`). Archiwum nie jest rozpakowywane, co chroni przed zip-bombą. Typ niezgodny z rozszerzeniem daje 415.
- **Nazwa pliku:** najwyżej 250 znaków, bez `; : > < / \ | ' * % $`.
- **Limit rozmiaru:** `MAX_FILE_SIZE_MB`. Za duże ciało żądania jest odrzucane już po nagłówku `Content-Length`, a strumień jest dodatkowo czytany porcjami z limitem.
- **Pliki w pamięci:** upload nie trafia do pliku tymczasowego (`spool_max_size` w Starlette jest podniesiony) i nie zapisujemy go trwale. Są dwa wyjątki, oba usuwane po żądaniu:
  - DOC i ODS: plik trafia do katalogu `tempfile.TemporaryDirectory`, gdzie jest też profil LibreOffice. Katalog jest kasowany po konwersji, a timeout `soffice` wynosi 60 s.
  - OCR: `pytesseract` przekazuje obraz Tesseractowi przez plik tymczasowy, który kasuje zaraz po odczycie.
- **JWT (PyJWT):** sekret, algorytm i czas ważności ustawiamy w env. Hasło porównujemy w stałym czasie (`hmac.compare_digest`). Gdy brakuje sekretu lub hasła, usługa zwraca 503 i nie wydaje tokenów z pustym sekretem.
- **Zewnętrzne usługi:** poza endpointem LLM aplikacja nie łączy się z żadnym zewnętrznym API.
- **Frontend** trzyma token w `sessionStorage`.

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
- **Frontend z podglądem na żywo** (`GET /`): logowanie, upload, render formularza z JSON-a, działające stany JSONata (vendored `web/vendor/jsonata.min.js`), podgląd `trace` i pobranie JSON-a.

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
- **`defaultValue`:** to string albo tablica. Reguły techniczne podają `[]` dla pól wyboru, a schemat dopuszcza tylko string, więc kopia schematu dopuszcza oba warianty.

## Wyniki dla jury

Katalog `wyniki/` zawiera JSON-y formularzy do oceny: `2.json`, `3.json`, `4.json`, `6.json`, `7.json`, `8.json`, `9.json`. Wszystkie przechodzą `app.rules_check`.

Odtworzenie wyników (potrzebny katalog `data/` z materiałami COI i zmienne `LLM_*` w środowisku):

```bash
set -a; source .env; set +a
python -m scripts.generate_wyniki          # wszystkie
python -m scripts.generate_wyniki 6 8      # wybrane
```

Skrypt bierze z każdego folderu `data/<nr>` plik w kolejności docx → pdf → xlsx → … i wypisuje źródło szkicu (`llm` albo `heuristic`) oraz liczbę błędów. Przy darmowym limicie API (2 zapytania na minutę) cała generacja trwa kilka minut.

## Testy

```bash
pytest
```

Testy (63) nie wymagają klucza LLM. Wywołania modelu są w nich zastępowane atrapami.

## Licencje

Wszystkie zależności to open source o licencjach permisywnych albo z weak copyleft na poziomie pliku. **Nie ma GPL ani AGPL.** Nie używamy PyMuPDF (AGPL). Licencje pakietów Pythona odczytano z metadanych w `.venv` (`importlib.metadata`).

| Zależność | Wersja | Licencja |
|---|---|---|
| fastapi (`[standard]`: uvicorn, starlette, httpx, jinja2…) | 0.121.3 | MIT (uvicorn, starlette, httpx: BSD-3-Clause) |
| python-multipart | 0.0.20 | Apache-2.0 |
| pytest | 9.0.1 | MIT |
| jsonschema (+ jsonschema-specifications, referencing, rpds-py, attrs) | 4.26.0 | MIT |
| pyjwt | 2.15.1 | MIT |
| filetype | 1.2.0 | MIT |
| openai | 3.57.0 | Apache-2.0 |
| pypdfium2 (PDFium w środku) | 5.15.2 | Apache-2.0 / BSD-3-Clause |
| python-docx | 1.2.0 | MIT |
| openpyxl (+ et_xmlfile) | 3.1.5 | MIT |
| pytesseract | 0.3.13 | Apache-2.0 |
| pillow | 13.0.0 | MIT-CMU (rodzina HPND, permisywna) |
| pyyaml | 6.0.4 | MIT |
| pydantic / pydantic-core | 2.14.4 / 2.50.5 | MIT |
| lxml (pośrednio, python-docx) | 6.1.3 | BSD-3-Clause |
| certifi (pośrednio, httpx) | 2026.11.20 | MPL-2.0 (niemodyfikowany pakiet danych) |
| JSONata (`web/vendor/jsonata.min.js`) | 2.2.2 | MIT |
| Tesseract OCR + `tesseract-ocr-pol` | Debian bookworm | Apache-2.0 |
| LibreOffice (headless) | Debian bookworm | MPL-2.0 |
| Ollama (opcjonalnie, profil `local-llm`) | 0.40.17 | MIT |
| Ministral 3 (14B / 8B), wagi modelu | — | Apache-2.0 |

Pozostałe pakiety pośrednie, czyli to, co ciągnie za sobą `fastapi[standard]` (np. anyio, click, rich, typer, websockets, uvloop, idna, urllib3, sentry-sdk), mają licencje MIT, BSD, ISC, Apache-2.0, PSF-2.0, 0BSD albo Unlicense.

**MPL-2.0 (LibreOffice, certifi)** to weak copyleft działający na poziomie pliku. Obowiązek udostępnienia zmian dotyczy tylko zmodyfikowanych plików objętych MPL. LibreOffice uruchamiamy jako osobny, niezmodyfikowany proces (`soffice --headless --convert-to`) i nie linkujemy go z naszym kodem. certifi to niezmieniony pakiet. Żaden z nich nie obejmuje licencją naszego kodu.

Obraz bazowy Debian zawiera standardowe narzędzia systemu (część na GPL), które nie są linkowane z aplikacją. To typowa sytuacja dla każdego obrazu opartego na Debianie.

## Struktura repozytorium

```
app/
  main.py            FastAPI: endpointy, limit body, frontend
  config.py          zmienne środowiskowe
  validation.py      nazwa, rozszerzenie, MIME, rozmiar
  security.py        JWT
  ingest.py          ekstrakcja tekstu / OCR / LibreOffice
  pipeline.py        LLM → fallback → builder → walidator
  rules_check.py     walidator reguł COI (także CLI)
  form_builder/      draft.py (kontrakt szkicu), llm_draft.py, fallback.py, builder.py, enrich.py
config/              form_schema.json, field_rules.yaml, fewshot/ (przykład few-shot)
web/                 frontend (index.html + vendored JSONata)
scripts/             generate_wyniki.py
tests/               pytest
wyniki/              JSON-y dla jury
data/                materiały COI (formularze 1–9)
```

## Znane ograniczenia

- **Darmowe API Mistral:** limit 2 zapytania na minutę. Przy większym ruchu część żądań dostaje 429 i po 3 próbach (ok. 1 min) przechodzi na heurystykę. Produkcyjnie potrzebny jest płatny plan albo model lokalny.
- **Ekstrakcja tekstu** (`app/ingest.py`) to tymczasowy adapter. Długie dokumenty są ucinane do 30 000 znaków.
- **Szkic heurystyczny** ma wyraźnie gorszą jakość od LLM: tylko pola tekstowe, jedna strona, najwyżej 60 pól.
- **Podgląd we frontendzie** nie ładuje pełnych słowników (Kraje, TERYT), tylko wstawia wartość zastępczą do przełączania stanów. Sekcje powtarzalne pokazuje jako jeden wiersz.
- **Batch** (`convert-batch`) nie jest zaimplementowany.
- **Limit rozmiaru** dla uploadu chunked bez `Content-Length` działa dopiero po sparsowaniu żądania.
