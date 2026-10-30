"""Artifact storage: raw files are written once, hashed, and never modified.

User-supplied filenames are sanitised and only ever used as a suffix of a server-generated name,
so they cannot choose a directory. Stored paths are relative to the data directory and resolved
with a containment check before every read.
"""
from __future__ import annotations

import hashlib
import re
import shutil
from pathlib import Path, PurePath
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.database.models import Artifact, AuditEvent, utcnow

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


class StorageError(Exception):
    pass


def safe_filename(name: str | None, default: str = "file") -> str:
    base = PurePath((name or "").replace("\\", "/")).name
    base = _UNSAFE.sub("_", base).strip("._")
    return base[:120] or default


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def store_artifact(
    db: Session,
    data: bytes,
    *,
    kind: str,
    subdir: str,
    original_filename: str,
    content_type: str,
    specimen_id: int | None = None,
    experiment_id: int | None = None,
    is_demo: bool = False,
    meta: dict[str, Any] | None = None,
) -> Artifact:
    digest = sha256_bytes(data)
    name = safe_filename(original_filename)
    stamp = utcnow().strftime("%Y%m%dT%H%M%S")
    rel = Path(subdir) / f"{stamp}_{digest[:12]}_{name}"
    target = settings.data_dir / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    n = 1
    while target.exists():  # never overwrite an existing file
        rel = Path(subdir) / f"{stamp}_{digest[:12]}_{n}_{name}"
        target = settings.data_dir / rel
        n += 1
    with open(target, "xb") as fh:
        fh.write(data)
    artifact = Artifact(
        kind=kind,
        original_filename=(original_filename or name)[:255],
        stored_path=rel.as_posix(),
        sha256=digest,
        size_bytes=len(data),
        content_type=content_type,
        specimen_id=specimen_id,
        experiment_id=experiment_id,
        is_demo=is_demo,
        meta=meta or {},
    )
    db.add(artifact)
    db.flush()
    return artifact


def artifact_path(artifact: Artifact) -> Path:
    root = settings.data_dir.resolve()
    path = (root / artifact.stored_path).resolve()
    if root not in path.parents:
        raise StorageError("Artifact path escapes the data directory")
    return path


def read_artifact(artifact: Artifact, verify: bool = True) -> bytes:
    path = artifact_path(artifact)
    if not path.exists():
        raise StorageError(f"Stored file for artifact {artifact.id} is missing")
    data = path.read_bytes()
    if verify and sha256_bytes(data) != artifact.sha256:
        raise StorageError(f"Stored file for artifact {artifact.id} does not match its recorded SHA-256")
    return data


def move_to_trash(artifact: Artifact) -> str | None:
    """Move a file into data/trash instead of deleting it. Returns the trash path (relative)."""
    try:
        src = artifact_path(artifact)
    except StorageError:
        return None
    if not src.exists():
        return None
    rel = Path("trash") / f"{utcnow():%Y%m%dT%H%M%S}_{artifact.id}_{src.name}"
    dest = settings.data_dir / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))
    return rel.as_posix()


def delete_file(artifact: Artifact) -> None:
    """Hard delete; used only for synthetic demo artifacts."""
    try:
        artifact_path(artifact).unlink(missing_ok=True)
    except StorageError:
        pass


def audit(db: Session, entity_type: str, entity_id: Any, action: str, summary: str, details: dict | None = None) -> None:
    db.add(AuditEvent(entity_type=entity_type, entity_id=str(entity_id), action=action, summary=summary[:300], details=details or {}))
