"""X-11: benchmark modeli LLM na pipeline COI — czas, tokeny, 429, jakość szkicu.

Użycie:
  python -m scripts.bench_models --models ministral-14b-api,ministral-8b-api --forms 1,2,4 [--out benchmark]
Ollama na hoście: OLLAMA_BASE_URL=http://localhost:11434/v1

Jakość:
  - formularze 1 i 5: etykiety pól części merytorycznej vs oficjalny wzorzec COI (UWAGA: 1 i 5 są też few-shotem
    w prompcie, więc wynik jest zawyżony — mierzy raczej, czy model umie trzymać się przykładu),
  - pozostałe: vs `wyniki/<nr>.json` (Ministral 14B, po przeglądzie) = referencja, nie złoty standard.
Czas: `wall` = całość, `net` = bez czekania na 429 (limit darmowego planu, nie wina modelu).
"""
import argparse
import difflib
import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from types import SimpleNamespace

import openai
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")  # klucze z .env -> os.environ (rejestr X-09 czyta env)

import hackcore.llm as hllm  # noqa: E402
from app.form_builder.builder import build
from app.form_builder.draft_llm import chunks, make_draft
from app.pipeline import registry
from app.rules_check import check
from hackcore import LLMClient, load_document
ROOT = Path(__file__).resolve().parent.parent
LEAF_SKIP = {"SECTION", "INFO_SECTION", "TEXT_BLOCK"}
PREFERRED = ["docx", "pdf", "xlsx", "odt", "ods", "doc", "png", "jpg", "jpeg"]  # jak scripts/generate_wyniki.py


def pick(folder: Path) -> Path:
    """Kopia z generate_wyniki.py (tamten moduł generuje wyniki już przy imporcie)."""
    files = [p for p in folder.rglob("*") if p.is_file() and "wizualizacja" not in p.name.lower()]
    by_ext = {p.suffix.lower().lstrip("."): p for p in files}
    return next(by_ext[e] for e in PREFERRED if e in by_ext)


@dataclass
class Stats:
    calls: int = 0
    rate_limited: int = 0
    wait_s: float = 0.0
    call_s: float = 0.0
    in_tok: int = 0
    out_tok: int = 0
    errors: list = field(default_factory=list)


def instrument(client: LLMClient, st: Stats, no_think: bool) -> None:
    """Podmienia _call klienta: mierzy czas wywołań, tokeny i 429 (logika retry LLMClient bez zmian)."""
    def _call(system, user, schema, name):
        if no_think:  # Qwen3: wyłączenie trybu thinking (soft switch)
            user = user + "\n/no_think"
        t = time.perf_counter()
        try:
            resp = client._client.chat.completions.create(
                model=client.model, temperature=0,
                messages=[{"role": "system", "content": system + hllm.JSON_HINT}, {"role": "user", "content": user}],
                response_format=client._response_format(schema, name))
        except openai.RateLimitError:
            st.rate_limited += 1
            raise
        except Exception as e:
            st.errors.append(f"{type(e).__name__}: {str(e)[:150]}")
            raise
        finally:
            st.call_s += time.perf_counter() - t
            st.calls += 1
        if resp.usage:
            st.in_tok += resp.usage.prompt_tokens or 0
            st.out_tok += resp.usage.completion_tokens or 0
        return resp.choices[0].message.content or ""
    client._call = _call


def _norm(s: str) -> str:
    return " ".join(re.sub(r"[^\w ]+", " ", (s or "").lower()).split())


def subject_labels(form: dict) -> list[str]:
    """Etykiety pól w zakładkach merytorycznych (bez „Dane”, „Kontakt…” i FINISH — te są z szablonów)."""
    out: list[str] = []

    def walk(qs):
        for q in qs:
            f = q["field"]
            if f["type"] not in LEAF_SKIP:
                out.append(f["title"])
            walk(f.get("repeatingSectionGrid") or [])

    for t in form["tabs"]:
        if t["type"] == "MAIN" and t["title"] != "Dane" and not t["title"].lower().startswith("kontakt"):
            walk(t["questions"])
    return out


def match(pred: list[str], ref: list[str], thr: float = 0.75) -> dict:
    """Zachłanne dopasowanie etykiet (difflib) -> precision/recall/F1."""
    left = [_norm(r) for r in ref]
    hit = 0
    for p in map(_norm, pred):
        best = max(range(len(left)), key=lambda i: difflib.SequenceMatcher(None, p, left[i]).ratio(), default=None)
        if best is not None and difflib.SequenceMatcher(None, p, left[best]).ratio() >= thr:
            hit += 1
            left.pop(best)
    prec = hit / len(pred) if pred else 0.0
    rec = hit / len(ref) if ref else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    return {"precision": round(prec, 2), "recall": round(rec, 2), "f1": round(f1, 2), "pred": len(pred), "ref": len(ref)}


def reference(nr: str) -> tuple[dict | None, str]:
    if nr in ("1", "5"):
        gold = next((ROOT / "data" / nr).rglob("konfiguracja*.json"))
        return json.loads(gold.read_text("utf-8")), "wzorzec COI"
    p = ROOT / "wyniki" / f"{nr}.json"
    return (json.loads(p.read_text("utf-8")), "wyniki 14B") if p.exists() else (None, "")


def count_states(form: dict) -> int:
    n = 0

    def walk(qs):
        nonlocal n
        for q in qs:
            n += len(q["field"].get("states") or [])
            walk(q["field"].get("repeatingSectionGrid") or [])

    for t in form["tabs"]:
        walk(t["questions"])
    return n


def run_one(mid: str, nr: str, doc, timeout: float) -> dict:
    base, key, model = registry().connection(mid)
    client = LLMClient(base, key, model, timeout=timeout)
    st = Stats()
    instrument(client, st, no_think=model.startswith("qwen3"))
    real_sleep = time.sleep

    def sleep(s):
        st.wait_s += s
        real_sleep(s)

    hllm.time = SimpleNamespace(sleep=sleep)  # tylko LLMClient czeka na 429 przez time.sleep
    t0 = time.perf_counter()
    try:
        res = make_draft(doc, client, compliance=False)
    finally:
        hllm.time = time
    wall = time.perf_counter() - t0
    notes: list[str] = []
    form = build(res.draft, notes)
    errs = check(form)
    fields = [f for p in res.draft.pages for s in p.sections for f in s.fields]
    sections = [s for p in res.draft.pages for s in p.sections]
    ref, ref_kind = reference(nr)
    opts = [o.lower() for f in fields for o in f.options]
    row = {
        "model": mid, "form": nr, "source": res.source, "ok": res.source == "llm" and not errs,
        "wall_s": round(wall, 1), "net_s": round(wall - st.wait_s, 1), "llm_s": round(st.call_s, 1),
        "chunks": len(chunks(doc)[0]), **{k: v for k, v in asdict(st).items() if k != "errors"},
        "out_tok_per_s": round(st.out_tok / st.call_s, 1) if st.call_s else None,
        "pages": len(res.draft.pages), "fields": len(fields),
        "show_if": sum(f.show_if is not None for f in fields) + sum(s.show_if is not None for s in sections),
        "states_in_form": count_states(form), "choice_fields": sum(f.type in ("RADIO", "SELECT") for f in fields),
        "rules_errors": len(errs), "warnings": res.warnings[:5], "errors": st.errors[:5],
        "ref_kind": ref_kind, "quality": match(subject_labels(form), subject_labels(ref)) if ref else None,
    }
    if nr == "4":  # kryterium F-16: RADIO wynajęcie/użyczenie
        row["f4_wynajem_uzyczenie"] = any("użycz" in o for o in opts) and any("wynaj" in o or "najem" in o for o in opts)
    return row, form


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", required=True)
    ap.add_argument("--forms", default="1,5,2,4,7,8")
    ap.add_argument("--out", default="benchmark")
    ap.add_argument("--timeout", type=float, default=600)
    ap.add_argument("--pause", type=float, default=2, help="przerwa między wywołaniami (limit darmowego API)")
    a = ap.parse_args()
    out = ROOT / a.out
    docs = {nr: load_document((src := pick(ROOT / "data" / nr)).read_bytes(), src.name) for nr in a.forms.split(",")}
    for mid in a.models.split(","):
        (out / mid).mkdir(parents=True, exist_ok=True)
        for nr, doc in docs.items():
            try:
                row, form = run_one(mid, nr, doc, a.timeout)
                (out / mid / f"{nr}.json").write_text(json.dumps(form, ensure_ascii=False, indent=2), "utf-8")
            except Exception as e:  # noqa: BLE001 — benchmark idzie dalej
                row = {"model": mid, "form": nr, "ok": False, "crash": f"{type(e).__name__}: {e}"[:300]}
            with (out / "results.jsonl").open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            q = row.get("quality") or {}
            print(f"{mid:20} form {nr}: ok={row.get('ok')} src={row.get('source')} wall={row.get('wall_s')}s "
                  f"net={row.get('net_s')}s 429={row.get('rate_limited')} out_tok={row.get('out_tok')} "
                  f"fields={row.get('fields')} show_if={row.get('show_if')} F1={q.get('f1')} {row.get('crash', '')}",
                  flush=True)
            time.sleep(a.pause)


if __name__ == "__main__":
    main()
