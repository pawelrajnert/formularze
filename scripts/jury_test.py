"""R-09: test „jak jury” — pliki wrzucane NA ŻYWO przez REST API do działającej usługi, każdy JSON walidowany.

Użycie (usługa musi działać, np. `start.bat` albo `docker run … -p 8013:8000`):
  python -m scripts.jury_test --url http://localhost:8013 [--dirs data/1 data/2 …] [--out jury] [--limit N]

Dla każdego pliku: POST /api/v1/forms/convert (JWT jak jury), czas end-to-end, a wynik:
  1) `app.rules_check.check` (JSON Schema COI + reguły techniczne),
  2) ORYGINALNY `importowanyPlikJsonSchemat` — dosłownie na całym JSON-ie,
  3) oryginalny schemat pytania na KAŻDYM poziomie (oryginał ma literówkę `repetingSectionGrid`, więc sam nie sprawdza
     pól zagnieżdżonych); jawne odstępstwa jak w tests/test_template_keys.py (defaultValue-lista dla SELECT/CHECKBOX).
Wynik: <out>/<nazwa>.json (form + trace) i <out>/RAPORT.md (tabela). Hasło/token nie trafiają do plików.
"""
import argparse
import json
import os
import time
from pathlib import Path

import httpx
from dotenv import dotenv_values
from jsonschema import Draft202012Validator

from app.rules_check import check

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = json.loads(next((ROOT / "data").glob("Materiały do zadania dla Uczestników/**/importowanyPlikJsonSchemat*.json"))
                    .read_text("utf-8"))
_ROOT_V = Draft202012Validator(SCHEMA)
_Q_V = Draft202012Validator(SCHEMA["properties"]["tabs"]["items"]["properties"]["questions"]["items"])
ALLOWED = {("SELECT", "field/defaultValue"), ("CHECKBOX", "field/defaultValue")}
SKIP = ("wizualizacja", "konfiguracja", "~$")
EXT = {".pdf", ".doc", ".docx", ".xlsx", ".ods", ".odt", ".jpg", ".jpeg", ".jpe", ".png"}


def _questions(qs):
    for q in qs:
        yield q
        yield from _questions(q["field"].get("repeatingSectionGrid") or [])


def schema_errors(form: dict) -> tuple[list[str], list[str]]:
    root = [f"{'/'.join(map(str, e.absolute_path)) or '(root)'}: {e.message}" for e in _ROOT_V.iter_errors(form)]
    every = []
    for t in form.get("tabs", []):
        for q in _questions(t.get("questions", [])):
            for e in _Q_V.iter_errors(q):
                where = "/".join(map(str, e.absolute_path))
                if (q["field"].get("type"), where) not in ALLOWED:
                    every.append(f"{t.get('title')}/{q['field'].get('techName')}: {where}: {e.message[:120]}")
    return root, every


def files(dirs: list[str]) -> list[Path]:
    out = []
    for d in dirs:
        for p in sorted(Path(d).rglob("*")):
            if p.is_file() and p.suffix.lower() in EXT and not any(s in p.name.lower() for s in SKIP):
                out.append(p)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8000")
    ap.add_argument("--dirs", nargs="*", default=[str(ROOT / "data" / str(i)) for i in range(1, 10)])
    ap.add_argument("--out", default=str(ROOT / "jury"))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--timeout", type=float, default=300)
    a = ap.parse_args()
    env = {**dotenv_values(ROOT / ".env"), **os.environ}
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    api = a.url.rstrip("/") + "/api/v1"
    with httpx.Client(timeout=a.timeout) as c:
        r = c.post(api + "/auth/token", json={"username": env.get("AUTH_USER", "admin"), "password": env.get("AUTH_PASSWORD", "")})
        headers = {"Authorization": f"Bearer {r.json()['access_token']}"} if r.status_code == 200 else {}
        todo = files(a.dirs)[: a.limit or None]
        rows = []
        for i, p in enumerate(todo, 1):
            t0 = time.perf_counter()
            try:
                resp = c.post(api + "/forms/convert?debug=true", headers=headers,
                              files={"file": (p.name, p.read_bytes())})
                status, body = resp.status_code, (resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {})
            except httpx.HTTPError as e:
                status, body = 0, {"detail": f"{type(e).__name__}: {e}"}
            secs = time.perf_counter() - t0
            row = {"plik": f"{p.parent.parent.name[:2].strip()}/{p.name}", "format": p.suffix.lower().lstrip("."),
                   "http": status, "s": round(secs, 1)}
            if status == 200 and "form" in body:
                form, tr = body["form"], body.get("trace", {})
                root, every = schema_errors(form)
                row |= {"rules": len(check(form)), "schemat": len(root), "schemat_poziomy": len(every),
                        "zrodlo": tr.get("source"), "model": tr.get("model"), "ocr": tr.get("ocr_used"),
                        "stron": len(form["tabs"]), "do_sprawdzenia": len((tr.get("changes") or {}).get("check", [])),
                        "timings": tr.get("timings"), "bledy": (root + every)[:3]}
                (out / f"{p.stem}.{row['format']}.json").write_text(
                    json.dumps({"form": form, "trace": tr}, ensure_ascii=False, indent=1), "utf-8")
            else:
                row["blad"] = str(body.get("detail", body))[:200]
            rows.append(row)
            ok = row.get("rules") == 0 and row.get("schemat") == 0 and row.get("schemat_poziomy") == 0
            print(f"[{i}/{len(todo)}] {'OK ' if ok else 'ERR'} {row['plik'][:60]:60} http={status} {secs:5.1f}s "
                  f"źródło={row.get('zrodlo')} model={row.get('model')} rules={row.get('rules')} schemat={row.get('schemat')}"
                  f"/{row.get('schemat_poziomy')} {row.get('blad', '')}", flush=True)
            (out / "results.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), "utf-8")
    report(rows, out)


def report(rows: list[dict], out: Path) -> None:
    ok = [r for r in rows if r.get("rules") == 0 and r.get("schemat") == 0 and r.get("schemat_poziomy") == 0]
    llm = [r for r in rows if r.get("zrodlo") == "llm"]
    times = sorted(r["s"] for r in rows if r.get("http") == 200)
    med = times[len(times) // 2] if times else 0
    lines = ["# Test „jak jury” (R-09)", "",
             f"Plików: **{len(rows)}** · HTTP 200: **{sum(r.get('http') == 200 for r in rows)}** · "
             f"poprawny JSON (reguły + oryginalny schemat na każdym poziomie): **{len(ok)}** · ze szkicu LLM: **{len(llm)}** · "
             f"czas mediana / max: **{med} s / {times[-1] if times else 0} s**", "",
             "| Plik | Format | HTTP | Czas | Źródło | Model | OCR | Reguły | Schemat (korzeń/poziomy) | Do sprawdzenia |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['plik']} | {r['format']} | {r['http']} | {r['s']} s | {r.get('zrodlo', '—')} | {r.get('model', '—')} | "
                     f"{'tak' if r.get('ocr') else ''} | {r.get('rules', '—')} | {r.get('schemat', '—')}/{r.get('schemat_poziomy', '—')} | "
                     f"{r.get('do_sprawdzenia', r.get('blad', '—'))} |")
    (out / "RAPORT.md").write_text("\n".join(lines) + "\n", "utf-8")
    print("\n".join(lines[:3]))


if __name__ == "__main__":
    main()
