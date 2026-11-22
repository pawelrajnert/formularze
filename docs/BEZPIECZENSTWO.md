# Bezpieczeństwo — szczegóły

Walidacja plików, pliki w pamięci, JWT oraz tabela zagrożeń z testami. Mapowanie na OWASP: [OWASP.md](OWASP.md).

[← powrót do README](../README.md)

## Bezpieczeństwo

- **Whitelista rozszerzeń:** `pdf, doc, docx, ods, xlsx, jpg, jpeg, jpe, png` (bez względu na wielkość liter).
- **Typ z treści:** sygnatura pliku przez `filetype`. DOCX, XLSX i ODS (i każdy plik ZIP) sprawdzamy przez spis plików ZIP (`word/document.xml`, `xl/workbook.xml`, `mimetype`). Archiwum nie jest rozpakowywane, co chroni przed zip-bombą. Typ niezgodny z rozszerzeniem daje 415. Wyjątek: dokument Word pod „drugą” końcówką (`.doc` z treścią DOCX — tak są zapisane `.DOC` formularzy 5 i 7 — albo odwrotnie) przyjmujemy i czytamy według **treści**.
- **Nazwa pliku:** najwyżej 250 znaków, bez `; : > < / \ | ' * % $`.
- **Limit rozmiaru:** `MAX_FILE_SIZE_MB`. Za duże ciało żądania jest odrzucane już po nagłówku `Content-Length`, a strumień jest dodatkowo czytany porcjami z limitem.
- **Pliki w pamięci:** upload nie trafia do pliku tymczasowego (`spool_max_size` w Starlette jest podniesiony) i nie zapisujemy go trwale. Są dwa wyjątki, oba usuwane po żądaniu:
  - DOC i ODS: plik trafia do katalogu `tempfile.TemporaryDirectory`, gdzie jest też profil LibreOffice. Katalog jest kasowany po konwersji, a timeout `soffice` wynosi 120 s (`SOFFICE_TIMEOUT`).
  - OCR: `pytesseract` przekazuje obraz Tesseractowi przez plik tymczasowy, który kasuje zaraz po odczycie.
- **JWT (PyJWT):** sekret, algorytm i czas ważności ustawiamy w env. Hasło porównujemy w stałym czasie (`hmac.compare_digest`). Gdy brakuje sekretu lub hasła, usługa zwraca 503 i nie wydaje tokenów z pustym sekretem.
- **Zewnętrzne usługi:** poza endpointem LLM aplikacja nie łączy się z żadnym zewnętrznym API.
- **Frontend** trzyma token w `sessionStorage`.

**Widoczne na demie (R-08):** po zalogowaniu frontend pokazuje zwijaną kartę „Bezpieczeństwo i ochrona danych” z `GET /api/v1/security`. Każde zabezpieczenie ma stan z prawdziwej konfiguracji (env), krótki opis i sposób włączenia. Wyłączone pozycje (domyślnie `COMPLIANCE_ENABLED` i `APPROVAL_REQUIRED`) mają etykietę „Wyłączone” z nazwą zmiennej, która je włącza. Odpowiedź zawiera tylko flagi i limity liczbowe, bez kluczy, haseł i adresów (`tests/test_safeguards.py`).

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
