#!/usr/bin/env python3
"""
Download and convert the JLCPCB parts database for use with the KiCAD MCP Server.

Source: https://cdfer.github.io/jlcpcb-parts-database/jlcpcb-components.sqlite3
        (daily-updated mirror of yaqwsx/jlcparts, ~1GB, filtered to 5+ in-stock components)

Target: data/jlcpcb_parts.db (SQLite schema expected by this MCP server)

Usage:
    python3 scripts/download_jlcpcb_db.py
    python3 scripts/download_jlcpcb_db.py --output /custom/path/jlcpcb_parts.db
    python3 scripts/download_jlcpcb_db.py --skip-download  # re-convert existing source db
"""

import argparse
import json
import logging
import os
import sqlite3
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

SOURCE_URL = "https://cdfer.github.io/jlcpcb-parts-database/jlcpcb-components.sqlite3"

# Resolve default output path relative to this script's location (project root / data/)
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
DEFAULT_OUTPUT = str(_PROJECT_ROOT / "data" / "jlcpcb_parts.db")
DEFAULT_CACHE = str(_PROJECT_ROOT / "data" / "jlcpcb-components.sqlite3")


# ---------------------------------------------------------------------------
# Download helpers
# ---------------------------------------------------------------------------

def _progress_hook(block_num: int, block_size: int, total_size: int) -> None:
    downloaded = block_num * block_size
    if total_size > 0:
        pct = min(downloaded / total_size * 100, 100)
        mb_done = downloaded / 1_048_576
        mb_total = total_size / 1_048_576
        print(
            f"\r  {pct:5.1f}%  {mb_done:7.1f} / {mb_total:.1f} MB",
            end="",
            flush=True,
        )
    else:
        print(f"\r  {downloaded / 1_048_576:.1f} MB downloaded", end="", flush=True)


def download_source_db(dest_path: str) -> None:
    """Download the CDFER SQLite database with resume support."""
    dest = Path(dest_path)
    dest.parent.mkdir(parents=True, exist_ok=True)

    # Check if a partial file exists for resume
    existing_bytes = dest.stat().st_size if dest.exists() else 0

    req = urllib.request.Request(SOURCE_URL)
    if existing_bytes:
        req.add_header("Range", f"bytes={existing_bytes}-")
        log.info("Resuming download from byte %d …", existing_bytes)

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            total = int(resp.headers.get("Content-Length", 0))
            if existing_bytes:
                total += existing_bytes  # adjust for partial

            log.info("Downloading %s", SOURCE_URL)
            log.info("Destination : %s", dest_path)
            if total:
                log.info("Total size  : %.1f MB", total / 1_048_576)

            mode = "ab" if existing_bytes else "wb"
            chunk = 1 << 20  # 1 MB
            written = existing_bytes

            with open(dest_path, mode) as fh:
                while True:
                    buf = resp.read(chunk)
                    if not buf:
                        break
                    fh.write(buf)
                    written += len(buf)
                    if total:
                        pct = min(written / total * 100, 100)
                        print(
                            f"\r  {pct:5.1f}%  {written / 1_048_576:7.1f} / {total / 1_048_576:.1f} MB",
                            end="",
                            flush=True,
                        )
                    else:
                        print(f"\r  {written / 1_048_576:.1f} MB", end="", flush=True)

            print()  # newline after progress
            log.info("Download complete: %.1f MB", written / 1_048_576)

    except urllib.error.HTTPError as e:
        if e.code == 416 and existing_bytes:
            log.info("Server says file is already complete (HTTP 416) — using cached copy.")
        else:
            raise


# ---------------------------------------------------------------------------
# Price format conversion
# ---------------------------------------------------------------------------

def _convert_price(price_json_str: str) -> str:
    """
    Convert jlcparts price format to MCP server format.

    jlcparts : [{"qFrom": 1, "qTo": 9,    "price": 0.002},
                 {"qFrom": 10, "qTo": null, "price": 0.001}]
    MCP server: [{"qty": 1,  "price": 0.002},
                 {"qty": 10, "price": 0.001}]
    """
    if not price_json_str:
        return "[]"
    try:
        breaks = json.loads(price_json_str)
        converted = [{"qty": b["qFrom"], "price": b["price"]} for b in breaks if "qFrom" in b]
        return json.dumps(converted)
    except Exception:
        return "[]"


def _library_type(basic: int, preferred: int) -> str:
    if basic:
        return "Basic"
    if preferred:
        return "Preferred"
    return "Extended"


# ---------------------------------------------------------------------------
# Schema creation (target DB)
# ---------------------------------------------------------------------------

TARGET_DDL = """
CREATE TABLE IF NOT EXISTS components (
    lcsc          TEXT PRIMARY KEY,
    category      TEXT,
    subcategory   TEXT,
    mfr_part      TEXT,
    package       TEXT,
    solder_joints INTEGER,
    manufacturer  TEXT,
    library_type  TEXT,
    description   TEXT,
    datasheet     TEXT,
    stock         INTEGER,
    price_json    TEXT,
    last_updated  INTEGER
);
CREATE INDEX IF NOT EXISTS idx_category     ON components(category, subcategory);
CREATE INDEX IF NOT EXISTS idx_package      ON components(package);
CREATE INDEX IF NOT EXISTS idx_manufacturer ON components(manufacturer);
CREATE INDEX IF NOT EXISTS idx_library_type ON components(library_type);
CREATE INDEX IF NOT EXISTS idx_mfr_part     ON components(mfr_part);
CREATE VIRTUAL TABLE IF NOT EXISTS components_fts USING fts5(
    lcsc,
    description,
    mfr_part,
    manufacturer,
    content=components
);
"""


# ---------------------------------------------------------------------------
# Conversion
# ---------------------------------------------------------------------------

def convert(source_db: str, target_db: str) -> None:
    """Read source SQLite, transform rows, write to target SQLite."""

    log.info("Opening source database: %s", source_db)
    src = sqlite3.connect(f"file:{source_db}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row

    # Verify expected schema
    tables = {r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "components" not in tables:
        src.close()
        raise RuntimeError(
            "Source database does not contain a 'components' table. "
            "It may be corrupted or from an unexpected source."
        )

    has_view = "v_components" in {
        r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='view'")
    }

    log.info("Creating target database: %s", target_db)
    Path(target_db).parent.mkdir(parents=True, exist_ok=True)

    # Remove existing target so we start clean
    if Path(target_db).exists():
        Path(target_db).unlink()

    tgt = sqlite3.connect(target_db)
    tgt.executescript(TARGET_DDL)
    tgt.execute("PRAGMA journal_mode = WAL")
    tgt.execute("PRAGMA synchronous  = NORMAL")

    now_ts = int(time.time())

    # Use the view when available (it already joins manufacturers + categories)
    if has_view:
        log.info("Using v_components view for conversion …")
        query = "SELECT * FROM v_components"
    else:
        log.info("v_components view not found — falling back to manual JOIN …")
        query = """
            SELECT
                c.lcsc        AS lcsc,
                cat.category  AS category,
                cat.subcategory AS subcategory,
                c.mfr         AS mfr,
                c.package     AS package,
                c.joints      AS joints,
                m.name        AS manufacturer,
                c.basic       AS basic,
                c.preferred   AS preferred,
                c.description AS description,
                c.datasheet   AS datasheet,
                c.stock       AS stock,
                c.price       AS price,
                c.last_update AS last_update
            FROM components c
            LEFT JOIN manufacturers m   ON c.manufacturer_id = m.id
            LEFT JOIN categories    cat ON c.category_id     = cat.id
        """

    insert_sql = """
        INSERT OR REPLACE INTO components (
            lcsc, category, subcategory, mfr_part, package,
            solder_joints, manufacturer, library_type, description,
            datasheet, stock, price_json, last_updated
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """

    batch = []
    BATCH_SIZE = 5_000
    total = 0
    skipped = 0

    log.info("Converting rows …")
    cursor = src.execute(query)

    while True:
        rows = cursor.fetchmany(BATCH_SIZE)
        if not rows:
            break

        for row in rows:
            r = dict(row)
            try:
                lcsc_int = r.get("lcsc")
                if lcsc_int is None:
                    skipped += 1
                    continue
                lcsc = f"C{int(lcsc_int)}"

                # Price: prefer 'price' column; view may call it 'price' too
                raw_price = r.get("price", "[]") or "[]"
                price_json = _convert_price(raw_price)

                basic     = int(r.get("basic", 0) or 0)
                preferred = int(r.get("preferred", 0) or 0)
                lib_type  = _library_type(basic, preferred)

                last_updated = r.get("last_update") or r.get("last_updated") or now_ts

                batch.append((
                    lcsc,
                    r.get("category", ""),
                    r.get("subcategory", ""),
                    r.get("mfr", ""),        # mfr_part (manufacturer part number)
                    r.get("package", ""),
                    int(r.get("joints", 0) or 0),
                    r.get("manufacturer", ""),
                    lib_type,
                    r.get("description", ""),
                    r.get("datasheet", ""),
                    int(r.get("stock", 0) or 0),
                    price_json,
                    int(last_updated),
                ))
                total += 1

            except Exception as exc:
                log.debug("Skipping row lcsc=%s: %s", r.get("lcsc"), exc)
                skipped += 1

        if batch:
            tgt.executemany(insert_sql, batch)
            tgt.commit()
            batch = []
            log.info("  … %d rows imported", total)

    src.close()

    log.info("Building full-text search index …")
    tgt.execute("INSERT INTO components_fts(components_fts) VALUES('rebuild')")
    tgt.commit()

    log.info("Vacuuming target database …")
    tgt.execute("VACUUM")
    tgt.close()

    # Report
    size_mb = Path(target_db).stat().st_size / 1_048_576
    log.info("Done. %d parts imported, %d skipped.", total, skipped)
    log.info("Target database: %s (%.1f MB)", target_db, size_mb)


# ---------------------------------------------------------------------------
# Stats helper
# ---------------------------------------------------------------------------

def print_stats(db_path: str) -> None:
    if not Path(db_path).exists():
        return
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    total    = conn.execute("SELECT COUNT(*) FROM components").fetchone()[0]
    basic    = conn.execute("SELECT COUNT(*) FROM components WHERE library_type='Basic'").fetchone()[0]
    pref     = conn.execute("SELECT COUNT(*) FROM components WHERE library_type='Preferred'").fetchone()[0]
    extended = conn.execute("SELECT COUNT(*) FROM components WHERE library_type='Extended'").fetchone()[0]
    in_stock = conn.execute("SELECT COUNT(*) FROM components WHERE stock > 0").fetchone()[0]
    conn.close()

    log.info("--- Database stats ---")
    log.info("  Total parts : %d", total)
    log.info("  Basic       : %d", basic)
    log.info("  Preferred   : %d", pref)
    log.info("  Extended    : %d", extended)
    log.info("  In stock    : %d", in_stock)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download & convert the JLCPCB parts database for the KiCAD MCP Server."
    )
    parser.add_argument(
        "--output", "-o",
        default=DEFAULT_OUTPUT,
        help=f"Path for the output database (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--cache", "-c",
        default=DEFAULT_CACHE,
        help=f"Path to cache the downloaded source database (default: {DEFAULT_CACHE})",
    )
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="Skip download and re-convert the cached source database",
    )
    parser.add_argument(
        "--stats-only",
        action="store_true",
        help="Print stats for an existing output database and exit",
    )
    args = parser.parse_args()

    if args.stats_only:
        print_stats(args.output)
        return

    if not args.skip_download:
        download_source_db(args.cache)
    else:
        if not Path(args.cache).exists():
            log.error("--skip-download specified but cache file not found: %s", args.cache)
            sys.exit(1)
        log.info("Skipping download, using cached: %s", args.cache)

    convert(args.cache, args.output)
    print_stats(args.output)


if __name__ == "__main__":
    main()
