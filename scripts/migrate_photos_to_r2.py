#!/usr/bin/env python3
"""Sube a Backblaze B2 las fotos de Citas que hoy están en disco.

Es SEGURO: solo copia (nunca borra nada del disco) y se puede repetir las veces
que haga falta (si una foto ya está en B2 se salta). Ejecútalo en Railway con las
variables B2_* ya configuradas:

    python scripts/migrate_photos_to_r2.py            # copia
    python scripts/migrate_photos_to_r2.py --dry-run  # solo muestra qué subiría

Cuando termines y compruebes que las fotos se ven bien, ya puedes borrar a mano la
carpeta dating_photos del disco para recuperar espacio.
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import storage  # noqa: E402


def photos_dir() -> str:
    configured = (os.getenv("DATING_PHOTOS_DIR") or "").strip()
    if configured:
        return configured
    db_path = (os.getenv("DB_PATH") or "").strip()
    if db_path:
        return os.path.join(os.path.dirname(os.path.abspath(db_path)), "dating_photos")
    return "dating_photos"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="no sube nada, solo lista")
    args = parser.parse_args()
    if not storage.enabled():
        print("B2 no está configurado: define B2_ENDPOINT, B2_ACCESS_KEY, B2_SECRET_KEY y B2_BUCKET.")
        return 1
    folder = photos_dir()
    if not os.path.isdir(folder):
        print(f"No existe la carpeta de fotos: {folder} (nada que migrar).")
        return 0
    uploaded = skipped = failed = 0
    for name in sorted(os.listdir(folder)):
        path = os.path.join(folder, name)
        if not os.path.isfile(path) or not name.lower().endswith(".jpg"):
            continue
        if storage.get(name) is not None:
            skipped += 1
            continue
        if args.dry_run:
            print(f"subiría: {name}")
            uploaded += 1
            continue
        with open(path, "rb") as handle:
            ok = storage.put(name, handle.read())
        if ok:
            uploaded += 1
        else:
            failed += 1
            print(f"FALLÓ: {name}")
    print(f"Listo. Subidas: {uploaded} · Ya estaban en B2: {skipped} · Fallidas: {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
