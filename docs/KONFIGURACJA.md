# Konfiguracja — wszystkie zmienne

Zmienne środowiskowe (`.env`, wzór `.env.example`).

[← powrót do README](../README.md)

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
