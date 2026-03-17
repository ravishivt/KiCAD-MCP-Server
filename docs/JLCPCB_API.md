# JLCPCB Open API — Quick Reference

## Credentials

| Field | Value |
|---|---|
| App ID | `<your-app-id>` |
| Access Key | `<your-access-key>` |
| Secret Key | `<your-secret-key>` |

Store these in environment variables — never commit them:

```bash
export JLCPCB_APP_ID="<your-app-id>"
export JLCPCB_ACCESS_KEY="<your-access-key>"
export JLCPCB_SECRET_KEY="<your-secret-key>"
```

---

## Base URL

```
https://open.jlcpcb.com
```

---

## Authentication

Every request requires a signed `Authorization` header. The scheme is `JOP`.

### Signature Algorithm

Build a string from five lines (each ending with `\n`):

```
<HTTP_METHOD>\n
<REQUEST_PATH>\n
<UNIX_TIMESTAMP>\n
<NONCE>\n
<REQUEST_BODY>\n
```

- **HTTP_METHOD**: uppercase (`GET`, `POST`, …)
- **REQUEST_PATH**: path + query string, no domain
- **UNIX_TIMESTAMP**: seconds since epoch
- **NONCE**: 32-character random alphanumeric string
- **REQUEST_BODY**: raw JSON for POST; empty string for GET

Sign with **HMAC-SHA256** using your Secret Key, then **Base64-encode** the result.

### Authorization Header Format

```
Authorization: JOP appid="<APP_ID>",accesskey="<ACCESS_KEY>",nonce="<NONCE>",timestamp="<TIMESTAMP>",signature="<SIGNATURE>"
```

The entire value must be on a single line.

### Python Helper

```python
import hmac, hashlib, base64, os, random, string, time, json

APP_ID     = os.environ["JLCPCB_APP_ID"]
ACCESS_KEY = os.environ["JLCPCB_ACCESS_KEY"]
SECRET_KEY = os.environ["JLCPCB_SECRET_KEY"]

def generate_nonce(length=32):
    return "".join(random.choices(string.ascii_letters + string.digits, k=length))

def build_auth_header(method: str, path: str, body: str) -> dict:
    nonce     = generate_nonce()
    timestamp = int(time.time())
    to_sign   = f"{method}\n{path}\n{timestamp}\n{nonce}\n{body}\n"
    signature = base64.b64encode(
        hmac.new(SECRET_KEY.encode(), to_sign.encode(), hashlib.sha256).digest()
    ).decode()
    auth = (
        f'JOP appid="{APP_ID}",'
        f'accesskey="{ACCESS_KEY}",'
        f'nonce="{nonce}",'
        f'timestamp="{timestamp}",'
        f'signature="{signature}"'
    )
    return {"Authorization": auth, "Content-Type": "application/json"}
```

---

## Endpoints

### Get Component List

Paginated query of the public component library.

| | |
|---|---|
| **Method** | `POST` |
| **Path** | `/overseas/openapi/component/getComponentLibraryList` |

**Request body**

```json
{
  "currentPage": 1,
  "pageSize": 100
}
```

| Parameter | Type | Required | Notes |
|---|---|---|---|
| `currentPage` | Integer | Yes | Starts at `1` |
| `pageSize` | Integer | Yes | Default `30`, max `1000` |

**Sample curl (bash, no extra dependencies)**

Uses `openssl` (available on macOS and most Linux distros) to compute the signature.

```bash
# Credentials (or export these from your environment)
APP_ID="<your-app-id>"
ACCESS_KEY="<your-access-key>"
SECRET_KEY="<your-secret-key>"

# Request details
METHOD="POST"
REQ_PATH="/overseas/openapi/component/getComponentLibraryList"
BODY='{"currentPage": 1, "pageSize": 100}'

# Generate nonce and timestamp
NONCE=$(LC_ALL=C tr -dc 'A-Za-z0-9' < /dev/urandom | head -c 32)
TIMESTAMP=$(date +%s)

# Build string-to-sign and compute HMAC-SHA256 signature
SIGNATURE=$(printf "%s\n%s\n%s\n%s\n%s\n" "$METHOD" "$REQ_PATH" "$TIMESTAMP" "$NONCE" "$BODY" \
  | openssl dgst -sha256 -hmac "$SECRET_KEY" -binary \
  | base64 | tr -d '\n')

# Send request
curl -X POST "https://open.jlcpcb.com${REQ_PATH}" \
  -H "Content-Type: application/json" \
  -H "Authorization: JOP appid=\"${APP_ID}\",accesskey=\"${ACCESS_KEY}\",nonce=\"${NONCE}\",timestamp=\"${TIMESTAMP}\",signature=\"${SIGNATURE}\"" \
  -d "$BODY"
```

**Example (Python)**

```python
import urllib.request

def get_component_page(page: int, page_size: int) -> dict:
    path = "/overseas/openapi/component/getComponentLibraryList"
    body = json.dumps({"currentPage": page, "pageSize": page_size})
    headers = build_auth_header("POST", path, body)
    req = urllib.request.Request(
        "https://open.jlcpcb.com" + path,
        data=body.encode(),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())
```

**Response**

```json
{
  "code": 200,
  "message": "success",
  "data": [
    {
      "componentCode": "C8734",
      "componentModel": "STM32F103C8T6",
      "componentSpecification": "LQFP-48"
    }
  ]
}
```

| Field | Description |
|---|---|
| `componentCode` | JLCPCB C-number (e.g. `C8734`) |
| `componentModel` | Part number / model name |
| `componentSpecification` | Package / footprint |

**Status codes**

| Code | Meaning |
|---|---|
| `200` | Success |
| `401` | Unauthorized (bad/missing signature) |
| `403` | Forbidden |
| `429` | Rate limited |
| `4xx` | Parameter error |
| `500` | Server error |

---

## Pagination Pattern

To fetch the first N components reliably:

```python
def fetch_components(total: int, page_size: int = 100) -> list:
    results = []
    page = 1
    while len(results) < total:
        data = get_component_page(page, page_size).get("data", [])
        if not data:
            break  # no more pages
        results.extend(data)
        page += 1
    return results[:total]
```

Verified: fetching 500 components across 5 pages of 100 returns zero duplicates.
