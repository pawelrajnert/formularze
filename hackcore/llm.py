"""C-04: klient LLM dla dowolnego endpointu OpenAI-compatible (Mistral, Scaleway, Ollama).

- structured outputs: response_format=json_schema (N-X3); schemat z $ref rozwijany inline (małe modele kopiowały $ref),
- instrukcja JSON powtórzona w prompcie (małe modele), temperature=0,
- limit zapytań (X-11): okno 60 s per endpoint+klucz. Limit czytamy z nagłówka `x-ratelimit-limit-req-minute`
  (Mistral free = 2/min, bez Retry-After) i czekamy DOKŁADNIE tyle, ile trzeba, zanim wyślemy zapytanie
  (zamiast stałych 31 s po 429, które bywały za krótkie -> podwójne czekanie). Bez nagłówków: 31 s po 429,
- odpowiedź ucięta (finish_reason=length): ponowienie przy temperature=0 da to samo -> od razu LLMError,
- zły JSON: wycięcie {...} z odpowiedzi + walidacja pydantic, 1 retry,
- po wyczerpaniu prób: LLMError -> wołający robi fallback (COI: heurystyka, UZP: same regexy).
"""
import copy
import hashlib
import json
import logging
import os
import re
import threading
import time
from collections import deque
from collections.abc import Callable
from typing import Any, TypeVar

import openai
from pydantic import BaseModel, ValidationError

log = logging.getLogger(__name__)
M = TypeVar("M", bound=BaseModel)

RATE_LIMIT_WAIT_S = 31.0
MAX_ATTEMPTS = 3
JSON_HINT = "\n\nOdpowiedz WYŁĄCZNIE poprawnym obiektem JSON zgodnym ze schematem. Bez komentarzy i bez markdown."


class LLMError(RuntimeError):
    """LLM niedostępny / limit / nie dał poprawnego JSON-a po wszystkich próbach."""


class TruncatedOutput(ValueError):
    """Model doszedł do limitu długości odpowiedzi — JSON jest ucięty."""


WINDOW_S = 60.0
MAX_WAIT_S = 65.0


class RateWindow:
    """Przesuwne okno zapytań do jednego endpointu+klucza (wspólne dla wszystkich klientów w procesie).

    Limit poznajemy z nagłówków odpowiedzi; do tego czasu nie czekamy proaktywnie (zachowanie jak wcześniej).
    """

    def __init__(self) -> None:
        self.limit: int | None = None
        self.times: deque[float] = deque()
        self.lock = threading.Lock()

    def _trim(self, now: float) -> None:
        while self.times and now - self.times[0] >= WINDOW_S:
            self.times.popleft()

    def wait_before(self, now: float) -> float:
        """Ile czekać przed wysłaniem zapytania, żeby nie dostać 429 (0 = można od razu)."""
        with self.lock:
            self._trim(now)
            if self.limit and len(self.times) >= self.limit:
                return min(MAX_WAIT_S, self.times[0] + WINDOW_S + 0.5 - now)
            return 0.0

    def wait_after_429(self, now: float, fallback: float) -> float:
        """Po 429: do wygaśnięcia najstarszego zapytania z okna; gdy okno puste (zapytania z innego procesu) -> fallback."""
        with self.lock:
            self._trim(now)
            if self.times:
                return max(1.0, min(MAX_WAIT_S, self.times[0] + WINDOW_S + 0.5 - now))
            return fallback

    def record(self, now: float) -> None:
        with self.lock:
            self.times.append(now)

    def learn(self, headers: Any) -> None:
        try:
            if v := headers.get("x-ratelimit-limit-req-minute"):
                self.limit = int(v)
        except (AttributeError, TypeError, ValueError):
            pass


_WINDOWS: dict[str, RateWindow] = {}
_WINDOWS_LOCK = threading.Lock()


def rate_window(base_url: str, api_key: str) -> RateWindow:
    key = base_url.rstrip("/") + "|" + hashlib.sha256((api_key or "").encode()).hexdigest()[:16]
    with _WINDOWS_LOCK:
        return _WINDOWS.setdefault(key, RateWindow())


def inline_refs(schema: dict) -> dict:
    """Rozwija $ref/$defs (pydantic) do jednego płaskiego schematu."""
    defs = schema.get("$defs", {})

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                target = walk(copy.deepcopy(defs[node["$ref"].split("/")[-1]]))
                rest = {k: v for k, v in node.items() if k != "$ref"}
                return {**target, **walk(rest)}
            return {k: walk(v) for k, v in node.items() if k != "$defs"}
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    return walk(schema)


def parse_json(text: str) -> dict:
    """JSON z odpowiedzi modelu: wprost, z bloku ```json``` albo od pierwszej { do ostatniej }."""
    text = text.strip()
    candidates = [text]
    if m := re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL):
        candidates.append(m.group(1))
    if (a := text.find("{")) != -1 and (b := text.rfind("}")) > a:
        candidates.append(text[a:b + 1])
    for c in candidates:
        try:
            obj = json.loads(c)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    raise ValueError("Odpowiedź nie zawiera obiektu JSON")


class LLMClient:
    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 120,
                 max_attempts: int = MAX_ATTEMPTS, rate_limit_wait: float = RATE_LIMIT_WAIT_S):
        self.model = model
        self.max_attempts = max_attempts
        self.rate_limit_wait = rate_limit_wait
        # max_retries=0: retry/backoff robimy sami (SDK czeka za krótko na 429 Mistrala)
        self._client = openai.OpenAI(base_url=base_url, api_key=api_key or "none", timeout=timeout, max_retries=0)
        self._json_schema_ok = True  # gdy endpoint odrzuci json_schema -> json_object do końca życia klienta
        self.window = rate_window(base_url, api_key)
        self.waited_s = 0.0  # ile czasu ten klient spędził na czekaniu na limit (do trace / benchmarku)

    @classmethod
    def from_env(cls) -> "LLMClient | None":
        """LLM_BASE_URL/LLM_API_KEY/LLM_MODEL z env; None gdy brak konfiguracji (tryb bez LLM)."""
        base, model = os.environ.get("LLM_BASE_URL", ""), os.environ.get("LLM_MODEL", "")
        if not base or not model:
            return None
        return cls(base, os.environ.get("LLM_API_KEY", ""), model, float(os.environ.get("LLM_TIMEOUT", "120")))

    def _response_format(self, schema: dict | None, name: str) -> dict:
        if schema is not None and self._json_schema_ok:
            return {"type": "json_schema", "json_schema": {"name": name, "schema": inline_refs(schema)}}
        return {"type": "json_object"}

    def _sleep(self, seconds: float, why: str) -> None:
        if seconds <= 0:
            return
        log.warning("LLM: czekam %.1f s (%s)", seconds, why)
        self.waited_s += seconds
        time.sleep(seconds)

    def _call(self, system: str, user: str, schema: dict | None, name: str) -> str:
        self._sleep(self.window.wait_before(time.monotonic()), f"limit {self.window.limit} zapytań/min")
        self.window.record(time.monotonic())
        raw = self._client.chat.completions.with_raw_response.create(
            model=self.model,
            temperature=0,
            messages=[{"role": "system", "content": system + JSON_HINT}, {"role": "user", "content": user}],
            response_format=self._response_format(schema, name),
        )
        self.window.learn(raw.headers)
        resp = raw.parse()
        choice = resp.choices[0]
        if getattr(choice, "finish_reason", None) == "length":
            raise TruncatedOutput("Odpowiedź modelu ucięta (limit długości) — za długi dokument lub zapętlenie")
        return choice.message.content or ""

    def complete_json(self, system: str, user: str, schema: dict | None = None, name: str = "response") -> dict:
        return self._complete(system, user, schema, name, validate=None)

    def complete_model(self, system: str, user: str, model_cls: type[M],
                       coerce: Callable[[dict], dict] | None = None) -> M:
        """Structured output wprost do modelu pydantic (np. Draft z F-06).

        coerce: naprawa surowego dict przed walidacją (małe modele mylą enumy/typy) — jeden zły enum nie zabija wyniku.
        """
        fix = coerce or (lambda d: d)
        data = self._complete(system, user, model_cls.model_json_schema(), model_cls.__name__,
                              validate=lambda d: model_cls.model_validate(fix(d)))
        return model_cls.model_validate(fix(data))

    def _complete(self, system: str, user: str, schema: dict | None, name: str, validate) -> dict:
        bad_json_retries = 1
        last: Exception | None = None
        attempt = 0
        while attempt < self.max_attempts:
            attempt += 1
            try:
                data = parse_json(self._call(system, user, schema, name))
                if validate:
                    validate(data)
                return data
            except openai.RateLimitError as e:
                last = e
                self.window.learn(getattr(getattr(e, "response", None), "headers", None))
                if attempt < self.max_attempts:
                    wait = self.window.wait_after_429(time.monotonic(), self.rate_limit_wait)
                    self._sleep(wait, f"429, próba {attempt}/{self.max_attempts}")
            except TruncatedOutput as e:  # temperature=0 -> ponowienie da to samo; nie marnujemy limitu i czasu
                raise LLMError(str(e)) from e
            except openai.BadRequestError as e:
                # endpoint nie zna json_schema -> raz przełączamy na json_object i próbujemy ponownie (bez liczenia próby)
                if self._json_schema_ok and schema is not None and "response_format" in str(e).lower():
                    log.warning("Endpoint odrzucił json_schema, przełączam na json_object")
                    self._json_schema_ok = False
                    attempt -= 1
                    continue
                raise LLMError(f"LLM 400: {e}") from e
            except (openai.APITimeoutError, openai.APIConnectionError, openai.InternalServerError) as e:
                last = e
                log.warning("LLM niedostępny (%s), próba %d/%d", type(e).__name__, attempt, self.max_attempts)
            except openai.APIError as e:
                raise LLMError(f"LLM błąd API: {e}") from e
            except (ValueError, ValidationError) as e:  # zły JSON / niezgodny ze schematem
                last = e
                if bad_json_retries <= 0:
                    break
                bad_json_retries -= 1
                # S-01: sam typ błędu - komunikat pydantic cytuje input_value, czyli treść dokumentu
                log.warning("LLM zwrócił zły JSON (%s), ponawiam", type(e).__name__)
        raise LLMError(f"LLM nie odpowiedział poprawnie po {attempt} próbach: {last}") from last
