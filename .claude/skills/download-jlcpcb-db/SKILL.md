---
name: download-jlcpcb-db
description: Download and convert the JLCPCB parts database for the KiCAD MCP Server. Use when the user wants to populate or refresh the local JLCPCB parts database, mentions the database is empty, times out during download, or asks about the jlcpcb_parts.db.
argument-hint: [--skip-download] [--stats-only] [--output path]
allowed-tools: Bash
---

Run the JLCPCB database download and conversion script.

The script at `scripts/download_jlcpcb_db.py` downloads a pre-built ~1GB SQLite file from
https://cdfer.github.io/jlcpcb-parts-database/jlcpcb-components.sqlite3 (updated daily from
yaqwsx/jlcparts), then converts it into `data/jlcpcb_parts.db` in the schema this MCP server expects.

## Steps

1. Parse $ARGUMENTS to determine which flags to pass:
   - No args → full download + convert
   - `--skip-download` → re-convert the cached source file without re-downloading
   - `--stats-only` → just print stats for the existing database
   - `--output <path>` → write the output database to a custom path
   - `--cache <path>` → use a custom path for the downloaded source file

2. Run the script with the appropriate flags:

```bash
python3 scripts/download_jlcpcb_db.py $ARGUMENTS
```

3. After the script finishes, report:
   - Whether it succeeded or failed
   - The stats (total parts, Basic/Preferred/Extended counts, in-stock count)
   - The path of the output database
   - Any errors encountered

## Notes

- The download supports resume — if interrupted, re-running continues where it left off
- The cached source file is saved at `data/jlcpcb-components.sqlite3`
- The output database is saved at `data/jlcpcb_parts.db` (default)
- Download is ~1GB; conversion takes a minute or two after download completes
