# JLCPCB Cart API

Unofficial but functional component search API discovered by inspecting JLCPCB's
own shopping cart frontend. No authentication required.

## Endpoints

### Component Search

```
POST https://jlcpcb.com/api/overseas-pcb-order/v1/shoppingCart/smtGood/selectSmtComponentList/v2
Content-Type: application/json
```

**Request body:**

| Field | Type | Description |
|---|---|---|
| `keyword` | string | Free-text search query |
| `currentPage` | int | Page number, 1-based |
| `pageSize` | int | Results per page (tested up to 100) |
| `componentLibraryType` | string | `"base"` = Basic parts only, `"expand"` = Extended parts only; omit for all |
| `stockFlag` | bool | `true` to exclude out-of-stock parts |

**Example:**
```json
{
  "keyword": "10k 0603 1%",
  "currentPage": 1,
  "pageSize": 20,
  "componentLibraryType": "base",
  "stockFlag": true
}
```

**Response:**
```json
{
  "code": 200,
  "data": {
    "componentPageInfo": {
      "total": 122,
      "list": [ ... ]
    }
  }
}
```

Each item in `list` includes:

| Field | Description |
|---|---|
| `componentCode` | LCSC number (e.g. `"C25804"`) |
| `componentModelEn` | Manufacturer part number |
| `componentBrandEn` | Manufacturer name |
| `componentSpecificationEn` | Package (e.g. `"0603"`) |
| `componentLibraryType` | `"base"` (Basic) or `"expand"` (Extended) |
| `describe` | Full description string |
| `stockCount` | Current stock |
| `initialPrice` | Unit price at qty 1 (USD) |
| `componentPrices` | Tier pricing array `[{startNumber, endNumber, productPrice}]` |
| `dataManualUrl` | Datasheet PDF URL |
| `firstSortName` | Top-level category (e.g. `"Chip Resistor - Surface Mount"`) |
| `secondSortName` | Sub-category |
| `attributes` | Array of `{attribute_name_en, attribute_value_name}` specs |
| `assemblyComponentFlag` | Whether part is available for SMT assembly |

---

### Component Detail

```
GET https://cart.jlcpcb.com/shoppingCart/smtGood/getComponentDetail?componentCode=C25804
```

Returns full detail for a single part by LCSC code. Same field structure as search
results, but `componentPrices` is `null` and `initialPrice` is populated instead.

**Example:**
```
GET https://cart.jlcpcb.com/shoppingCart/smtGood/getComponentDetail?componentCode=C25804
```

```json
{
  "code": 200,
  "data": {
    "componentCode": "C25804",
    "componentModelEn": "0603WAF1002T5E",
    "componentBrandEn": "UNI-ROYAL(Uniroyal Elec)",
    "componentSpecificationEn": "0603",
    "describe": "-55℃~+155℃ 100mW 10kΩ 75V Thick Film Resistor ±1% ±100ppm/℃ 0603 ...",
    "stockCount": 26328983,
    "initialPrice": 0.0013,
    "dataManualUrl": "https://www.lcsc.com/datasheet/...",
    "attributes": [
      {"attribute_name_en": "Resistance", "attribute_value_name": "10kΩ"},
      {"attribute_name_en": "Tolerance", "attribute_value_name": "±1%"},
      {"attribute_name_en": "Power(Watts)", "attribute_value_name": "100mW"}
    ]
  }
}
```

---

## What Works

- **Free-text search** — keyword searches across LCSC code, MFR part number, description,
  and category. Natural queries like `"10k 0603 1%"`, `"ESP32"`, `"C25804"` all return
  relevant results.
- **Basic/Extended library filter** — `componentLibraryType: "base"` reliably filters to
  Basic parts only (e.g. 122 results for "10k 0603" vs 282k without filter).
- **In-stock filter** — `stockFlag: true` excludes out-of-stock parts.
- **Pagination** — standard `currentPage` / `pageSize`.
- **Part detail lookup** — detail endpoint returns full specs, attributes, and datasheet URL
  for any LCSC code.
- **Live data** — reflects current JLCPCB inventory and pricing, no caching.

## What Doesn't Work / Limitations

- **No parametric filtering** — cannot filter by resistance=10kΩ, tolerance=1%, voltage=50V,
  etc. as structured parameters. Must use keyword search and filter results client-side.
- **Package filter field is ignored** — passing `componentSpecificationEn: "0603"` as a
  request field has no effect; package must be included in the keyword string.
- **Sort field has no effect** — a `sortType` parameter exists but did not change result
  ordering in testing.
- **No authentication** — these are unauthenticated public endpoints; no way to access
  private/custom parts libraries.
- **No direct category browsing** — category IDs (`firstSortAccessId`) appear in results
  but filtering by them is unreliable; keyword search is more effective.
- **Unofficial API** — no SLA or stability guarantees; JLCPCB could change or remove these
  endpoints at any time without notice.

## Notes on the Official API

JLCPCB has an official developer platform at `api.jlcpcb.com` with JOP (HMAC-SHA256)
signed authentication. The component endpoints on that platform (`open.jlcpcb.com`) accept
valid credentials but return `{"code": 401, "message": "API not exists"}` for all tested
component paths — the actual component endpoint paths are not publicly documented and
appear to require a separate activation step with JLCPCB.

The old partner API (`jlcpcb.com/external/component/getComponentInfos`) consistently
returns 401 Unauthorized regardless of credentials, suggesting those credentials are
tied to the new platform only.
