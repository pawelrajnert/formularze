"""X-09: rejestr modeli LLM (model factory) — `config/models.yaml` -> LLMClient.

- tylko otwarte wagi + licencja z allowlisty (Discord COI): walidacja przy ładowaniu, zły wpis = wyjątek,
- klucze API wyłącznie z env (w YAML-u jest NAZWA zmiennej), Ollama ma stały klucz "ollama",
- wybór: jawne id (np. `?model=`) > env `LLM_MODEL_ID` > stare `LLM_BASE_URL/LLM_API_KEY/LLM_MODEL`.
"""
import os
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path

import httpx
import yaml

from hackcore.llm import LLMClient

LICENSE_ALLOWLIST = {"Apache-2.0", "MIT"}
OLLAMA_KEY = "ollama"
_FIELDS = {"id", "backend", "base_url", "base_url_env", "model", "api_key_env", "license", "license_source",
           "license_verified", "open_weights", "weights_url", "params_b", "quantization", "context", "notes"}
_PUBLIC = ("id", "backend", "model", "license", "license_source", "license_verified", "open_weights",
           "weights_url", "params_b", "quantization", "context", "notes")


class ModelRegistryError(ValueError):
    """Zły rejestr modeli (licencja, duplikat, brak pola) albo zła konfiguracja wybranego modelu."""


class UnknownModel(ModelRegistryError):
    """Id spoza rejestru -> w API 400."""


class MissingAPIKey(ModelRegistryError):
    """Model z rejestru wymaga klucza, a żadna z jego zmiennych env nie jest ustawiona."""


@dataclass(frozen=True)
class ModelSpec:
    id: str
    backend: str
    model: str
    license: str
    open_weights: bool
    base_url: str = ""
    base_url_env: str = ""
    api_key_env: tuple[str, ...] = ()
    license_source: str = ""
    license_verified: bool = False
    weights_url: str = ""
    params_b: float | None = None
    quantization: str | None = None
    context: int | None = None
    notes: str = ""

    def resolved_base_url(self, env: Mapping[str, str]) -> str:
        return (env.get(self.base_url_env, "") if self.base_url_env else "") or self.base_url

    def api_key(self, env: Mapping[str, str]) -> str | None:
        """Pierwsza niepusta zmienna z api_key_env; Ollama bez klucza -> "ollama"; brak -> None."""
        if key := next((env[n] for n in self.api_key_env if env.get(n)), None):
            return key
        return OLLAMA_KEY if self.backend == "ollama" else None


@dataclass
class Registry:
    models: dict[str, ModelSpec]
    default: str | None = None
    env: Mapping[str, str] = field(default_factory=lambda: os.environ, repr=False)

    def ids(self) -> list[str]:
        return list(self.models)

    def get(self, model_id: str) -> ModelSpec:
        try:
            return self.models[model_id]
        except KeyError:
            raise UnknownModel(f"Nieznany model '{model_id}'. Dostępne: {', '.join(self.models)}") from None

    def connection(self, model_id: str) -> tuple[str, str, str]:
        """(base_url, api_key, model) dla id; MissingAPIKey gdy brak klucza w env."""
        spec = self.get(model_id)
        key = spec.api_key(self.env)
        if key is None:
            raise MissingAPIKey(f"Model '{model_id}' wymaga klucza w env: {' / '.join(spec.api_key_env) or '?'}")
        if not (base := spec.resolved_base_url(self.env)):
            raise ModelRegistryError(f"Model '{model_id}': brak base_url (ani {spec.base_url_env} w env)")
        return base, key, spec.model

    def client(self, model_id: str, timeout: float | None = None) -> LLMClient:
        """Klient dla id z rejestru. Brak klucza -> MissingAPIKey (czytelny błąd, nie cichy brak LLM)."""
        base, key, model = self.connection(model_id)
        return LLMClient(base, key, model, timeout or float(self.env.get("LLM_TIMEOUT", "120")))

    def public(self, probe: "Callable[[str], bool] | None" = None) -> list[dict]:
        """Lista do `GET /api/v1/models`: bez kluczy, nazw zmiennych env i adresów endpointów.

        configured: model z kluczem -> jest klucz; Ollama (klucz niepotrzebny) -> serwer odpowiada (R-05),
        sprawdzane raz na adres w obrębie wywołania, timeout 1 s.
        """
        probe = probe or ollama_reachable
        alive: dict[str, bool] = {}
        out = []
        for spec in self.models.values():
            d = {k: v for k, v in asdict(spec).items() if k in _PUBLIC}
            d["default"] = spec.id == self.default
            if spec.backend == "ollama":
                url = spec.resolved_base_url(self.env)
                if url not in alive:
                    alive[url] = probe(url)
                d["configured"] = alive[url]
            else:
                d["configured"] = spec.api_key(self.env) is not None
            out.append(d)
        return out


def ollama_reachable(base_url: str, timeout: float = 1.0) -> bool:
    """Czy endpoint OpenAI-compatible Ollamy odpowiada (GET /models)."""
    try:
        return httpx.get(base_url.rstrip("/") + "/models", timeout=timeout).status_code < 500
    except httpx.HTTPError:
        return False


def _spec(raw: dict, i: int) -> ModelSpec:
    if not isinstance(raw, dict):
        raise ModelRegistryError(f"models[{i}]: wpis musi być słownikiem")
    where = f"model '{raw.get('id', f'#{i}')}'"
    if unknown := set(raw) - _FIELDS:
        raise ModelRegistryError(f"{where}: nieznane pola {sorted(unknown)}")
    if missing := [k for k in ("id", "backend", "model", "license", "open_weights") if raw.get(k) in (None, "")]:
        raise ModelRegistryError(f"{where}: brak pól {missing}")
    lic = next((a for a in LICENSE_ALLOWLIST if a.lower() == str(raw["license"]).strip().lower()), None)
    if lic is None:
        raise ModelRegistryError(f"{where}: licencja '{raw['license']}' spoza allowlisty {sorted(LICENSE_ALLOWLIST)}")
    if raw["open_weights"] is not True:
        raise ModelRegistryError(f"{where}: dozwolone tylko modele z otwartymi wagami (open_weights: true)")
    if not (raw.get("base_url") or raw.get("base_url_env")):
        raise ModelRegistryError(f"{where}: wymagane base_url albo base_url_env")
    keys = raw.get("api_key_env") or ()
    keys = (keys,) if isinstance(keys, str) else tuple(keys)
    if not keys and raw["backend"] != "ollama":
        raise ModelRegistryError(f"{where}: backend '{raw['backend']}' wymaga api_key_env (nazwa zmiennej env)")
    vals = {k: v for k, v in raw.items() if v is not None}
    return ModelSpec(**{**vals, "id": str(raw["id"]), "license": lic, "api_key_env": keys,
                        "license_verified": bool(raw.get("license_verified", False))})


def load_registry(path: str | Path, env: Mapping[str, str] | None = None) -> Registry:
    try:
        data = yaml.safe_load(Path(path).read_text("utf-8")) or {}
    except (OSError, yaml.YAMLError) as e:
        raise ModelRegistryError(f"Nie da się wczytać rejestru modeli {path}: {e}") from e
    models: dict[str, ModelSpec] = {}
    for i, raw in enumerate(data.get("models") or []):
        spec = _spec(raw, i)
        if spec.id in models:
            raise ModelRegistryError(f"Zdublowane id modelu '{spec.id}'")
        models[spec.id] = spec
    default = data.get("default")
    if default is not None and default not in models:
        raise ModelRegistryError(f"default '{default}' nie istnieje w rejestrze")
    return Registry(models, default, os.environ if env is None else env)


def selected_model_id(explicit: str | None = None, env: Mapping[str, str] | None = None) -> str | None:
    """Jawne id (np. `?model=`) > env LLM_MODEL_ID > None (czyli stare LLM_BASE_URL/LLM_API_KEY/LLM_MODEL)."""
    env = os.environ if env is None else env
    return (explicit or "").strip() or env.get("LLM_MODEL_ID", "").strip() or None


def select_client(registry: Registry, model_id: str | None = None) -> LLMClient | None:
    """Klient wg kolejności z selected_model_id; bez id -> stare LLM_* jak LLMClient.from_env() (może być None)."""
    env = registry.env
    if mid := selected_model_id(model_id, env):
        return registry.client(mid)
    base, model = env.get("LLM_BASE_URL", ""), env.get("LLM_MODEL", "")
    if not base or not model:
        return None
    return LLMClient(base, env.get("LLM_API_KEY", ""), model, float(env.get("LLM_TIMEOUT", "120")))
