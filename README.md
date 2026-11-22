# COI — cyfryzacja formularzy

Usługa REST, która z pojedynczego pliku papierowego formularza urzędowego (PDF, DOC, DOCX, ODS, XLSX, JPG, JPEG, PNG) tworzy JSON formularza elektronicznego zgodny ze schematem `importowanyPlikJsonSchemat.json` i z „Regułami technicznymi konfiguracji formularzy” COI. Model językowy opisuje tylko treść formularza (strony, sekcje, pola). Całą resztę (UUID, siatkę, przejścia, stronę końcową, warunki JSONata, słowniki, dane inicjalne) dokłada deterministyczny builder. Na końcu wynik sprawdza walidator reguł. Dołączony frontend pozwala wgrać plik i od razu zobaczyć podgląd formularza.

## Jak to działa

```
plik ──► walidacja (nazwa, rozszerzenie, MIME z treści, rozmiar)          app/validation.py
     ──► ekstrakcja tekstu                                                hackcore/ingest/
           PDF: warstwa tekstowa (pypdfium2), skan → OCR (Tesseract, pol)
           DOCX/XLSX: python-docx / openpyxl · DOC/ODS: LibreOffice → DOCX/XLSX
           JPG/PNG: OCR (kawałki długiego skanu równolegle)
     ──► szkic LLM: few-shot (formularze 1 i 5) + structured output (JSON Schema Draft)   app/form_builder/draft_llm.py
           │  klient: okno limitu, model zapasowy, pula kluczy, cache       hackcore/llm.py
           │  brak konfiguracji LLM / timeout / zły JSON / szkic odrzucony przez walidator
           └─► szkic heurystyczny (etykiety z „…”, „:”, nagłówków)       app/form_builder/draft_heuristic.py
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

Na Windowsie (Docker Desktop): **`start.bat`** — tworzy `.env` z wzoru (i otwiera go do uzupełnienia), buduje i uruchamia kontener, czeka na `/health` i otwiera przeglądarkę. `start.bat stop` zatrzymuje.

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
| `LLM_API_KEY` | Klucz API (`ollama` dla lokalnej Ollamy). Kilka kluczy po przecinku (`klucz1,klucz2`) = pula, każdy klucz ma własny limit zapytań | puste |
| `LLM_FALLBACK_MODELS` | Modele zapasowe na tym samym endpoincie (po przecinku), używane od razu, gdy główny model ma pełny limit zapytań (Mistral free: 2/min **na model**) | puste (w `.env.example`: `ministral-8b-latest`) |
| `LLM_FALLBACK_MAX_WAIT` | Ile sekund najwyżej czekać na wolny główny model, zanim szkic zrobi zapasowy (duże formularze wychodzą lepiej z 14B) | `20` |
| `DRAFT_CACHE_SIZE` | Pamięć podręczna szkiców w procesie: ten sam dokument + model + prompt → wynik bez LLM. `0` wyłącza | `32` |
| `OCR_WORKERS` | Ile kawałków skanu OCR-ować równolegle | `min(4, liczba CPU)` |
| `LLM_MODEL` | Nazwa modelu (`ministral-14b-latest` w API, `ministral-3:14b` w Ollamie) | puste |
| `OCR_LANG` | Język Tesseracta | `pol` |
| `MAX_FILE_SIZE_MB` | Maksymalny rozmiar pliku w MB | `20` |
| `AUTH_ENABLED` | `true` oznacza, że `/forms/convert` wymaga JWT. `false` wyłącza autoryzację (demo lokalne) | `true` |
| `AUTH_USER` | Login do `/auth/token` | `admin` |
| `AUTH_PASSWORD` | Hasło do `/auth/token`. Gdy jest puste, endpointy z autoryzacją zwracają 503 | puste |
| `JWT_SECRET` | Sekret do podpisu JWT. Gdy jest pusty, zwracają 503 | puste |
| `JWT_ALGORITHM` | Algorytm JWT (PyJWT) | `HS256` |
| `JWT_EXPIRE_MINUTES` | Czas ważności tokenu w minutach | `60` |
| `APPROVAL_REQUIRED` | `true` włącza bramkę zatwierdzenia urzędnika (F-18): wynik ma status DRAFT, a eksport jest zablokowany do zatwierdzenia | `false` |
| `RATE_LIMIT_PER_MINUTE` | Limit zapytań na IP w oknie 60 s, osobno dla `/auth/token` i `/forms/convert`. `0` wyłącza limit | `30` |
| `LLM_MODEL_ID` | Model z rejestru `config/models.yaml` (pierwszeństwo przed `LLM_*`). Per żądanie: `?model=<id>`, lista: `GET /api/v1/models` | puste |
| `COMPLIANCE_ENABLED` | `true` włącza maskowanie danych osobowych przed LLM i blok `ai_disclosure` (AI Act art. 50) obok JSON-a | `false` |
| `AUDIT_DIR` | Katalog na rekordy zatwierdzeń `<sha256 JSON-a>.approval.json` (w compose wolumen `audit`) | `audit` |

LLM jest używany tylko wtedy, gdy ustawione są wszystkie trzy zmienne `LLM_*`.

## REST API

| Metoda i ścieżka | Opis |
|---|---|
| `POST /api/v1/auth/token` | Body JSON `{"username", "password"}`. Zwraca `{"access_token", "token_type": "bearer"}` |
| `POST /api/v1/forms/convert` | `multipart/form-data`, pole `file`, nagłówek `Authorization: Bearer <token>`, query `debug=false` |
| `POST /api/v1/forms/approve` | Przy `APPROVAL_REQUIRED=true`. Body: `form`, `token` (z bloku `approval` odpowiedzi `/convert`), `checks`, `statement`, `pages_visited`, `review_seconds`. Zwraca `{"record"}` i zapisuje go w `AUDIT_DIR` |
| `GET /api/v1/security` | Nagłówek `Authorization: Bearer <token>`. Lista zabezpieczeń i ochrony danych ze stanem z bieżącej konfiguracji: `[{id, nazwa, stan: "włączone"\|"wyłączone", opis, jak_wlaczyc, dowod}]`. Bez sekretów i adresów endpointów |
| `GET /health` | `{"status": "ok"}` (healthcheck w compose) |
| `GET /` | frontend (`web/index.html`) |
| `GET /docs` | OpenAPI / Swagger UI (FastAPI) |

Odpowiedź `200` z `/forms/convert`:

```json
{ "filename": "wniosek.pdf", "form": { "title": "…", "tabs": [ … ], "flow": { "links": [ … ] } } }
```

Przy `debug=true` odpowiedź dodatkowo zawiera:

- `draft`: szkic, z którego zbudowano formularz (LLM albo heurystyka),
- `trace`: `{"source": "llm" | "heuristic", "reason": "<dlaczego fallback>", "model": "<model>", "seconds": …, "text_chars": <długość tekstu>, "timings": {"odczyt_s", "szkic_s", "czekanie_na_limit_s", "budowa_walidacja_s", "razem_s"}, "rules_errors": [<błędy walidatora szkicu LLM>], "warnings": […], "changes": {…}, "proposedDictionaries": […], "plain_language": {"summary": …, "suggestions": […]}}`. `warnings` mówi m.in., że szkic zrobił model zapasowy albo że wynik pochodzi z pamięci podręcznej.

Kody błędów:

| Kod | Kiedy |
|---|---|
| `400` | Zła nazwa pliku: pusta, dłuższa niż 250 znaków albo zawiera `; : > < / \ \| ' * % $` |
| `401` | Brak tokenu, zły lub wygasły token. Przy `/auth/token`: zły login lub hasło |
| `411` | Upload chunked (`Transfer-Encoding`) bez `Content-Length` |
| `413` | Plik większy niż `MAX_FILE_SIZE_MB`. Sprawdzane po `Content-Length` i ponownie przy czytaniu strumienia. Także DOCX/XLSX/ODS, które po rozpakowaniu miałyby ponad 200 MB |
| `415` | Rozszerzenie spoza whitelisty, typ wykryty z treści nie zgadza się z rozszerzeniem albo plik zawiera makra (`vbaProject.bin`, `Basic/`, `Scripts/`) |
| `422` | Brak pola `file` (walidacja FastAPI), nie udało się odczytać pliku (uszkodzony, brak OCR lub LibreOffice) albo formularz nie przeszedł walidacji reguł |
| `429` | Przekroczony `RATE_LIMIT_PER_MINUTE` (nagłówek `Retry-After: 60`) |
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

Domyślnie korzystamy z API Mistral i modelu `ministral-14b-latest`, czyli **Ministral 3 14B** z otwartymi wagami na licencji Apache-2.0. Regulamin: *„Rozwiązanie może korzystać z modeli językowych postawionych »w chmurze« i komunikować się z nimi przez API pod warunkiem, że model będzie dostępny w wersji otwartej i możliwy do postawienia na własnej infrastrukturze.”* Ministral 3 14B spełnia oba warunki: wagi są na Hugging Face (Apache-2.0), a ten sam model działa w Ollamie (niżej). Klient to biblioteka `openai`, więc działa z każdym endpointem zgodnym z OpenAI API. Jedno żądanie to zwykle jedno wywołanie modelu z `temperature=0` i `response_format=json_schema`.

**Limit darmowego API i jak go omijamy** (Mistral Experiment: zmierzone **2 zapytania/min na model i na klucz**, nagłówki `x-ratelimit-*`):

- okno 60 s po stronie klienta: limit czytamy z nagłówków i wysyłamy zapytanie dokładnie wtedy, gdy wolno (bez nieudanych prób i podwójnego czekania),
- **model zapasowy** (`LLM_FALLBACK_MODELS=ministral-8b-latest`): gdy 14B ma pełny limit i zwolni się później niż za `LLM_FALLBACK_MAX_WAIT` (20 s), szkic od razu robi 8B (ma własny limit); krótsze czekanie na 14B wygrywa (jakość) — w `trace.warnings` jest o tym wpis,
- **pula kluczy** (`LLM_API_KEY=klucz1,klucz2`),
- **pamięć podręczna**: ten sam plik drugi raz → wynik w < 1 s,
- odpowiedź ucięta (`finish_reason=length`) → od razu szkic heurystyczny, bez ponawiania (przy `temperature=0` dałoby to samo).

Pomiar (5 różnych formularzy pod rząd, darmowy klucz): **0 s czekania na limit**, 2 z 5 zrobił model zapasowy, powtórka pliku 0,2 s. Wcześniej ta seria to ok. 2 minuty samego czekania.

**Benchmark modeli** (`python -m scripts.bench_models --models … --forms 1,5,2,3,4,6,7,8,9`, wyniki w `benchmark/results.jsonl`; 9 formularzy COI, Mistral API):

| Model | Poprawny wynik z LLM | Czas modelu (mediana / max) | Tokeny/s | Zależności `show_if` (suma) | Zgodność etykiet* |
|---|---|---|---|---|---|
| **Ministral 3 14B** (domyślny) | 9/9 | 7,4 s / 48 s | ~115 | 81 | 0,74 |
| Ministral 3 8B (zapasowy) | 9/9 | 8,2 s / 34 s | ~135 | 39 | 0,56 |
| Ministral 3 3B | 8/9 | 5,7 s / 34 s | ~240 | 24 | 0,28 |
| Qwen3 4B lokalnie (Ollama, CPU, 12 rdzeni / 8 GB) | 1/1 (form. 1) | **1221 s** | ~2 | — | — |

\* etykiety pól części merytorycznej vs wzorce COI (form. 1, 5) i wyniki 14B (pozostałe). Wniosek: o czasie decyduje długość generowanej odpowiedzi i limit API, a nie rozmiar modelu; mniejszy model przyspiesza o 20–50%, ale gubi połowę zależności, więc domyślny zostaje 14B. Polskie modele (PLLuM-12B, Bielik-11B) są w rejestrze `config/models.yaml` — przełączenie to `LLM_MODEL_ID`, a `scripts/bench_models.py` pozwala urzędowi porównać je na własnych formularzach.

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

Czas: przez API Ministral 14B potrzebuje 3–20 s na typowy formularz (formularz 8 z 84 polami: ok. 50 s, skan JPG formularza 9 z OCR: ok. 55 s). **Na CPU bez GPU wersja lokalna jest niepraktyczna**: zmierzyliśmy 20 min na najprostszy formularz już dla modelu 4B (Docker, 12 rdzeni, 8 GB). Wdrożenie lokalne w urzędzie = serwer z GPU (np. 1× karta 24 GB dla Ministral 3 14B w Q4) z Ollamą albo vLLM — wtedy czas jest zbliżony do API, bez limitów zapytań, a dane nie opuszczają urzędu.

**Bez LLM:** gdy brakuje konfiguracji, LLM jest niedostępny albo jego szkic nie przechodzi walidatora, formularz powstaje ze szkicu heurystycznego. Ten wynik też przechodzi przez builder i walidator, więc zwykle dostajemy poprawny JSON. 422 pojawia się tylko wtedy, gdy nie da się odczytać tekstu albo nawet szkic heurystyczny nie przejdzie walidacji.

## Zatwierdzenie urzędnika (playbook, F-18)

Zasada: AI proponuje, a człowiek zatwierdza. Przy `APPROVAL_REQUIRED=true` formularz z `/convert` ma status DRAFT i nie da się go pobrać, dopóki urzędnik go nie zatwierdzi. Bramka siedzi w procesie, więc nie zależy od dobrej woli urzędnika.

1. **Pochodzenie:** `/convert` zwraca podpisany token z SHA-256 pliku źródłowego i wygenerowanego JSON-a oraz nazwą modelu.
2. **Obejrzenie całości:** przycisk „Zatwierdź” odblokowuje się dopiero, gdy urzędnik otworzy w podglądzie każdą stronę formularza. To przeciwdziała klikaniu bez czytania.
3. **Elementy wrażliwe potwierdzane osobno**, bez „zaznacz wszystko”: zgodność z oryginałem, pola tylko do odczytu i dane z profilu zaufanego, pola wymagane, zgody i RODO, opłaty i numery kont. Do tego oświadczenie „Sprawdziłem zgodność formularza z oryginałem i przepisami”.
4. **Kontrola serwera:** `/approve` odrzuca JSON zmieniony poza systemem (409), formularz, który nie przechodzi `rules_check` (422), niepełną listę kontrolną i nieobejrzane strony (400).
5. **Rekord audytu obok JSON-a**, a nie w nim, więc JSON zostaje czysty: login z JWT, data, SHA-256 źródła i wyniku, model, hash promptu i szablonów, wynik lintera, czas przeglądu. Rekord nie zawiera danych osobowych z dokumentu. Zapisuje się w `AUDIT_DIR`, a „Pobierz JSON” zapisuje go jako `<nazwa>.approval.json` obok formularza.

Podstawa: AI Act art. 14 (nadzór człowieka) i art. 50 (przejrzystość). Dalsze kroki (diff ręcznych poprawek, zasada czterech oczu, akceptacja każdej zmiany z listy „co zmieniliśmy”) są opisane w SPEC jako rozwój.

## AI Act i RODO

**Klasyfikacja ryzyka:** system przygotowuje konfigurację formularza dla urzędnika. Nie ocenia obywatela i nie decyduje o świadczeniach, więc nie jest systemem wysokiego ryzyka w rozumieniu rozporządzenia (UE) 2024/1689. Załącznik III pkt 5a obejmuje ocenę uprawnień do świadczeń i usług publicznych, a tego nie robimy.

| Wymóg | Jak go spełniamy | Gdzie |
|---|---|---|
| Art. 14: nadzór człowieka | AI proponuje, urzędnik zatwierdza. Przy `APPROVAL_REQUIRED=true` eksport jest zablokowany do zatwierdzenia, a urzędnik musi obejrzeć każdą stronę i osobno potwierdzić elementy wrażliwe | [Zatwierdzenie urzędnika](#zatwierdzenie-urzędnika-playbook-f-18) |
| Art. 50: przejrzystość treści AI | Przy `COMPLIANCE_ENABLED=true` odpowiedź ma blok `ai_disclosure` (czy użyto AI, model, hash promptu, które części są deterministyczne, `human_verified`). Rekord zatwierdzenia zapisuje model i wersje promptu oraz szablonów. Wszystko leży **obok** JSON-a, więc JSON formularza zostaje czysty i zgodny ze schematem | `/convert`, `AUDIT_DIR` |
| Art. 4: kompetencje w zakresie AI | Lista kontrolna w UI mówi urzędnikowi, co sprawdzić: zgodność z oryginałem, pola tylko do odczytu i dane z profilu zaufanego, pola wymagane, zgody i RODO, opłaty i konta | panel „Zatwierdzenie urzędnika” |
| Wyjaśnialność wyniku | Karta „Co zmieniliśmy względem papieru” (`trace.changes`): co usunęliśmy z papieru i dlaczego, co doszło ze standardu COI (z podstawą prawną), co poprawiliśmy i co urzędnik musi sprawdzić | UI, `/convert?debug=true` |
| Ograniczenie roli AI | LLM opisuje tylko część merytoryczną. Strony „Dane” i „Kontakt i zgody”, identyfikatory, siatkę i stronę końcową robi deterministyczny builder z szablonów, a każdy wynik przechodzi walidator `rules_check` | `app/form_builder/` |
| RODO: minimalizacja danych | Przy `COMPLIANCE_ENABLED=true` PESEL, NIP, REGON, IBAN, e-mail, telefon i nr dowodu z wypełnionego dokumentu są maskowane, zanim tekst trafi do LLM. Logi klienta LLM nie zawierają treści dokumentu. Wariant lokalny (profil `local-llm`, Ollama) sprawia, że dane w ogóle nie opuszczają urzędu | `hackcore/privacy.py`, [LLM: API albo model lokalny](#llm-api-albo-model-lokalny) |
| Otwarte modele | Rejestr `config/models.yaml` dopuszcza tylko modele z otwartymi wagami i licencją z allowlisty (Apache-2.0). Licencje sprawdzone na kartach modeli | `config/models.yaml` |

Obie flagi są domyślnie wyłączone (`false`), żeby jury mogło od razu pobrać JSON. W pracy urzędu włączamy obie.

## Bezpieczeństwo

- **Whitelista rozszerzeń:** `pdf, doc, docx, ods, xlsx, jpg, jpeg, jpe, png` (bez względu na wielkość liter).
- **Typ z treści:** sygnatura pliku przez `filetype`. DOCX, XLSX i ODS (i każdy plik ZIP) sprawdzamy przez spis plików ZIP (`word/document.xml`, `xl/workbook.xml`, `mimetype`). Archiwum nie jest rozpakowywane, co chroni przed zip-bombą. Typ niezgodny z rozszerzeniem daje 415. Wyjątek: dokument Word pod „drugą” końcówką (`.doc` z treścią DOCX — tak są zapisane `.DOC` formularzy 5 i 7 — albo odwrotnie) przyjmujemy i czytamy według **treści**.
- **Nazwa pliku:** najwyżej 250 znaków, bez `; : > < / \ | ' * % $`.
- **Limit rozmiaru:** `MAX_FILE_SIZE_MB`. Za duże ciało żądania jest odrzucane już po nagłówku `Content-Length`, a strumień jest dodatkowo czytany porcjami z limitem.
- **Pliki w pamięci:** upload nie trafia do pliku tymczasowego (`spool_max_size` w Starlette jest podniesiony) i nie zapisujemy go trwale. Są dwa wyjątki, oba usuwane po żądaniu:
  - DOC i ODS: plik trafia do katalogu `tempfile.TemporaryDirectory`, gdzie jest też profil LibreOffice. Katalog jest kasowany po konwersji, a timeout `soffice` wynosi 60 s.
  - OCR: `pytesseract` przekazuje obraz Tesseractowi przez plik tymczasowy, który kasuje zaraz po odczycie.
- **JWT (PyJWT):** sekret, algorytm i czas ważności ustawiamy w env. Hasło porównujemy w stałym czasie (`hmac.compare_digest`). Gdy brakuje sekretu lub hasła, usługa zwraca 503 i nie wydaje tokenów z pustym sekretem.
- **Zewnętrzne usługi:** poza endpointem LLM aplikacja nie łączy się z żadnym zewnętrznym API.
- **Frontend** trzyma token w `sessionStorage`.

**Widoczne na demie (R-08):** po zalogowaniu frontend pokazuje zwijaną kartę „Bezpieczeństwo i ochrona danych” z `GET /api/v1/security`. Każde zabezpieczenie ma stan z prawdziwej konfiguracji (env), krótki opis i wskazanie testu lub pliku. Wyłączone pozycje (domyślnie `COMPLIANCE_ENABLED` i `APPROVAL_REQUIRED`) są oznaczone na żółto z nazwą zmiennej, która je włącza. Odpowiedź zawiera tylko flagi i limity liczbowe, bez kluczy, haseł i adresów (`tests/test_safeguards.py`).

### Zagrożenia i zabezpieczenia (S-01)

Zasada: sprawdzamy, co przychodzi (plik, tekst dokumentu) i co wychodzi (JSON formularza). Wg [OWASP Top 10 LLM 2025](https://invicti.com/blog/web-security/owasp-top-10-risks-llm-security-2025). Testy są w `tests/test_security.py`, chyba że wskazano inaczej.

| Zagrożenie | Zabezpieczenie | Test |
|---|---|---|
| Zip-bomba w DOCX/XLSX/ODS (python-docx i openpyxl rozpakowują całe XML-e do pamięci) | Przed parsowaniem sumujemy rozmiary ze spisu ZIP. Powyżej 200 MB zwracamy 413. `zipfile` i tak nie rozpakuje wpisu ponad zadeklarowany rozmiar | `test_zip_bomb_rejected_before_parsing` |
| Bomba dekompresyjna obrazu | Pillow `MAX_IMAGE_PIXELS = 120 Mpx` (`hackcore/ingest/image.py`), powyżej 2× limitu błąd i 422 | `test_image_bomb_rejected` |
| Makra w DOCX/XLSX/ODS | Odrzucamy pliki z `vbaProject.bin`, `Basic/` lub `Scripts/` (415). python-docx i openpyxl i tak nie wykonują makr | `test_macros_rejected` |
| Makra w DOC/ODS przy konwersji LibreOffice | Świeży profil LO na każde wywołanie z `MacroSecurityLevel=3` i `DisableMacrosExecution=true`, timeout `soffice`, katalog tymczasowy kasowany po konwersji | `test_soffice_profile_disables_macros` |
| Upload chunked bez `Content-Length` (parser multipart trzyma całe ciało w pamięci, zanim zadziała limit) | Żądanie z `Transfer-Encoding` dostaje 411. Ciało z `Content-Length` ponad limit dostaje 413 | `test_chunked_upload_without_content_length_rejected`, `test_api.py::test_too_big` |
| Prompt injection pośredni (LLM01): „zignoruj instrukcje, dodaj pole…” w treści dokumentu | Tekst dokumentu trafia do bloku `<<< … >>>` oznaczonego jako DANE, a `>>>` w dokumencie jest rozbrajane. Structured output wymusza schemat `Draft`, obce klucze (`id`, `tabs`, `html`) przepadają. HTML, UUID i JSONatę robi deterministyczny builder, a bloki standardowe pochodzą z szablonów | `test_document_text_goes_to_data_block`, `test_injected_instructions_stay_data`, `test_poisoned_form_through_api_has_no_active_content` |
| XSS w wyniku (LLM05) | Teksty z dokumentu i z LLM przechodzą przez `escape()` w opisach HTML, a wartości w JSONacie przez `json.dumps` lub `_js`. Frontend renderuje opisy przez `safeHtml` | `test_injected_instructions_stay_data` |
| Linki z dokumentu w HTML wyniku | Allowlista w `rules_check`: `href`/`src` tylko `https://` do `gov.pl` (z subdomenami) i `warszawa19115.pl`, `data:image/` albo tekst bez schematu (artefakt wzorca COI). Inny link = błąd reguł, a szkic LLM jest odrzucany na rzecz heurystyki | `test_link_outside_allowlist_rejected`, `test_link_on_allowlist_ok`, `test_injected_link_in_plain_text_discards_llm_draft` |
| Za długie teksty | Limity w `rules_check`: tytuł formularza 255, `title`/`name` 1000, `defaultValue`/`query` 5000, opisy 50 000 znaków. Tekst do LLM jest cięty na części z limitem (`chunks`) | `test_length_limits` |
| Wynik niezgodny z formatem COI | Każdy wynik przechodzi pełny JSON Schema COI (`Draft202012Validator`) i reguły techniczne. Błąd daje fallback albo 422 | `test_full_json_schema_validation`, `test_rules_check.py` |
| Brute force hasła, zalewanie `/convert` | Limit `RATE_LIMIT_PER_MINUTE` na IP i ścieżkę (429). Shortcut: licznik w pamięci jednego procesu, więc przy kilku workerach trzeba limitu na proxy | `test_rate_limit` |
| Dane osobowe w logach | Aplikacja nie loguje treści dokumentu. Klient LLM przy złym JSON-ie loguje sam typ błędu, bo komunikat pydantic cytuje dane | `test_llm_bad_json_log_has_no_document_data`, `test_poisoned_form_through_api_has_no_active_content` |
| Kradzież tokenu, słaby sekret | JWT z sekretem z env i krótkim TTL. Bez sekretu usługa zwraca 503 | `test_api.py` |

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

Testy (ok. 350 + 90 testów odczytu plików, które wymagają Tesseracta/LibreOffice — komplet przechodzi w Dockerze) nie wymagają klucza LLM. Wywołania modelu są w nich zastępowane atrapami.

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
  pipeline.py        ingest → szkic (LLM / heurystyka) → builder → walidator
  rules_check.py     walidator reguł COI (także CLI)
  form_builder/      draft.py (kontrakt szkicu), draft_llm.py, draft_heuristic.py, draft_postprocess.py,
                     builder.py, cleanup.py, templates.py, enrich.py, dictionary_proposals.py, plain_language.py
hackcore/            wspólny rdzeń: ingest/ (PDF, DOCX, XLSX, DOC/ODS, OCR), llm.py, models.py (rejestr), privacy.py
config/              form_schema.json, field_rules.yaml, models.yaml, plain_language.yaml, section_templates/, fewshot/
web/                 frontend (index.html + vendored JSONata)
scripts/             generate_wyniki.py, bench_models.py, propose_dictionaries.py
start.bat            uruchomienie na Windowsie (Docker Desktop)
tests/               pytest
wyniki/              JSON-y dla jury
data/                materiały COI (formularze 1–9)
```

## Znane ograniczenia

- **Darmowe API Mistral:** limit 2 zapytania na minutę na model i klucz. Okno limitu, model zapasowy (8B), pula kluczy i cache sprawiają, że 5 konwersji pod rząd nie czeka (zmierzone), ale przy większym ruchu zapytania czekają albo trafiają do słabszego modelu zapasowego. Produkcyjnie: płatny plan albo model u siebie na GPU.
- **Długie dokumenty** idą do LLM w najwyżej 2 częściach po 18 000 znaków (reszta pominięta z ostrzeżeniem w `trace.warnings`).
- **Pola zmyślone przez AI ze słów obecnych w dokumencie** (np. „Nazwa banku” przy „rachunek w banku”) nie są wykrywane automatycznie — tylko pola ze słowami spoza dokumentu trafiają do „do sprawdzenia”.
- **Szkic heurystyczny** ma wyraźnie gorszą jakość od LLM: tylko pola tekstowe, jedna strona, najwyżej 60 pól.
- **Podgląd we frontendzie** nie ładuje pełnych słowników (Kraje, TERYT), tylko wstawia wartość zastępczą do przełączania stanów. Sekcje powtarzalne pokazuje jako jeden wiersz.
- **Batch** (`convert-batch`) nie jest zaimplementowany.
