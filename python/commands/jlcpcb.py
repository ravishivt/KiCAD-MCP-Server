"""
JLCPCB API client for fetching parts data

Handles authentication and downloading the JLCPCB parts library
for integration with KiCAD component selection.

Three endpoints are used:
  /demo/component/info                              - Cursor-based bulk download (rich data)
  /overseas/openapi/component/getComponentLibraryList    - Page-based list (sparse, code/model/spec only)
  /overseas/openapi/component/getComponentDetailByCode   - Batch lookup by C-code (full detail)
"""

import os
import logging
import requests
import time
import hmac
import hashlib
import secrets
import string
import base64
import json
from typing import Optional, Dict, List, Callable
from pathlib import Path

logger = logging.getLogger('kicad_interface')


class JLCPCBClient:
    """
    Client for JLCPCB Open API (open.jlcpcb.com)

    Handles HMAC-SHA256 signature-based authentication and all three
    component-related endpoints of the JLCPCB official open API.
    """

    BASE_URL = "https://open.jlcpcb.com"

    def __init__(self, app_id: Optional[str] = None, access_key: Optional[str] = None, secret_key: Optional[str] = None):
        """
        Initialize JLCPCB API client

        Args:
            app_id: JLCPCB App ID (or reads from JLCPCB_APP_ID env var)
            access_key: JLCPCB Access Key (or reads from JLCPCB_API_KEY env var)
            secret_key: JLCPCB Secret Key (or reads from JLCPCB_API_SECRET env var)
        """
        self.app_id = app_id or os.getenv('JLCPCB_APP_ID')
        self.access_key = access_key or os.getenv('JLCPCB_API_KEY')
        self.secret_key = secret_key or os.getenv('JLCPCB_API_SECRET')

        if not self.app_id or not self.access_key or not self.secret_key:
            logger.warning("JLCPCB API credentials not found. Set JLCPCB_APP_ID, JLCPCB_API_KEY, and JLCPCB_API_SECRET environment variables.")

    @staticmethod
    def _generate_nonce() -> str:
        """Generate a 32-character random nonce"""
        chars = string.ascii_letters + string.digits
        return ''.join(secrets.choice(chars) for _ in range(32))

    def _build_signature_string(self, method: str, path: str, timestamp: int, nonce: str, body: str) -> str:
        """
        Build the signature string according to JLCPCB spec:
          <HTTP Method>\\n<Request Path>\\n<Timestamp>\\n<Nonce>\\n<Request Body>\\n
        """
        return f"{method}\n{path}\n{timestamp}\n{nonce}\n{body}\n"

    def _sign(self, signature_string: str) -> str:
        """Sign with HMAC-SHA256, return Base64-encoded result"""
        signature_bytes = hmac.new(
            self.secret_key.encode('utf-8'),
            signature_string.encode('utf-8'),
            hashlib.sha256
        ).digest()
        return base64.b64encode(signature_bytes).decode('utf-8')

    def _get_auth_header(self, method: str, path: str, body: str = "") -> str:
        """
        Generate the Authorization header for JLCPCB API requests.

        Args:
            method: HTTP method (GET, POST, etc.)
            path: Request path (e.g. /demo/component/info)
            body: Request body JSON string (empty string for GET or bodyless POST)

        Returns:
            Authorization header value string
        """
        if not self.app_id or not self.access_key or not self.secret_key:
            raise Exception("JLCPCB API credentials not configured. Set JLCPCB_APP_ID, JLCPCB_API_KEY, and JLCPCB_API_SECRET.")

        nonce = self._generate_nonce()
        timestamp = int(time.time())

        sig_str = self._build_signature_string(method, path, timestamp, nonce, body)
        signature = self._sign(sig_str)

        return f'JOP appid="{self.app_id}",accesskey="{self.access_key}",nonce="{nonce}",timestamp="{timestamp}",signature="{signature}"'

    # -------------------------------------------------------------------------
    # /demo/component/info  (cursor-based, rich data)
    # -------------------------------------------------------------------------

    def fetch_component_info_page(self, last_key: Optional[str] = None) -> Dict:
        """
        Fetch one page from the Component Information endpoint.

        Uses cursor-based pagination. Returns rich data per component:
        stock, price (range string), categories, libraryType, manufacturer, etc.

        Args:
            last_key: Cursor returned by the previous page (None for first page)

        Returns:
            Dict with keys:
              'items'    - list of component dicts for this page
              'last_key' - cursor string for next page (None when exhausted)
        """
        path = "/demo/component/info"
        payload = {}
        if last_key:
            payload["lastKey"] = last_key
        body_str = json.dumps(payload)
        auth_header = self._get_auth_header("POST", path, body_str)

        try:
            response = requests.post(
                f"{self.BASE_URL}{path}",
                headers={"Authorization": auth_header, "Content-Type": "application/json"},
                data=body_str,
                timeout=60,
            )
            response.raise_for_status()
            data = response.json()

            if not data.get("success") and data.get("code") != 200:
                raise Exception(f"API error (code {data.get('code')}): {data.get('message', 'Unknown error')}")

            page_data = data.get("data") or {}
            return {
                "items": page_data.get("componentInfos", []),
                "last_key": page_data.get("lastKey"),
            }
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to fetch component info page: {e}")
            raise Exception(f"JLCPCB API request failed: {e}")

    def download_full_database(
        self,
        on_page: Optional[Callable[[List[Dict]], None]] = None,
        callback: Optional[Callable[[int, str], None]] = None,
    ) -> List[Dict]:
        """
        Download the entire JLCPCB component catalog via /demo/component/info.

        Uses cursor-based pagination (1 000 items/page). Each item includes:
        lcscPart, firstCategory, secondCategory, mfrPart, packageInfo,
        solderJoint, manufacturer, libraryType, description, datasheet,
        price (range string), stock.

        Args:
            on_page: If provided, called with each page's item list instead of
                     accumulating. Use this for streaming imports to avoid holding
                     the full catalog in memory.
            callback: Optional progress callback(total_so_far, status_message)

        Returns:
            List of all items when on_page is None; empty list otherwise.
        """
        all_parts: List[Dict] = []
        last_key: Optional[str] = None
        total = 0
        page = 0

        logger.info("Starting full JLCPCB catalog download via /demo/component/info ...")

        while True:
            page += 1
            try:
                result = self.fetch_component_info_page(last_key)
                items = result["items"]
                last_key = result["last_key"]

                if not items:
                    break

                total += len(items)

                if on_page:
                    on_page(items)
                else:
                    all_parts.extend(items)

                msg = f"Downloaded {total:,} parts (page {page})..."
                if callback:
                    callback(total, msg)
                else:
                    logger.info(msg)

                if not last_key:
                    break

                time.sleep(0.1)

            except Exception as e:
                logger.error(f"Error at page {page}: {e}")
                if total > 0:
                    logger.warning(f"Partial download: {total:,} parts retrieved before error")
                    break
                else:
                    raise

        logger.info(f"Download complete: {total:,} parts retrieved in {page} pages")
        return all_parts

    # -------------------------------------------------------------------------
    # /overseas/openapi/component/getComponentLibraryList  (page-based, sparse)
    # -------------------------------------------------------------------------

    def fetch_parts_page(self, page: int = 1, page_size: int = 1000) -> List[Dict]:
        """
        Fetch one page from the Component Library List endpoint.

        Returns sparse data only: componentCode, componentModel, componentSpecification.
        Prefer fetch_component_info_page() when you need stock/price/categories.

        Args:
            page: Page number (1-based)
            page_size: Results per page (max 1000)

        Returns:
            List of dicts with keys: componentCode, componentModel, componentSpecification
        """
        path = "/overseas/openapi/component/getComponentLibraryList"
        payload = {"currentPage": page, "pageSize": page_size}
        body_str = json.dumps(payload)
        auth_header = self._get_auth_header("POST", path, body_str)

        try:
            response = requests.post(
                f"{self.BASE_URL}{path}",
                headers={"Authorization": auth_header, "Content-Type": "application/json"},
                data=body_str,
                timeout=60,
            )
            response.raise_for_status()
            data = response.json()

            if data.get('code') != 200:
                raise Exception(f"API error (code {data.get('code')}): {data.get('message', 'Unknown error')}")

            return data.get('data', [])

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to fetch parts page: {e}")
            raise Exception(f"JLCPCB API request failed: {e}")

    # -------------------------------------------------------------------------
    # /overseas/openapi/component/getComponentDetailByCode  (batch lookup)
    # -------------------------------------------------------------------------

    def get_parts_batch(self, lcsc_numbers: List[str]) -> List[Dict]:
        """
        Get full details for up to 1000 parts by C-code.

        Returns per part: componentCode, componentModel, componentSpecification,
        firstTypeName, secondTypeName, libraryType, description, datasheetUrl,
        solderJointCount, priceRanges, stockCount, parameters, rohsFlag, eccnCode,
        assemblyComponentFlag, dataManualUrl.

        Args:
            lcsc_numbers: List of LCSC codes (e.g. ["C25804", "C8734"])

        Returns:
            List of component detail dicts (order not guaranteed to match input)
        """
        if not lcsc_numbers:
            return []

        path = "/overseas/openapi/component/getComponentDetailByCode"
        payload = {"componentCodes": lcsc_numbers[:1000]}
        body_str = json.dumps(payload)
        auth_header = self._get_auth_header("POST", path, body_str)

        try:
            response = requests.post(
                f"{self.BASE_URL}{path}",
                headers={"Authorization": auth_header, "Content-Type": "application/json"},
                data=body_str,
                timeout=60,
            )
            response.raise_for_status()
            data = response.json()

            if data.get('code') != 200:
                raise Exception(f"API error (code {data.get('code')}): {data.get('message', 'Unknown error')}")

            return data.get('data', [])

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to fetch part details: {e}")
            raise Exception(f"JLCPCB API request failed: {e}")

    def get_part_by_lcsc(self, lcsc_number: str) -> Optional[Dict]:
        """
        Get full details for a single part by LCSC number.

        Args:
            lcsc_number: LCSC part number ("C25804" or "25804")

        Returns:
            Component detail dict or None if not found
        """
        lcsc = lcsc_number.strip()
        if not lcsc.upper().startswith("C"):
            lcsc = f"C{lcsc}"

        results = self.get_parts_batch([lcsc])
        return results[0] if results else None


def test_jlcpcb_connection(app_id=None, access_key=None, secret_key=None) -> bool:
    """
    Test JLCPCB Open API connection using getComponentDetailByCode.

    Returns:
        True if connection successful, False otherwise
    """
    try:
        client = JLCPCBClient(app_id, access_key, secret_key)
        parts = client.get_parts_batch(["C25804"])
        logger.info(f"JLCPCB API connection test successful - got {len(parts)} parts")
        return True
    except Exception as e:
        logger.error(f"JLCPCB API connection test failed: {e}")
        return False


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)

    print("Testing JLCPCB Open API connection (open.jlcpcb.com)...")
    if test_jlcpcb_connection():
        print("✓ Connection successful!")

        client = JLCPCBClient()

        print("\nFetching first page via /demo/component/info...")
        result = client.fetch_component_info_page()
        items = result["items"]
        print(f"✓ {len(items)} items, lastKey present: {bool(result['last_key'])}")
        if items:
            part = items[0]
            print(f"  LCSC: {part.get('lcscPart')}")
            print(f"  Model: {part.get('mfrPart')}")
            print(f"  Category: {part.get('firstCategory')} / {part.get('secondCategory')}")
            print(f"  Library: {part.get('libraryType')}  Stock: {part.get('stock')}")
            print(f"  Price: {part.get('price')}")

        print("\nLooking up C25804 via getComponentDetailByCode...")
        detail = client.get_part_by_lcsc("C25804")
        if detail:
            print(f"  {detail.get('componentCode')}: {detail.get('componentModel')} "
                  f"[{detail.get('libraryType')}] stock={detail.get('stockCount')}")
    else:
        print("✗ Connection failed. Check JLCPCB_APP_ID, JLCPCB_API_KEY, JLCPCB_API_SECRET.")
