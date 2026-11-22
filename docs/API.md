# REST API — szczegóły

Pełny opis endpointów, odpowiedzi i kodów błędów.

[← powrót do README](../README.md)

## REST API

| Metoda i ścieżka | Opis |
|---|---|
| `POST /api/v1/auth/token` | Body JSON `{"username", "password"}`. Zwraca `{"access_token", "token_type": "bearer"}` |
| `POST /api/v1/forms/convert` | `multipart/form-data`, pole `file`, nagłówek `Authorization: Bearer <token>`, query `debug=false` |
| `POST /api/v1/forms/approve` | Przy `APPROVAL_REQUIRED=true`. Body: `form`, `token` (z bloku `approval` odpowiedzi `/convert`), `checks`, `statement`, `pages_visited`, `review_seconds`. Zwraca `{"record"}` i zapisuje go w `AUDIT_DIR` |
| `GET /api/v1/security` | Nagłówek `Authorization: Bearer <token>`. Lista zabezpieczeń i ochrony danych ze stanem z bieżącej konfiguracji: `[{id, nazwa, stan: "włączone"\|"wyłączone", opis, jak_wlaczyc}]`. Bez sekretów i adresów endpointów |
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
