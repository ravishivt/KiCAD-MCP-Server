# JLCPCB Integration Guide

The KiCAD MCP Server provides fast local search across 611K+ JLCPCB parts plus live
part detail lookups via the JLCPCB API.

> **Note:** This document provides usage examples and workflow guidance. For complete API reference and setup instructions, see [JLCPCB_INTEGRATION.md](JLCPCB_INTEGRATION.md).

The KiCAD MCP Server provides **three complementary approaches** for working with JLCPCB parts:

1. **Local Fast Search** - 611K+ parts via CDFER community mirror (Recommended for most use cases)
2. **Local Symbol Libraries** - Search JLCPCB libraries installed via KiCad PCM _(contributed by [@l3wi](https://github.com/l3wi) in [PR #25](https://github.com/mixelpixx/KiCAD-MCP-Server/pull/25))_
3. **Official JLCPCB API** - Requires enterprise account credentials (Advanced)

All approaches can be used together to give you maximum flexibility.

## Credits

- **Local Symbol Library Search**: Implementation by [@l3wi](https://github.com/l3wi) - [PR #25](https://github.com/mixelpixx/KiCAD-MCP-Server/pull/25)
- **JLCPCB API Integration**: Built on top of the local library foundation

---

## Approach 1: Local Fast Search (Recommended)

### Setup: Populating the Local Database

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

### Searching Parts

#### Free-text query (FTS)

FTS searches across LCSC code, manufacturer part number, manufacturer name, and
pre-built attribute descriptions. About 65% of parts have attribute text derived
from JLCPCB's own parametric data (e.g. `"450mΩ ±25% 600Ω@100MHz 0603 Ferrite Beads ROHS"`).

Good for:
- MPN lookups: `query="AP63203"`
- Component type + specs: `query="ferrite bead 600 ohm 0603"`
- Parametric values: `query="100nF 25V X7R 0402"`

#### Category/subcategory filters

Structural filters that work for all 611K parts regardless of description coverage.
Use `get_jlcpcb_categories` to discover exact names.

Good for:
- Broad category browsing when you don't have specific specs
- Guaranteeing full coverage of a component type

#### Combining both

All filters apply with AND — combine freely to narrow results:

```
search_jlcpcb_parts({
  query: "600 ohm",
  category: "Filters",
  subcategory: "Ferrite Beads",
  library_type: "Basic"
})
```

### Workflow Examples

#### Find a Basic ferrite bead with known impedance

```
search_jlcpcb_parts({
  query: "600Ω@100MHz 200mA",
  library_type: "Basic"
})
```

#### Browse all ferrite beads when specs are flexible

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

#### MPN lookup

```
search_jlcpcb_parts({ query: "AP63203" })
```

#### Confirm a candidate part (live stock/price)

```
get_jlcpcb_part({ lcsc_number: "C1002" })
```

Returns current stock, price breaks, datasheet, and full parameters from the live
JLCPCB API — more up-to-date than the local DB snapshot.

#### Find cheaper alternatives

```
suggest_jlcpcb_alternatives({ lcsc_number: "C25804", limit: 5 })
```

### Cost Optimization

**Prefer Basic parts** — they have $0 assembly fee. Extended parts charge $3 per
unique part number. Filter with `library_type: "Basic"`.

**Check quantity price breaks** — use `get_jlcpcb_part` to see full price tiers
before committing to a part.

---

## Approach 2: Local Symbol Libraries (Good for Offline Use)

### What It Does

- Searches symbol libraries you've installed via KiCad's Plugin and Content Manager (PCM)
- Works with community JLCPCB libraries like `JLCPCB-KiCad-Library`
- No API credentials needed
- Works offline
- Symbols already have LCSC IDs and footprints configured

### Setup

1. **Install JLCPCB Libraries via KiCad PCM:**
   - Open KiCad → Tools → Plugin and Content Manager
   - Search for "JLCPCB" or "JLC"
   - Install libraries like:
     - `JLCPCB-KiCad-Library` (community maintained)
     - `EDA_MCP` (contains common JLCPCB parts)
     - Any other JLCPCB-compatible libraries

2. **Verify Installation:**
   The libraries should appear in KiCad's symbol library table.

### Usage Examples

#### Search for Components

```
search_symbols({
  query: "ESP32",
  library: "JLCPCB"  // Filter to JLCPCB libraries only
})
```

#### Search by LCSC ID

```
search_symbols({
  query: "C2934196"  // Direct LCSC ID search
})
```

#### Get Symbol Details

```
get_symbol_info({
  symbol: "PCM_JLCPCB-MCUs:ESP32-C3"
})
```

### Advantages

- No API credentials required
- Works offline after library installation
- Symbols pre-configured with correct footprints
- Community-maintained and curated
- Instant availability

### Limitations

- Only parts in installed libraries (typically 1k-10k parts)
- No real-time pricing or stock information
- Requires manual library updates via PCM

---

## Approach 3: Official JLCPCB API (Advanced - Enterprise Accounts Only)

### What It Does

- Downloads from the **official JLCPCB API** (requires enterprise account)
- Provides **real-time pricing and stock information**
- Automatic **Basic vs Extended** library type identification (Basic = free assembly)
- Smart suggestions for cheaper/in-stock alternatives
- Package-to-footprint mapping for KiCad

### Setup

#### 1. Get JLCPCB API Credentials

Visit [JLCPCB](https://jlcpcb.com/) and get your API credentials:

1. Log in to your JLCPCB account
2. Go to: **Account → API Management**
3. Click "Create API Key"
4. Save your `appKey` and `appSecret`

#### 2. Configure Environment Variables

Create a `.env` file in the project root:

```
JLCPCB_APP_ID=your_app_id_here
JLCPCB_API_KEY=your_app_key_here
JLCPCB_API_SECRET=your_app_secret_here
```

Or add to your shell profile (`~/.bashrc`, `~/.zshrc`, or `~/.profile`):

```bash
export JLCPCB_APP_ID="your_app_id_here"
export JLCPCB_API_KEY="your_app_key_here"
export JLCPCB_API_SECRET="your_app_secret_here"
```

#### 3. Download the Parts Database

**One-time setup** (takes 5-10 minutes):

```
download_jlcpcb_database({ force: false })
```

This downloads ~100k parts from JLCPCB and creates a local SQLite database (`data/jlcpcb_parts.db`).

### Usage Examples

#### Search for Parts with Specifications

```
search_jlcpcb_parts({
  query: "10k resistor",
  package: "0603",
  library_type: "Basic"  // Only free-assembly parts
})
```

#### Get Part Details with Pricing

```
get_jlcpcb_part({
  lcsc_number: "C58972"
})
```

#### Find Cheaper Alternatives

```
suggest_jlcpcb_alternatives({
  lcsc_number: "C25804",
  limit: 5
})
```

#### Search by Category and Package

```
search_jlcpcb_parts({
  category: "Microcontrollers",
  package: "QFN-32",
  manufacturer: "STM",
  in_stock: true,
  limit: 10
})
```

#### Get Database Statistics

```
get_jlcpcb_database_stats({})
```

---

## Best Practices: Using Both Approaches Together

### Workflow 1: Design with Known Components

**Use Local Libraries:**

```
1. search_symbols({ query: "STM32F103", library: "JLCPCB" })
2. Select component from installed library
3. Component already has correct symbol + footprint + LCSC ID
```

**Why:** Faster, symbols are pre-configured and tested.

### Workflow 2: Find Optimal Part for Cost

**Use Local DB Search:**

```
1. search_jlcpcb_parts({
     query: "10k resistor",
     package: "0603",
     library_type: "Basic"
   })
2. Select cheapest Basic part
3. Use suggested footprint from API
```

**Why:** Ensures lowest cost and maximum stock availability.

### Workflow 3: Explore Unknown Parts

**Start with search, verify with Libraries:**

```
1. search_jlcpcb_parts({ query: "ESP32", limit: 20 })
2. Find interesting part (e.g., C2934196)
3. search_symbols({ query: "C2934196" })
4. If found in library → use library symbol
5. If not found → use API footprint suggestion
```

**Why:** Combines discovery power of DB with quality of curated libraries.

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

### "No symbols found" (Local Libraries)

1. Install JLCPCB libraries via KiCad PCM
2. Verify library is enabled in KiCad symbol library table
3. Restart KiCad MCP server

### "Authentication failed"

1. Verify your API credentials are correct
2. Check JLCPCB account has API access enabled
3. Try regenerating API key/secret in JLCPCB dashboard

---

## Resources

- [JLCPCB API Documentation](https://jlcpcb.com/help/article/JLCPCB-API)
- [JLCPCB Parts Library](https://jlcpcb.com/parts)
- [KiCad Plugin and Content Manager](https://www.kicad.org/help/pcm/)
- [JLCPCB-KiCad-Library (GitHub)](https://github.com/pejot/JLC2KiCad_lib)
