#!/usr/bin/env python3
"""Restore a database backup downloaded from the Telegram backup chat.

Usage:
  BACKUP_ENCRYPTION_KEY=... python scripts/restore_telegram_backup.py liggacuba-XXXX.db.gz.enc /base/liggacuba.db
  python scripts/restore_telegram_backup.py liggacuba-XXXX.db.gz /base/liggacuba.db

Never overwrites an existing file. Stop the app before moving the result into place.
"""
import base64, gzip, hashlib, os, sqlite3, sys

def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__); return 2
    src, dst = sys.argv[1], sys.argv[2]
    if os.path.exists(dst):
        print(f"Refusing to overwrite existing file: {dst}"); return 1
    data = open(src, "rb").read()
    if src.endswith(".enc"):
        key = (os.getenv("BACKUP_ENCRYPTION_KEY") or "").strip()
        if not key:
            print("Set BACKUP_ENCRYPTION_KEY to decrypt this backup."); return 1
        from cryptography.fernet import Fernet
        data = Fernet(base64.urlsafe_b64encode(hashlib.sha256(key.encode()).digest())).decrypt(data)
    raw = gzip.decompress(data)
    with open(dst, "wb") as handle:
        handle.write(raw)
    check = sqlite3.connect(dst).execute("PRAGMA integrity_check").fetchone()[0]
    print("Restored. integrity_check:", check)
    return 0 if check == "ok" else 1

if __name__ == "__main__":
    sys.exit(main())
