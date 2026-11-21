"""F-18: bramka zatwierdzenia urzędnika (APPROVAL_REQUIRED) i rekord audytu zapisywany OBOK JSON-a formularza.

/convert wydaje podpisany token pochodzenia (hash źródła i wyniku, model). /approve sprawdza, że zatwierdzany JSON
to dokładnie ten wygenerowany, że przechodzi rules_check i że urzędnik odhaczył playbook — dopiero wtedy zapisuje rekord.
Rekord nie zawiera danych osobowych z dokumentu, tylko hashe, login urzędnika i wyniki sprawdzeń.
"""
import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt

from app import config
from app.form_builder.draft_llm import SYSTEM_RULES
from app.rules_check import check

ROOT = Path(__file__).resolve().parents[1]
# elementy wrażliwe potwierdzane osobno (playbook pkt 2 i 5), bez „zaznacz wszystko”
CHECKS = {
    "source_match": "Porównałem podgląd z oryginałem dokumentu",
    "readonly_prefill": "Sprawdziłem pola tylko do odczytu i dane z profilu zaufanego",
    "required": "Sprawdziłem, które pola są wymagane",
    "consents": "Sprawdziłem zgody i klauzulę RODO",
    "fees": "Sprawdziłem opłaty i numery kont",
}
STATEMENT = "Sprawdziłem zgodność formularza z oryginałem i przepisami"
_PROCESS_SECRET = secrets.token_hex(32)  # gdy AUTH_ENABLED=false i brak JWT_SECRET


class ApprovalError(Exception):
    """Zatwierdzenie odrzucone -> 400/409/422 (status w atrybucie)."""

    def __init__(self, status: int, msg: str):
        super().__init__(msg)
        self.status = status


def sha256_json(form: dict) -> str:
    return hashlib.sha256(json.dumps(form, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _secret() -> str:
    return config.settings.jwt_secret or _PROCESS_SECRET


def versions() -> dict:
    tpl = hashlib.sha256()
    for p in sorted((ROOT / "config" / "section_templates").glob("*.json")) + [ROOT / "config" / "field_rules.yaml"]:
        tpl.update(p.name.encode() + p.read_bytes())
    return {"app": "0.1.0", "prompt_sha256": hashlib.sha256(SYSTEM_RULES.encode()).hexdigest(), "templates_sha256": tpl.hexdigest()}


def issue(data: bytes, form: dict, model: str | None, source: str, name: str) -> dict:
    """Blok `approval` w odpowiedzi /convert: status DRAFT + token pochodzenia (ważny 24 h)."""
    claims = {"src": hashlib.sha256(data).hexdigest(), "name": name, "form": sha256_json(form), "model": model,
              "draft": source, "exp": datetime.now(timezone.utc) + timedelta(hours=24)}
    return {"status": "DRAFT", "token": jwt.encode(claims, _secret(), algorithm="HS256"),
            "checks": CHECKS, "statement": STATEMENT}


def approve(form: dict, token: str, checks: dict, statement: bool, pages_visited: list, review_seconds: int,
            user: str | None) -> dict:
    try:
        c = jwt.decode(token, _secret(), algorithms=["HS256"])
    except jwt.PyJWTError as e:
        raise ApprovalError(400, f"Nieprawidłowy lub wygasły token pochodzenia: {e}") from e
    form_sha = sha256_json(form)
    if form_sha != c["form"]:
        raise ApprovalError(409, "JSON różni się od wygenerowanego (zmiany poza systemem) — wygeneruj formularz ponownie")
    if errs := check(form):
        raise ApprovalError(422, f"Formularz nie przechodzi walidatora: {'; '.join(errs[:3])}")
    if missing := [CHECKS[k] for k in CHECKS if checks.get(k) is not True]:
        raise ApprovalError(400, "Niepotwierdzone: " + "; ".join(missing))
    if statement is not True:
        raise ApprovalError(400, "Brak oświadczenia: " + STATEMENT)
    if unseen := [t.get("title") for t in form["tabs"] if t["id"] not in set(pages_visited)]:
        raise ApprovalError(400, "Nie obejrzano stron podglądu: " + ", ".join(map(str, unseen)))
    record = {
        "status": "APPROVED", "approved_by": user or "anonim (AUTH_ENABLED=false)",
        "approved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": {"sha256": c["src"], "name": c["name"]}, "form_sha256": form_sha,
        "ai": {"generated_by_ai": c["draft"] == "llm", "draft_source": c["draft"], "model": c["model"], **versions()},
        "checks": {CHECKS[k]: True for k in CHECKS}, "statement": STATEMENT, "rules_check": "OK",
        "review": {"pages_visited": len(form["tabs"]), "seconds": int(review_seconds)},
    }
    out = Path(config.settings.audit_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{form_sha}.approval.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), "utf-8")
    return record
