"""
JLCPCB API client for fetching parts data

Handles authentication and downloading the JLCPCB parts library
for integration with KiCAD component selection.
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

    Handles HMAC-SHA256 signature-based authentication and fetching
    the complete parts library from JLCPCB's official open API.
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
        Build the signature string according to JLCPCB spec

        Format:
        <HTTP Method>\n
        <Request Path>\n
        <Timestamp>\n
        <Nonce>\n
        <Request Body>\n

        Args:
            method: HTTP method (GET, POST, etc.)
            path: Request path with query params
            timestamp: Unix timestamp in seconds
            nonce: 32-character random string
            body: Request body (empty string for GET)

        Returns:
            Signature string
        """
        return f"{method}\n{path}\n{timestamp}\n{nonce}\n{body}\n"

    def _sign(self, signature_string: str) -> str:
        """
        Sign the signature string with HMAC-SHA256

        Args:
            signature_string: The string to sign

        Returns:
            Base64-encoded signature
        """
        signature_bytes = hmac.new(
            self.secret_key.encode('utf-8'),
            signature_string.encode('utf-8'),
            hashlib.sha256
        ).digest()
        return base64.b64encode(signature_bytes).decode('utf-8')

    def _get_auth_header(self, method: str, path: str, body: str = "") -> str:
        """
        Generate the Authorization header for JLCPCB API requests

        Args:
            method: HTTP method (GET, POST, etc.)
            path: Request path with query params
            body: Request body JSON string (empty for GET)

        Returns:
            Authorization header value
        """
        if not self.app_id or not self.access_key or not self.secret_key:
            raise Exception("JLCPCB API credentials not configured. Please set JLCPCB_APP_ID, JLCPCB_API_KEY, and JLCPCB_API_SECRET environment variables.")

        nonce = self._generate_nonce()
        timestamp = int(time.time())

        signature_string = self._build_signature_string(method, path, timestamp, nonce, body)
        signature = self._sign(signature_string)

        logger.debug(f"Signature string:\n{repr(signature_string)}")
        logger.debug(f"Signature: {signature}")
        logger.debug(f"Auth header: JOP appid=\"{self.app_id}\",accesskey=\"{self.access_key}\",nonce=\"{nonce}\",timestamp=\"{timestamp}\",signature=\"{signature}\"")

        return f'JOP appid="{self.app_id}",accesskey="{self.access_key}",nonce="{nonce}",timestamp="{timestamp}",signature="{signature}"'

    def fetch_parts_page(self, page: int = 1, page_size: int = 1000) -> List[Dict]:
        """
        Fetch one page of parts from JLCPCB Open API

        Args:
            page: Page number (1-based)
            page_size: Number of parts per page (max 1000)

        Returns:
            List of component dicts with keys: componentCode, componentModel, componentSpecification
        """
        path = "/overseas/openapi/component/getComponentLibraryList"

        payload = {"currentPage": page, "pageSize": page_size}
        body_str = json.dumps(payload)

        auth_header = self._get_auth_header("POST", path, body_str)

        headers = {
            "Authorization": auth_header,
            "Content-Type": "application/json"
        }

        try:
            response = requests.post(
                f"{self.BASE_URL}{path}",
                headers=headers,
                data=body_str,
                timeout=60
            )

            logger.debug(f"Response status: {response.status_code}")
            response.raise_for_status()
            data = response.json()

            if data.get('code') != 200:
                raise Exception(f"API request failed (code {data.get('code')}): {data.get('message', 'Unknown error')}")

            return data.get('data', [])

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to fetch parts page: {e}")
            raise Exception(f"JLCPCB API request failed: {e}")

    def download_full_database(
        self,
        callback: Optional[Callable[[int, int, str], None]] = None,
        page_size: int = 1000
    ) -> List[Dict]:
        """
        Download entire parts library from JLCPCB Open API

        Args:
            callback: Optional progress callback function(current_page, total_parts, status_msg)
            page_size: Number of parts per page (max 1000)

        Returns:
            List of all parts (each with componentCode, componentModel, componentSpecification)
        """
        all_parts = []
        page = 0

        logger.info("Starting full JLCPCB parts database download via open.jlcpcb.com...")

        while True:
            page += 1

            try:
                parts = self.fetch_parts_page(page, page_size)

                if not parts:
                    break

                all_parts.extend(parts)

                if callback:
                    callback(page, len(all_parts), f"Downloaded {len(all_parts)} parts...")
                else:
                    logger.info(f"Page {page}: Downloaded {len(all_parts)} parts so far...")

                # Stop if we got fewer than page_size (last page)
                if len(parts) < page_size:
                    break

                # Rate limiting
                time.sleep(0.2)

            except Exception as e:
                logger.error(f"Error downloading parts at page {page}: {e}")
                if len(all_parts) > 0:
                    logger.warning(f"Partial download available: {len(all_parts)} parts")
                    return all_parts
                else:
                    raise

        logger.info(f"Download complete: {len(all_parts)} parts retrieved")
        return all_parts

    def get_part_by_lcsc(self, lcsc_number: str) -> Optional[Dict]:
        """
        The JLCPCB Open API does not have a single-part lookup endpoint.
        Use JLCSearchClient.get_part_by_lcsc() for live per-part lookups.
        """
        logger.warning("get_part_by_lcsc is not supported by JLCPCB Open API; use JLCSearchClient instead")
        return None


def test_jlcpcb_connection(app_id: Optional[str] = None, access_key: Optional[str] = None, secret_key: Optional[str] = None) -> bool:
    """
    Test JLCPCB Open API connection

    Returns:
        True if connection successful, False otherwise
    """
    try:
        client = JLCPCBClient(app_id, access_key, secret_key)
        parts = client.fetch_parts_page(page=1, page_size=5)
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
        print("\nFetching first page of parts...")
        parts = client.fetch_parts_page(page=1, page_size=5)
        print(f"✓ Retrieved {len(parts)} parts in first page")

        if parts:
            print(f"\nExample part:")
            part = parts[0]
            print(f"  LCSC: {part.get('componentCode')}")
            print(f"  Model: {part.get('componentModel')}")
            print(f"  Spec: {part.get('componentSpecification')}")
    else:
        print("✗ Connection failed. Check JLCPCB_APP_ID, JLCPCB_API_KEY, JLCPCB_API_SECRET.")
