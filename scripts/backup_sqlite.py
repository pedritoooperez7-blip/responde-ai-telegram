#!/usr/bin/env python3
"""Create a consistent SQLite backup without stopping the application.

Uses SQLite's online backup API, so it is safe while the app is writing. The
source database is opened read-only and is never modified. Existing files are
never overwritten: a numeric suffix is added when needed.

Usage:
    python scripts/backup_sqlite.py --db /data/liggacuba.db --out-dir /data/backups
    python scripts/backup_sqlite.py --out-dir /data/backups --keep 14

Restoring is a manual, documented procedure (docs/BACKUP_RESTORE.md). This
script never restores, replaces or deletes a database in place.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time
from pathlib import Path
from urllib.parse import quote

DEFAULT_DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "liggacuba.db")
BACKUP_PREFIX = "liggacuba-"


def _read_only_uri(path: Path) -> str:
    return "file:" + quote(str(path.resolve())) + "?mode=ro"


def _unique_destination(out_dir: Path, stamp: str) -> Path:
    candidate = out_dir / f"{BACKUP_PREFIX}{stamp}.db"
    counter = 1
    while candidate.exists():
        candidate = out_dir / f"{BACKUP_PREFIX}{stamp}-{counter}.db"
        counter += 1
    return candidate


def backup(db_path: str | os.PathLike, out_dir: str | os.PathLike, keep: int | None = None,
           timestamp: float | None = None) -> Path:
    """Copy ``db_path`` to a new file in ``out_dir`` and verify its integrity.

    ``keep`` is opt-in: when set to a positive number, older backups created by
    this script are removed after the new one is verified.
    """
    source_path = Path(db_path)
    if not source_path.is_file():
        raise FileNotFoundError(f"La base de datos no existe: {source_path}")
    destination_dir = Path(out_dir)
    destination_dir.mkdir(parents=True, exist_ok=True)

    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(timestamp if timestamp is not None else time.time()))
    destination = _unique_destination(destination_dir, stamp)

    source = sqlite3.connect(_read_only_uri(source_path), uri=True, timeout=15)
    target = sqlite3.connect(str(destination), timeout=15)
    try:
        source.backup(target)
        target.commit()
        integrity = target.execute("PRAGMA integrity_check").fetchone()
    finally:
        target.close()
        source.close()

    if not integrity or str(integrity[0]).lower() != "ok":
        raise RuntimeError("La copia no superó la comprobación de integridad; no se considera válida")

    if keep is not None and int(keep) > 0:
        backups = sorted(destination_dir.glob(f"{BACKUP_PREFIX}*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in backups[int(keep):]:
            if old != destination:
                old.unlink()
    return destination


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Copia de seguridad consistente de SQLite")
    parser.add_argument("--db", default=os.getenv("DB_PATH", DEFAULT_DB), help="Ruta de la base de datos (por defecto DB_PATH)")
    parser.add_argument("--out-dir", default=os.getenv("BACKUP_DIR", "backups"), help="Directorio de destino")
    parser.add_argument("--keep", type=int, default=None, help="Conservar solo N copias (opcional; sin valor no se borra nada)")
    args = parser.parse_args(argv)
    try:
        destination = backup(args.db, args.out_dir, keep=args.keep)
    except (FileNotFoundError, RuntimeError, sqlite3.Error) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Copia verificada: {destination} ({destination.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
