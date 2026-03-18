# JLCPCB Integration Guide

The KiCAD MCP Server provides fast local search across 611K+ JLCPCB parts plus live
part detail lookups via the JLCPCB API.

---

## Setup: Populating the Local Database

Run the `/download-jlcpcb-db` skill, or directly:

```bash
python3 scripts/download_jlcpcb_db.py
```

This downloads the [CDFER community mirror](https://cdfer.github.io/jlcpcb-parts-database/)
(~1 GB, updated daily from yaqwsx/jlcparts), converts it into `data/jlcpcb_parts.db`, and
builds a full-text search index. Takes 1–2 minutes after the download completes.

**No API credentials required for setup.**

If you already have the source file cached, re-convert without re-downloading:

```bash
python3 scripts/download_jlcpcb_db.py --skip-download
```

---

## Searching Parts

### Free-text query (FTS)

FTS searches across LCSC code, manufacturer part number, manufacturer name, and
pre-built attribute descriptions. About 65% of parts have attribute text derived
from JLCPCB's own parametric data (e.g. `"450mΩ ±25% 600Ω@100MHz 0603 Ferrite Beads ROHS"`).

Good for:
- MPN lookups: `query="AP63203"`
- Component type + specs: `query="ferrite bead 600 ohm 0603"`
- Parametric values: `query="100nF 25V X7R 0402"`

### Category/subcategory filters

Structural filters that work for all 611K parts regardless of description coverage.
Use `get_jlcpcb_categories` to discover exact names.

Good for:
- Broad category browsing when you don't have specific specs
- Guaranteeing full coverage of a component type

### Combining both

All filters apply with AND — combine freely to narrow results:

```
search_jlcpcb_parts({
  query: "600 ohm",
  category: "Filters",
  subcategory: "Ferrite Beads",
  library_type: "Basic"
})
```

---

## Workflow Examples

### Find a Basic ferrite bead with known impedance

```
search_jlcpcb_parts({
  query: "600Ω@100MHz 200mA",
  library_type: "Basic"
})
```

### Browse all ferrite beads when specs are flexible

```
1. get_jlcpcb_categories(category="Filters")
   → see subcategories including "Ferrite Beads"

2. search_jlcpcb_parts({
     category: "Filters",
     subcategory: "Ferrite Beads",
     library_type: "Basic",
     limit: 20
   })
```

### MPN lookup

```
search_jlcpcb_parts({ query: "AP63203" })
```

### Confirm a candidate part (live stock/price)

```
get_jlcpcb_part({ lcsc_number: "C1002" })
```

Returns current stock, price breaks, datasheet, and full parameters from the live
JLCPCB API — more up-to-date than the local DB snapshot.

### Find cheaper alternatives

```
suggest_jlcpcb_alternatives({ lcsc_number: "C25804", limit: 5 })
```

---

## Cost Optimization

**Prefer Basic parts** — they have $0 assembly fee. Extended parts charge $3 per
unique part number. Filter with `library_type: "Basic"`.

**Check quantity price breaks** — use `get_jlcpcb_part` to see full price tiers
before committing to a part.

---

## Troubleshooting

### "Database not found or empty"

Run the setup script:
```bash
python3 scripts/download_jlcpcb_db.py
```

### Search returns no results

- Try broadening: remove package or subcategory filters
- Check spelling of category/subcategory via `get_jlcpcb_categories`
- For parametric searches, use the exact notation from JLCPCB (e.g. `600Ω@100MHz` not `600 ohm at 100mhz`)

### `get_jlcpcb_part` fails

This calls the live JLCPCB API. Check that `JLCPCB_APP_ID`, `JLCPCB_API_KEY`, and
`JLCPCB_API_SECRET` are set in `.env` or your environment.
