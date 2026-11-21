import os
from dataclasses import dataclass, field


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class Settings:
    llm_base_url: str = field(default_factory=lambda: _env("LLM_BASE_URL"))
    llm_api_key: str = field(default_factory=lambda: _env("LLM_API_KEY"))
    llm_model: str = field(default_factory=lambda: _env("LLM_MODEL"))
    ocr_lang: str = field(default_factory=lambda: _env("OCR_LANG", "pol"))
    max_file_size_mb: int = field(default_factory=lambda: int(_env("MAX_FILE_SIZE_MB", "20")))
    auth_enabled: bool = field(default_factory=lambda: _env("AUTH_ENABLED", "true").lower() == "true")
    auth_user: str = field(default_factory=lambda: _env("AUTH_USER", "admin"))
    auth_password: str = field(default_factory=lambda: _env("AUTH_PASSWORD"))
    jwt_secret: str = field(default_factory=lambda: _env("JWT_SECRET"))
    jwt_algorithm: str = field(default_factory=lambda: _env("JWT_ALGORITHM", "HS256"))
    jwt_expire_minutes: int = field(default_factory=lambda: int(_env("JWT_EXPIRE_MINUTES", "60")))
    approval_required: bool = field(default_factory=lambda: _env("APPROVAL_REQUIRED", "false").lower() == "true")
    audit_dir: str = field(default_factory=lambda: _env("AUDIT_DIR", "audit"))


settings = Settings()
