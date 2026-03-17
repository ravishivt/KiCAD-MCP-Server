# JLCPCB Open API Reference

All three component endpoints live under `https://open.jlcpcb.com` and share the same
HMAC-SHA256 authentication scheme. This document covers authentication and each endpoint
in detail, with working `curl` examples.

---

## Authentication

Every request must carry an `Authorization` header with a signed token.

### Signature algorithm

```
signature_string = METHOD + "\n"
                 + PATH   + "\n"
                 + TIMESTAMP + "\n"
                 + NONCE     + "\n"
                 + BODY      + "\n"

signature = base64( HMAC-SHA256( secret_key, signature_string ) )

Authorization: JOP appid="<APP_ID>",accesskey="<API_KEY>",nonce="<NONCE>",timestamp="<TS>",signature="<SIG>"
```

- `METHOD` — uppercase HTTP verb (`POST`)
- `PATH` — request path only, no host or query string (e.g. `/demo/component/info`)
- `TIMESTAMP` — Unix epoch in **seconds**
- `NONCE` — 32 random alphanumeric characters, unique per request
- `BODY` — raw JSON request body (empty string `""` if no body)

### Shell helper

Save the snippet below and `source` it before running any of the curl examples.

```bash
JLCPCB_APP_ID="your_app_id"
JLCPCB_API_KEY="your_access_key"
JLCPCB_API_SECRET="your_secret_key"

# Usage: AUTH=$(jlcpcb_auth POST /some/path '{"key":"val"}')
jlcpcb_auth() {
  local method="$1"
  local path="$2"
  local body="${3:-}"
  local ts
  ts=$(date +%s)
  local nonce
  nonce=$(LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 32)
  # printf interprets \n correctly; the trailing newline after $body is required
  local sig_str
  sig_str=$(printf '%s\n%s\n%s\n%s\n%s\n' "$method" "$path" "$ts" "$nonce" "$body")
  local sig
  sig=$(printf '%s' "$sig_str" | openssl dgst -sha256 -hmac "$JLCPCB_API_SECRET" -binary | base64)
  printf 'JOP appid="%s",accesskey="%s",nonce="%s",timestamp="%s",signature="%s"' \
    "$JLCPCB_APP_ID" "$JLCPCB_API_KEY" "$nonce" "$ts" "$sig"
}
```

> **Note** `openssl` and standard POSIX utilities are required. Tested on macOS and Linux.

---

## API 1 — Component Information Interface

**Endpoint:** `POST https://open.jlcpcb.com/demo/component/info`

### What it does

Cursor-based paginated dump of the **entire JLCPCB component catalog** with full data per
component: stock, price ranges, categories, library type, manufacturer, datasheet, etc.

This is the right endpoint for a full database download. Use the `lastKey` from each
response as the cursor for the next request. Stop when `lastKey` is absent or null.

**Page size:** 1 000 components per request (fixed, not configurable).

### Request parameters

| Field     | Type   | Required | Description                                             |
|-----------|--------|----------|---------------------------------------------------------|
| `lastKey` | string | No       | Cursor from the previous response. Omit for first page. |

### Response fields (per component in `data.componentInfos`)

| Field           | Type    | Notes                                                              |
|-----------------|---------|--------------------------------------------------------------------|
| `lcscPart`      | string  | LCSC / C-code (e.g. `"C25804"`)                                   |
| `firstCategory` | string  | Top-level category (e.g. `"Resistors"`)                           |
| `secondCategory`| string  | Sub-category (e.g. `"Chip Resistor - Surface Mount"`)             |
| `mfrPart`       | string  | Manufacturer part number                                           |
| `packageInfo`   | string  | Package designation — often `null`, use `getComponentDetailByCode` for reliable package data |
| `solderJoint`   | string  | Number of solder joints (as string)                               |
| `manufacturer`  | string  | Manufacturer name                                                  |
| `libraryType`   | string  | `"base"` = Basic (free assembly), `"expand"` = Extended ($3 setup fee), `"preferred"` = Preferred |
| `description`   | string  | Component description — sometimes empty                           |
| `datasheet`     | string  | Datasheet URL (lcsc.com hosted)                                   |
| `price`         | string  | Price tiers: `"1-9:0.804,10-29:0.585,30-99:0.544,100-:0.505"` (startQty-endQty:unitPrice) |
| `stock`         | integer | Current stock count                                               |

`data.lastKey` — opaque cursor string. Pass as `lastKey` in next request. `null` or absent means last page.

### curl examples

```bash
# First page (no lastKey)
BODY='{}'
AUTH=$(jlcpcb_auth POST /demo/component/info "$BODY")

curl -s -X POST https://open.jlcpcb.com/demo/component/info \
  -H "Authorization: $AUTH" \
  -H "Content-Type: application/json" \
  -d "$BODY" | jq '{
    count: (.data.componentInfos | length),
    last_key_present: (.data.lastKey != null),
    first: .data.componentInfos[0]
  }'
```

```bash
# Next page — paste the lastKey from the previous response
LAST_KEY="POFTQ8ZidxVrP1bNKADY80hi..."
BODY=$(printf '{"lastKey":"%s"}' "$LAST_KEY")
AUTH=$(jlcpcb_auth POST /demo/component/info "$BODY")

curl -s -X POST https://open.jlcpcb.com/demo/component/info \
  -H "Authorization: $AUTH" \
  -H "Content-Type: application/json" \
  -d "$BODY" | jq '.data.componentInfos[0]'
```

### Example response (truncated)

```json
{
  "success": true,
  "code": 200,
  "message": null,
  "data": {
    "componentInfos": [
      {
        "lcscPart": "C1002",
        "firstCategory": "Filters",
        "secondCategory": "Ferrite Beads",
        "mfrPart": "GZ1608D601TF",
        "packageInfo": null,
        "solderJoint": "2",
        "manufacturer": "Sunlord",
        "libraryType": "base",
        "description": "",
        "datasheet": "https://www.lcsc.com/datasheet/..._C1002.pdf",
        "price": "20-3980:0.0122667,4000-11980:0.0106074,12000-79980:0.0098815,80000-:0.0089630",
        "stock": 605304
      }
    ],
    "lastKey": "POFTQ8ZidxVrP1bN..."
  }
}
```

### Use cases

- **Full catalog download** — iterate with `lastKey` until exhausted; import directly to local DB.
- **Incremental refresh** — save `lastKey` after the last page and resume from that cursor on subsequent runs (catalog ordering is stable within a session; treat a full re-crawl as periodic maintenance).

### Known limitations

- `packageInfo` is frequently `null`. Use API 3 (`getComponentDetailByCode`) for reliable package data.
- `description` can be empty for some parts.
- Price is a formatted string, not structured JSON — parse the `start-end:price,...` format.

---

## API 2 — Get Component List

**Endpoint:** `POST https://open.jlcpcb.com/overseas/openapi/component/getComponentLibraryList`

### What it does

Page-number paginated list of all components. Returns **sparse data only**: C-code, model,
and package specification. No stock, price, or categories.

Useful for getting the full set of LCSC codes to then batch-enrich via API 3, but API 1 is
preferable when you need rich data since it provides both the list and full data in one pass.

### Request parameters

| Field         | Type    | Required | Description                          |
|---------------|---------|----------|--------------------------------------|
| `currentPage` | integer | Yes      | Page number, 1-based                 |
| `pageSize`    | integer | Yes      | Results per page, max 1 000          |

### Response fields (per component in `data`)

| Field                    | Type   | Description              |
|--------------------------|--------|--------------------------|
| `componentCode`          | string | LCSC / C-code            |
| `componentModel`         | string | Manufacturer part number |
| `componentSpecification` | string | Package designation      |

### curl example

```bash
BODY='{"currentPage":1,"pageSize":5}'
AUTH=$(jlcpcb_auth POST /overseas/openapi/component/getComponentLibraryList "$BODY")

curl -s -X POST \
  https://open.jlcpcb.com/overseas/openapi/component/getComponentLibraryList \
  -H "Authorization: $AUTH" \
  -H "Content-Type: application/json" \
  -d "$BODY" | jq '.data'
```

### Example response

```json
{
  "code": 200,
  "message": "success",
  "data": [
    {
      "componentCode": "C8734",
      "componentModel": "STM32F103C8T6",
      "componentSpecification": "LQFP-48"
    },
    {
      "componentCode": "C82899",
      "componentModel": "ESP32-WROOM-32",
      "componentSpecification": "SMD-38"
    }
  ]
}
```

### Use cases

- Enumerate all LCSC codes to detect new parts since last sync.
- Feed a list of codes into API 3 for bulk detail enrichment.

---

## API 3 — Query Component Detail Data

**Endpoint:** `POST https://open.jlcpcb.com/overseas/openapi/component/getComponentDetailByCode`

### What it does

Batch lookup of full component details by C-code. Accepts up to **1 000 codes per request**.
Returns the richest response of all three endpoints: structured price ranges, parameters,
stock, RoHS/ECCN, datasheet URL, assembly flags.

This is the primary endpoint for live per-part lookups.

### Request parameters

| Field            | Type     | Required | Description                                              |
|------------------|----------|----------|----------------------------------------------------------|
| `componentCodes` | string[] | Yes      | Array of C-codes, max 1 000 (e.g. `["C25804","C8734"]`) |

### Response fields (per component in `data`)

| Field                  | Type    | Description                                                        |
|------------------------|---------|--------------------------------------------------------------------|
| `componentCode`        | string  | LCSC / C-code                                                      |
| `componentModel`       | string  | Manufacturer part number                                           |
| `componentSpecification`| string | Package (e.g. `"0603"`, `"LQFP-48"`)                             |
| `firstTypeName`        | string  | Top-level category                                                 |
| `secondTypeName`       | string  | Sub-category                                                       |
| `libraryType`          | string  | `"base"` / `"expand"` / `"preferred"`                             |
| `description`          | string  | Full component description                                         |
| `datasheetUrl`         | string  | Datasheet file access ID (not a direct URL)                       |
| `dataManualUrl`        | string  | Direct datasheet PDF URL                                           |
| `solderJointCount`     | integer | Number of solder joints                                            |
| `priceRanges`          | array   | Structured price breaks (see below)                               |
| `stockCount`           | integer | Current stock                                                      |
| `parameters`           | array   | Key/value parameter list (see below)                              |
| `assemblyComponentFlag`| boolean | `true` if this is a fabricated/assembly component                 |
| `eccnCode`             | string  | Export control classification (e.g. `"5A992C"`)                  |
| `rohsFlag`             | boolean | RoHS compliant                                                     |

**`priceRanges` structure:**
```json
[
  { "startQuantity": 1,   "endQuantity": 9,   "unitPrice": 5.8069 },
  { "startQuantity": 10,  "endQuantity": 29,  "unitPrice": 4.9495 },
  { "startQuantity": 1300,"endQuantity": -1,  "unitPrice": 3.5817 }
]
```
`endQuantity: -1` means open-ended (no upper bound).

**`parameters` structure:**
```json
[
  { "parameterName": "Frequency",        "parameterValue": "2.4GHz" },
  { "parameterName": "Voltage - Supply", "parameterValue": "3V~3.6V" }
]
```

### curl examples

```bash
# Single part lookup
BODY='{"componentCodes":["C2980300"]}'
AUTH=$(jlcpcb_auth POST /overseas/openapi/component/getComponentDetailByCode "$BODY")

curl -s -X POST \
  https://open.jlcpcb.com/overseas/openapi/component/getComponentDetailByCode \
  -H "Authorization: $AUTH" \
  -H "Content-Type: application/json" \
  -d "$BODY" | jq '.data[0] | {
    lcsc: .componentCode,
    model: .componentModel,
    package: .componentSpecification,
    library: .libraryType,
    stock: .stockCount,
    price_1: .priceRanges[0]
  }'
```

```bash
# Batch lookup — up to 1000 codes per request
BODY='{"componentCodes":["C25804","C8734","C82899","C2980300"]}'
AUTH=$(jlcpcb_auth POST /overseas/openapi/component/getComponentDetailByCode "$BODY")

curl -s -X POST \
  https://open.jlcpcb.com/overseas/openapi/component/getComponentDetailByCode \
  -H "Authorization: $AUTH" \
  -H "Content-Type: application/json" \
  -d "$BODY" | jq '[.data[] | {lcsc: .componentCode, stock: .stockCount, price_1: .priceRanges[0].unitPrice}]'
```

### Example response (C2980300)

```json
{
  "code": 200,
  "message": null,
  "data": [
    {
      "componentCode": "C2980300",
      "componentModel": "ESP32-S3-WROOM-1U-N8R8",
      "componentSpecification": "SMD,19.2x18mm",
      "firstTypeName": "IoT/Communication Modules",
      "secondTypeName": "WiFi Modules",
      "libraryType": "expand",
      "description": "-103.5dBm -40℃~+65℃ 2.4GHz 20.5dBm 355mA 3V~3.6V ...",
      "dataManualUrl": "https://wmsc.lcsc.com/wmsc/upload/file/pdf/v2/lcsc/..._C2980300.pdf",
      "solderJointCount": 49,
      "priceRanges": [
        { "startQuantity": 1,    "endQuantity": 9,    "unitPrice": 5.8069 },
        { "startQuantity": 10,   "endQuantity": 29,   "unitPrice": 4.9495 },
        { "startQuantity": 30,   "endQuantity": 99,   "unitPrice": 4.4424 },
        { "startQuantity": 100,  "endQuantity": 649,  "unitPrice": 3.9273 },
        { "startQuantity": 650,  "endQuantity": 1299, "unitPrice": 3.6883 },
        { "startQuantity": 1300, "endQuantity": -1,   "unitPrice": 3.5817 }
      ],
      "stockCount": 2742,
      "parameters": [
        { "parameterName": "Frequency",        "parameterValue": "2.4GHz" },
        { "parameterName": "Voltage - Supply", "parameterValue": "3V~3.6V" },
        { "parameterName": "Wireless Standard","parameterValue": "Bluetooth5.0" }
      ],
      "assemblyComponentFlag": false,
      "eccnCode": "5A992C",
      "rohsFlag": true
    }
  ]
}
```

### Use cases

- **Live part lookup** by known C-code — stock, price, full spec.
- **Enriching search results** — search local DB for candidates, then batch-fetch live stock/price for top results.
- **BOM validation** — verify stock and pricing for all parts in a design before ordering.

---

## Comparison

| | API 1 `/demo/component/info` | API 2 `getComponentLibraryList` | API 3 `getComponentDetailByCode` |
|---|---|---|---|
| **Pagination** | Cursor (`lastKey`) | Page number | N/A (direct lookup) |
| **Page size** | 1 000 (fixed) | Up to 1 000 | Up to 1 000 codes |
| **Stock** | ✅ | ❌ | ✅ |
| **Price** | ✅ (range string) | ❌ | ✅ (structured) |
| **Categories** | ✅ | ❌ | ✅ |
| **Parameters** | ❌ | ❌ | ✅ |
| **Package** | ⚠️ often null | ✅ | ✅ |
| **Description** | ⚠️ sometimes empty | ❌ | ✅ |
| **RoHS / ECCN** | ❌ | ❌ | ✅ |
| **Best for** | Full catalog download | Code enumeration | Live lookups & enrichment |

---

## Error codes

| HTTP / code | Meaning |
|-------------|---------|
| 200 / 200 | Success |
| 200 / 500 | Server error — usually means wrong `Content-Type`, missing body, or bad auth |
| 401 | Unauthorized — credentials missing or invalid |
| 403 | Forbidden — account does not have access to this endpoint |
| 429 | Rate limited — back off and retry |
| 400 | Bad request — missing required field or wrong content-type |

> **Important:** API 1 returns HTTP 200 with `"code": 500` when called without
> `Content-Type: application/json` + a JSON body. Always set the header even for an
> empty body (`{}`).

---

## Credentials setup

```bash
# .env file (project root)
JLCPCB_APP_ID=your_app_id_here
JLCPCB_API_KEY=your_access_key_here
JLCPCB_API_SECRET=your_secret_key_here
```

Credentials are read automatically by `JLCPCBClient` from environment variables.
Obtain them from your JLCPCB account → **API Management** → **Create API Key**.
