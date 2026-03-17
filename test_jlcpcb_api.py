#!/usr/bin/env python3
"""Test JLCPCB API - fetch first 500 components and verify pagination."""

import hmac
import hashlib
import base64
import random
import string
import time
import json
import urllib.request
import urllib.error

APP_ID = "556705688793325570"
ACCESS_KEY = "3397935bec234256941abe69208785f4"
SECRET_KEY = "liKvhO0MyemV7Nb7qfVJawXWw08tBUpw"

BASE_URL = "https://open.jlcpcb.com"
COMPONENT_PATH = "/overseas/openapi/component/getComponentLibraryList"


def generate_nonce(length=32):
    chars = string.ascii_letters + string.digits
    return "".join(random.choices(chars, k=length))


def sign(string_to_sign: str, secret_key: str) -> str:
    mac = hmac.new(secret_key.encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha256)
    return base64.b64encode(mac.digest()).decode("utf-8")


def build_auth_header(method: str, path: str, body: str) -> dict:
    nonce = generate_nonce()
    timestamp = int(time.time())
    string_to_sign = f"{method}\n{path}\n{timestamp}\n{nonce}\n{body}\n"
    signature = sign(string_to_sign, SECRET_KEY)
    auth = (
        f'JOP appid="{APP_ID}",'
        f'accesskey="{ACCESS_KEY}",'
        f'nonce="{nonce}",'
        f'timestamp="{timestamp}",'
        f'signature="{signature}"'
    )
    return {
        "Authorization": auth,
        "Content-Type": "application/json",
    }


def get_component_page(page: int, page_size: int) -> dict:
    body = json.dumps({"currentPage": page, "pageSize": page_size})
    headers = build_auth_header("POST", COMPONENT_PATH, body)
    url = BASE_URL + COMPONENT_PATH
    req = urllib.request.Request(url, data=body.encode("utf-8"), headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main():
    all_components = []
    page_size = 100  # fetch in chunks of 100 to exercise pagination
    total_needed = 500
    pages_needed = total_needed // page_size  # 5 pages

    print(f"Fetching {total_needed} components in {pages_needed} pages of {page_size} each...\n")

    for page in range(1, pages_needed + 1):
        print(f"  Page {page}/{pages_needed}...", end=" ", flush=True)
        try:
            result = get_component_page(page, page_size)
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            print(f"HTTP {e.code}: {body}")
            return
        except Exception as e:
            print(f"Error: {e}")
            return

        code = result.get("code")
        if code != 200:
            print(f"API error: {result}")
            return

        data = result.get("data", [])
        print(f"got {len(data)} components")
        all_components.extend(data)

    print(f"\nTotal components fetched: {len(all_components)}")

    # Verify pagination: check for duplicates by componentCode
    codes = [c.get("componentCode") for c in all_components if c.get("componentCode")]
    unique_codes = set(codes)
    duplicates = len(codes) - len(unique_codes)

    print(f"Unique component codes: {len(unique_codes)}")
    if duplicates:
        print(f"WARNING: {duplicates} duplicate entries found (possible pagination overlap)")
    else:
        print("No duplicates - pagination looks correct")

    # Sample output
    print("\nFirst 5 components:")
    for c in all_components[:5]:
        print(f"  {c.get('componentCode'):10s}  {c.get('componentModel', ''):30s}  {c.get('componentSpecification', '')}")

    print("\nLast 5 components:")
    for c in all_components[-5:]:
        print(f"  {c.get('componentCode'):10s}  {c.get('componentModel', ''):30s}  {c.get('componentSpecification', '')}")


if __name__ == "__main__":
    main()
