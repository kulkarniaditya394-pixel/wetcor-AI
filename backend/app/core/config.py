"""Runtime configuration. Read from environment variables (see backend/.env.example)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

APP_NAME = "WETCOR AI"
APP_VERSION = "1.0.0"
ROOT_DIR = Path(__file__).resolve().parents[3]  # wetcor-ai/


def _load_dotenv(path: Path) -> None:
    """Minimal KEY=VALUE loader; real environment variables win."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(ROOT_DIR / "backend" / ".env")


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(os.getenv("WETCOR_DATA_DIR", ROOT_DIR / "data")).resolve())
    models_dir: Path = field(default_factory=lambda: Path(os.getenv("WETCOR_MODELS_DIR", ROOT_DIR / "models")).resolve())
    host: str = field(default_factory=lambda: os.getenv("WETCOR_HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: int(os.getenv("WETCOR_PORT", "8100")))
    cors_origins: list[str] = field(
        default_factory=lambda: [
            o.strip()
            for o in os.getenv("WETCOR_CORS_ORIGINS", "http://localhost:3100,http://127.0.0.1:3100").split(",")
            if o.strip()
        ]
    )
    max_upload_bytes: int = field(default_factory=lambda: int(float(os.getenv("WETCOR_MAX_UPLOAD_MB", "25")) * 1024 * 1024))

    @property
    def database_path(self) -> Path:
        return self.data_dir / "database" / "wetcor.sqlite3"

    def ensure_dirs(self) -> None:
        for sub in ("database", "raw", "processed", "reports", "demo", "trash"):
            (self.data_dir / sub).mkdir(parents=True, exist_ok=True)
        self.models_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()


def use_data_dir(data_dir: Path, models_dir: Path | None = None) -> None:
    """Point the app at another workspace (used by tests)."""
    settings.data_dir = Path(data_dir).resolve()
    settings.models_dir = Path(models_dir or Path(data_dir) / "models").resolve()
