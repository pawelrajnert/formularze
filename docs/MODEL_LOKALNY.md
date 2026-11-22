# Model lokalny (Ollama, bez internetu)

Przełączenie na model uruchomiony u siebie, na CPU — dane nie opuszczają urzędu.

[← powrót do README](../README.md)

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

**Cała usługa działa na zwykłym CPU, bez GPU** (wymóg: maszyna na obronie nie ma GPU). Aplikacja, OCR (Tesseract), LibreOffice, builder i walidator liczą się na CPU, a model językowy z otwartymi wagami wołamy przez API (dozwolone regulaminem). Czas przez API: Ministral 14B potrzebuje 3–20 s na typowy formularz (formularz 8 z 84 polami: ok. 50 s, skan JPG formularza 9 z OCR: ok. 55 s); test na 69 plikach wszystkich formatów: mediana 28 s.

**Wersja w pełni lokalna (bez internetu) też działa na CPU** — profil `local-llm` (Ollama w kontenerze, bez GPU), ten sam kod i ten sam JSON. Jest wyraźnie wolniejsza: na laptopie (Docker, 12 rdzeni, 8 GB RAM) zmierzyliśmy ok. 20 min na najprostszy formularz dla modelu 4B, więc na CPU zalecamy mniejszy model z tej samej rodziny (`ministral-3:3b` / `ministral-3:8b`) i przetwarzanie w tle. Opcjonalnie, jeśli urząd ma serwer z kartą graficzną, ten sam model w Ollamie/vLLM odpowiada tak szybko jak API — GPU nie jest jednak wymagane.

**Bez LLM:** gdy brakuje konfiguracji, LLM jest niedostępny albo jego szkic nie przechodzi walidatora, formularz powstaje ze szkicu heurystycznego. Ten wynik też przechodzi przez builder i walidator, więc zwykle dostajemy poprawny JSON. 422 pojawia się tylko wtedy, gdy nie da się odczytać tekstu albo nawet szkic heurystyczny nie przejdzie walidacji.

