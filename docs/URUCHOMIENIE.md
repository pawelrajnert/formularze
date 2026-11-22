# Uruchomienie — warianty

Docker (zalecane), Windows (`start.bat`), bez Dockera i budowa własnego obrazu.

[← powrót do README](../README.md)

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

## Testy

```bash
pytest
```

Testy (ok. 350 + 90 testów odczytu plików, które wymagają Tesseracta/LibreOffice — komplet przechodzi w Dockerze) nie wymagają klucza LLM. Wywołania modelu są w nich zastępowane atrapami.
