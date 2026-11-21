import httpx
import openai
import pytest
from pydantic import BaseModel

from hackcore import LLMClient, LLMError, load_document
from hackcore.llm import inline_refs, parse_json


def _client(responses):
    c = LLMClient("http://x/v1", "k", "m", rate_limit_wait=0)
    calls = []

    def fake(system, user, schema, name):
        calls.append(c._response_format(schema, name)["type"])
        r = responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    c._call = fake
    return c, calls


def _err(cls, status, msg="err"):
    resp = httpx.Response(status, request=httpx.Request("POST", "http://x/v1/chat/completions"))
    return cls(msg, response=resp, body=None)


class Item(BaseModel):
    name: str


class Box(BaseModel):
    items: list[Item]


def test_parse_json_variants():
    assert parse_json('{"a": 1}') == {"a": 1}
    assert parse_json('Oto:\n```json\n{"a": 2}\n```') == {"a": 2}
    assert parse_json('blah {"a": 3} blah') == {"a": 3}
    with pytest.raises(ValueError):
        parse_json("brak")


def test_inline_refs_removes_defs():
    s = inline_refs(Box.model_json_schema())
    assert "$defs" not in s and "$ref" not in str(s)
    assert s["properties"]["items"]["items"]["properties"]["name"]["type"] == "string"


def test_rate_limit_then_ok():
    c, _ = _client([_err(openai.RateLimitError, 429), '{"items": [{"name": "a"}]}'])
    assert c.complete_model("s", "u", Box).items[0].name == "a"


def test_rate_limit_exhausted_raises():
    c, _ = _client([_err(openai.RateLimitError, 429)] * 3)
    with pytest.raises(LLMError):
        c.complete_json("s", "u")


def test_bad_json_one_retry():
    c, _ = _client(["nie json", '{"items": []}'])
    assert c.complete_model("s", "u", Box).items == []
    c, _ = _client(["nie json", "dalej nie"])
    with pytest.raises(LLMError):
        c.complete_json("s", "u")


def test_schema_mismatch_retried():
    c, _ = _client(['{"items": "zle"}', '{"items": [{"name": "b"}]}'])
    assert c.complete_model("s", "u", Box).items[0].name == "b"


def test_json_schema_rejected_falls_back_to_json_object():
    c, calls = _client([_err(openai.BadRequestError, 400, "response_format not supported"), '{"items": []}'])
    c.complete_model("s", "u", Box)
    assert calls == ["json_schema", "json_object"]


def test_from_env(monkeypatch):
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    assert LLMClient.from_env() is None
    monkeypatch.setenv("LLM_BASE_URL", "http://ollama:11434/v1")
    monkeypatch.setenv("LLM_MODEL", "ministral-3:8b")
    assert LLMClient.from_env().model == "ministral-3:8b"


def test_contract_imports():
    from hackcore.document import source_format
    assert source_format("x.JPE") == "jpg" and source_format("a.DOC") == "doc"
    assert callable(load_document)


# --- X-11: okno limitu zapytań + ucięta odpowiedź --------------------------------------------------------------
def test_rate_window_waits_exactly_until_oldest_request_expires():
    from hackcore.llm import RateWindow
    w = RateWindow()
    w.record(100.0)
    w.record(110.0)
    assert w.wait_before(115.0) == 0.0          # limit jeszcze nieznany -> bez proaktywnego czekania
    w.learn({"x-ratelimit-limit-req-minute": "2"})
    assert w.wait_before(115.0) == pytest.approx(45.5)   # 100 + 60 + 0.5 - 115
    assert w.wait_before(161.0) == 0.0          # najstarsze wypadło z okna
    assert w.wait_after_429(120.0, fallback=31) == pytest.approx(50.5)  # 100 już wypadło -> 110 + 60.5 - 120


def test_rate_window_429_without_history_uses_fallback():
    from hackcore.llm import RateWindow
    assert RateWindow().wait_after_429(0.0, fallback=31) == 31


def test_rate_window_shared_per_endpoint_and_key():
    a, b = LLMClient("http://w/v1", "k1", "m1"), LLMClient("http://w/v1/", "k1", "m2")
    assert a.window is b.window                 # różne modele, ten sam klucz -> ten sam limit
    assert LLMClient("http://w/v1", "k2", "m1").window is not a.window


def test_truncated_output_not_retried():
    from hackcore.llm import TruncatedOutput
    c, calls = _client([TruncatedOutput("ucięte"), '{"items": []}'])
    with pytest.raises(LLMError, match="ucięta|ucięte"):
        c.complete_model("s", "u", Box)
    assert len(calls) == 1                      # bez ponowienia (temperature=0 dałoby to samo)
