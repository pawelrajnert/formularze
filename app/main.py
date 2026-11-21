from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool
from starlette.formparsers import MultiPartParser

from app import approval, config
from app.pipeline import ConversionError, IngestError, UnknownModel, convert_document, registry
from app.security import check_credentials, create_token, require_auth, require_configured
from app.validation import check_content, check_name, read_limited

# pliki tylko w pamięci: Starlette domyślnie zrzuca upload > 1 MB do pliku tymczasowego
MultiPartParser.spool_max_size = 1 << 40

app = FastAPI(title="COI — cyfryzacja formularzy", version="0.1.0")
WEB_DIR = Path(__file__).resolve().parent.parent / "web"
app.mount("/web", StaticFiles(directory=WEB_DIR), name="web")


def _max_bytes() -> int:
    return config.settings.max_file_size_mb * 1024 * 1024


@app.middleware("http")
async def reject_big_bodies(request: Request, call_next):
    # shortcut: tylko Content-Length; upload chunked bez nagłówka trafia do read_limited dopiero po sparsowaniu
    if int(request.headers.get("content-length") or 0) > _max_bytes() + 64 * 1024:
        return JSONResponse({"detail": "Plik za duży"}, status_code=413)
    return await call_next(request)


class Approval(BaseModel):
    form: dict
    token: str
    checks: dict[str, bool]
    statement: bool
    pages_visited: list[str]
    review_seconds: int = 0


class Credentials(BaseModel):
    username: str
    password: str


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/v1/auth/token")
def token(body: Credentials) -> dict:
    require_configured()  # 503 zamiast tokenu z pustym sekretem/hasłem
    if not check_credentials(body.username, body.password):
        raise HTTPException(401, "Nieprawidłowy login lub hasło")
    return {"access_token": create_token(body.username), "token_type": "bearer"}


@app.get("/api/v1/models", dependencies=[Depends(require_auth)])
def models() -> list[dict]:
    return registry().public()


@app.post("/api/v1/forms/approve")
def approve(body: Approval, user: str | None = Depends(require_auth)) -> dict:
    try:
        record = approval.approve(**body.model_dump(), user=user)
    except approval.ApprovalError as e:
        raise HTTPException(e.status, str(e)) from e
    return {"record": record}


@app.post("/api/v1/forms/convert", dependencies=[Depends(require_auth)])
async def convert(file: UploadFile, debug: bool = False, model: str | None = None) -> dict:
    ext = check_name(file.filename)
    data = await read_limited(file, _max_bytes())
    check_content(data, ext)
    stem = file.filename.rsplit(".", 1)[0]
    try:
        # w wątku: OCR/LibreOffice/LLM blokują, a pętla zdarzeń ma obsługiwać inne żądania
        result = await run_in_threadpool(convert_document, data, ext, debug, stem, model)
    except UnknownModel as e:
        raise HTTPException(400, str(e)) from e
    except (IngestError, ConversionError) as e:
        raise HTTPException(422, str(e)) from e
    # 504 nieużywane: błąd/timeout LLM zawsze kończy się fallbackiem heurystycznym w pipeline
    return {"filename": file.filename, **result}
