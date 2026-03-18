#!/usr/bin/env python3
"""
Download the JLCPCB parts database using the official JLCPCB Open API.

Uses /demo/component/info (cursor pagination, 1 000 parts/page) and streams
each page directly into the local SQLite DB — no large intermediate file.

Requires credentials in .env or environment:
    JLCPCB_APP_ID
    JLCPCB_API_KEY
    JLCPCB_API_SECRET

Usage:
    python3 scripts/download_jlcpcb_db_api.py
    python3 scripts/download_jlcpcb_db_api.py --output /custom/path/jlcpcb_parts.db
    python3 scripts/download_jlcpcb_db_api.py --stats-only
"""

import argparse
import logging
import os
import sys
from pathlib import Path

# Allow imports from python/ directory
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
sys.path.insert(0, str(_PROJECT_ROOT / "python"))

# Load .env before importing anything that reads env vars
_env_path = _PROJECT_ROOT / ".env"
if _env_path.exists():
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _, _v = _line.partition("=")
                os.environ.setdefault(_k.strip(), _v.strip())

import importlib.util as _ilu

def _load(name, path):
    spec = _ilu.spec_from_file_location(name, path)
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

_jlcpcb       = _load("jlcpcb",       _PROJECT_ROOT / "python" / "commands" / "jlcpcb.py")
_jlcpcb_parts = _load("jlcpcb_parts", _PROJECT_ROOT / "python" / "commands" / "jlcpcb_parts.py")

JLCPCBClient       = _jlcpcb.JLCPCBClient
JLCPCBPartsManager = _jlcpcb_parts.JLCPCBPartsManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

DEFAULT_OUTPUT = str(_PROJECT_ROOT / "data" / "jlcpcb_parts.db")


def print_stats(db_path: str) -> None:
    mgr = JLCPCBPartsManager(db_path)
    stats = mgr.get_database_stats()
    log.info("--- Database stats ---")
    log.info("  Total parts : %d", stats["total_parts"])
    log.info("  Basic       : %d", stats["basic_parts"])
    log.info("  Preferred   : %d", stats.get("preferred_parts", 0))
    log.info("  Extended    : %d", stats["extended_parts"])
    log.info("  In stock    : %d", stats.get("in_stock", 0))
    log.info("  DB path     : %s", stats["db_path"])


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download JLCPCB parts DB via the official Open API."
    )
    parser.add_argument(
        "--output", "-o",
        default=DEFAULT_OUTPUT,
        help=f"Output database path (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--stats-only",
        action="store_true",
        help="Print stats for existing database and exit",
    )
    args = parser.parse_args()

    if args.stats_only:
        print_stats(args.output)
        return

    # Validate credentials
    app_id     = os.getenv("JLCPCB_APP_ID")
    access_key = os.getenv("JLCPCB_API_KEY")
    secret_key = os.getenv("JLCPCB_API_SECRET")

    missing = [k for k, v in [
        ("JLCPCB_APP_ID", app_id),
        ("JLCPCB_API_KEY", access_key),
        ("JLCPCB_API_SECRET", secret_key),
    ] if not v]

    if missing:
        log.error("Missing credentials: %s", ", ".join(missing))
        log.error("Set them in .env or as environment variables.")
        sys.exit(1)

    client = JLCPCBClient(app_id=app_id, access_key=access_key, secret_key=secret_key)

    # Wipe existing DB so we start clean
    output_path = Path(args.output)
    if output_path.exists():
        log.info("Removing existing database: %s", args.output)
        output_path.unlink()

    mgr = JLCPCBPartsManager(args.output)
    total_imported = [0]

    def on_page(items):
        count = mgr.import_component_info_parts(items)
        total_imported[0] += count
        log.info("  … %d parts imported so far", total_imported[0])

    log.info("Starting download via JLCPCB Open API /demo/component/info ...")
    log.info("Output: %s", args.output)

    client.download_full_database(on_page=on_page)

    log.info("Rebuilding full-text search index ...")
    mgr.rebuild_fts_index()

    db_size_mb = output_path.stat().st_size / 1_048_576
    log.info("Done. %d parts imported. DB size: %.1f MB", total_imported[0], db_size_mb)
    print_stats(args.output)


if __name__ == "__main__":
    main()
