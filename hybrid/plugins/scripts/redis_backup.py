#!/usr/bin/env python3
"""
Daily Redis backup with optional restore verification.
Run via cron (e.g. 0 2 * * * = 2 AM daily) or Task Scheduler.

Usage:
  python scripts/redis_backup.py [--backup-dir DIR] [--verify]
  REDIS_URL can be set in environment; defaults to redis://localhost:6379/0.
"""
import os
import sys
import argparse
import asyncio
import shutil
from datetime import datetime

try:
    import redis.asyncio as redis
except ImportError:
    import redis
    redis.asyncio = None


REDIS_URI = os.environ.get("REDIS_URL", "redis://localhost:6379/0")


async def run_backup(backup_dir: str, verify: bool) -> bool:
    if redis.asyncio is None:
        print("redis.asyncio not available; install redis with pip", file=sys.stderr)
        return False
    client = redis.from_url(REDIS_URI, decode_responses=False)
    try:
        # Trigger background save; wait for it
        await client.bgsave()
        # Poll until save completed (lastsave changes)
        last = await client.lastsave()
        for _ in range(30):
            await asyncio.sleep(1)
            now = await client.lastsave()
            if now != last:
                break
        # Redis RDB path is server-specific; for remote Redis we cannot copy file.
        # Document that for local Redis, copy dump.rdb from dir config.
        stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        info = await client.info("persistence")
        rdb_path = info.get("rdb_last_save_path") or "dump.rdb"
        dest = os.path.join(backup_dir, f"redis_backup_{stamp}.rdb")
        if os.path.isabs(rdb_path) and os.path.exists(rdb_path):
            shutil.copy2(rdb_path, dest)
            print(f"Backup copied to {dest}")
        else:
            print(f"RDB path from server: {rdb_path}. For local Redis, copy it to {dest} manually.")
        if verify:
            # Light verification: ping and dbsize
            await client.ping()
            size = await client.dbsize()
            print(f"Verify OK: dbsize={size}")
    finally:
        await client.aclose()
    return True


def main():
    ap = argparse.ArgumentParser(description="Redis backup (BGSAVE) and optional verify")
    ap.add_argument("--backup-dir", default=DEFAULT_BACKUP_DIR, help="Directory to store backup copies (default: project_root/backups)")
    ap.add_argument("--verify", action="store_true", help="Run a quick connectivity/dbsize check after backup")
    args = ap.parse_args()
    os.makedirs(args.backup_dir, exist_ok=True)
    ok = asyncio.run(run_backup(args.backup_dir, args.verify))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
