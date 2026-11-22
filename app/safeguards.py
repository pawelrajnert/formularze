"""R-08: lista zabezpieczeń i ochrony danych ze stanem z bieżącej konfiguracji (GET /api/v1/security).

Tylko flagi i limity liczbowe - nigdy sekrety (klucze, hasła, JWT_SECRET) ani adresy endpointów.
"""
from app import config
from hackcore.privacy import compliance_enabled

ON, OFF = "włączone", "wyłączone"


def _item(id_: str, nazwa: str, on: bool, opis: str, jak_wlaczyc: str | None) -> dict:
    return {"id": id_, "nazwa": nazwa, "stan": ON if on else OFF, "opis": opis, "jak_wlaczyc": None if on else jak_wlaczyc}


def safeguards() -> list[dict]:
    s = config.settings
    limit = s.rate_limit_per_minute
    return [
        _item("auth", "Logowanie i token JWT", s.auth_enabled,
              f"Endpointy wymagają tokenu JWT (sekret z env, ważność {s.jwt_expire_minutes} min). Hasło porównywane "
              "w stałym czasie. Bez sekretu lub hasła usługa zwraca 503 i nie wydaje tokenów.",
              "AUTH_ENABLED=true"),
        _item("rate_limit", "Limit zapytań", limit > 0,
              (f"Najwyżej {limit} żądań na minutę z jednego IP do logowania i konwersji (potem 429). "
               if limit > 0 else "Brak limitu żądań (ochrona przed brute force i zalewaniem /convert). ")
              + "Licznik w pamięci procesu - przy kilku workerach limit na proxy.",
              "RATE_LIMIT_PER_MINUTE=30"),
        _item("file_validation", "Walidacja pliku", True,
              f"Whitelista rozszerzeń, typ sprawdzany z treści (sygnatura, spis ZIP), bezpieczna nazwa (do 250 znaków), "
              f"limit {s.max_file_size_mb} MB (MAX_FILE_SIZE_MB), odrzucanie makr, ochrona przed bombą ZIP i bombą obrazu.",
              None),
        _item("memory_only", "Pliki tylko w pamięci", True,
              "Upload nie jest zapisywany na dysku. Wyjątki (DOC/ODS dla LibreOffice, OCR) trafiają do katalogu "
              "tymczasowego kasowanego po żądaniu.",
              None),
        _item("prompt_injection", "Ochrona przed prompt injection", True,
              "Tekst dokumentu trafia do promptu jako blok DANYCH, którego dokument nie może zamknąć. Structured output "
              "wymusza schemat szkicu, a identyfikatory, HTML i JSONatę tworzy deterministyczny builder.",
              None),
        _item("output_rules", "Allowlista linków i limity długości", True,
              "Walidator rules_check: linki tylko https do gov.pl i warszawa19115.pl, limity długości tekstów, pełny "
              "JSON Schema COI. Szkic LLM z obcym linkiem jest odrzucany na rzecz heurystyki.",
              None),
        _item("no_content_logs", "Logi bez treści dokumentu", True,
              "Aplikacja nie loguje treści dokumentu. Przy błędnym JSON-ie z LLM logowany jest tylko typ błędu.",
              None),
        _item("compliance", "Maskowanie danych osobowych przed LLM i oznaczenie treści AI (AI Act art. 50)",
              compliance_enabled(),
              "PESEL, NIP, REGON, IBAN, e-mail, telefon i nr dowodu są maskowane, zanim tekst trafi do LLM (RODO: "
              "minimalizacja). Odpowiedź dostaje blok ai_disclosure obok JSON-a formularza.",
              "COMPLIANCE_ENABLED=true"),
        _item("approval", "Zatwierdzenie urzędnika i rekord audytu (F-18, AI Act art. 14)", s.approval_required,
              "Eksport zablokowany do zatwierdzenia: urzędnik ogląda każdą stronę i potwierdza elementy wrażliwe. "
              "Rekord zatwierdzenia (model, wersje promptu i szablonów, bez danych osobowych) trafia do katalogu audytu.",
              "APPROVAL_REQUIRED=true"),
        _item("open_weights", "Model z otwartymi wagami, możliwy lokalnie", True,
              "Rejestr modeli dopuszcza tylko otwarte wagi z licencją z allowlisty (Apache-2.0). Profil local-llm "
              "(Ollama) uruchamia model w urzędzie - dane nie opuszczają serwera.",
              None),
        _item("docker_non_root", "Kontener bez uprawnień roota", True,
              "Obraz Docker uruchamia aplikację jako użytkownik appuser (uid 1000), nie jako root.",
              None),
    ]
