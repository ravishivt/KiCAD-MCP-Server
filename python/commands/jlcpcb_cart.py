"""
JLCPCB Cart API client (official JLCPCB component search)

Uses JLCPCB's internal cart/shopping APIs which return live, authoritative
component data directly from JLCPCB's inventory system.
No authentication required.
"""

import logging
import requests
from typing import Optional, Dict, List

logger = logging.getLogger('kicad_interface')


class JLCPCBCartClient:
    """
    Client for JLCPCB component APIs.

    Uses the JLCPCB shopping cart backend endpoints which power the JLCPCB
    component selection UI. Returns live inventory, pricing, and specifications
    directly from JLCPCB's systems.
    """

    SEARCH_URL = "https://jlcpcb.com/api/overseas-pcb-order/v1/shoppingCart/smtGood/selectSmtComponentList/v2"
    DETAIL_URL = "https://cart.jlcpcb.com/shoppingCart/smtGood/getComponentDetail"

    def search(
        self,
        keyword: str,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict:
        """
        Search for components by keyword.

        Args:
            keyword: Search term (e.g. "10k 0603", "ESP32", "C25804")
            page: Page number (1-based)
            page_size: Results per page (max ~100)

        Returns:
            Dict with keys:
              - total: total result count
              - list: list of component dicts
        """
        payload = {
            "keyword": keyword,
            "currentPage": page,
            "pageSize": page_size,
        }

        try:
            r = requests.post(self.SEARCH_URL, json=payload, timeout=30)
            r.raise_for_status()
            data = r.json()
            if data.get("code") != 200:
                raise Exception(f"API error {data.get('code')}: {data.get('message')}")
            return data.get("data", {}).get("componentPageInfo", {"total": 0, "list": []})
        except requests.exceptions.RequestException as e:
            logger.error(f"JLCPCB search failed: {e}")
            raise Exception(f"JLCPCB search request failed: {e}")

    def get_part(self, lcsc_number) -> Optional[Dict]:
        """
        Get component detail by LCSC number.

        Args:
            lcsc_number: LCSC code as int (25804) or string ("C25804" or "25804")

        Returns:
            Component dict or None if not found
        """
        lcsc_str = str(lcsc_number).lstrip("Cc")
        code = f"C{lcsc_str}"

        try:
            r = requests.get(self.DETAIL_URL, params={"componentCode": code}, timeout=30)
            r.raise_for_status()
            data = r.json()
            if data.get("code") != 200:
                return None
            return data.get("data")
        except requests.exceptions.RequestException as e:
            logger.error(f"JLCPCB get_part {code} failed: {e}")
            return None

    @staticmethod
    def normalize(raw: Dict) -> Dict:
        """
        Normalise a raw API component dict to a consistent schema.

        Returns a dict with these guaranteed keys (others may be included):
          lcsc_str, mfr, description, package, stock, price,
          is_basic, datasheet_url, category
        """
        code = raw.get("componentCode", "")
        # Price: use first tier price (search results) or initialPrice (detail endpoint)
        price = raw.get("initialPrice")
        if price is None:
            prices = raw.get("componentPrices") or raw.get("buyComponentPrices") or []
            if prices:
                sorted_prices = sorted(prices, key=lambda p: p.get("startNumber", 0))
                price = sorted_prices[0].get("productPrice")

        return {
            "lcsc_str": code,
            "lcsc": code,
            "mfr": raw.get("componentModelEn", ""),
            "manufacturer": raw.get("componentBrandEn", ""),
            "description": raw.get("describe", ""),
            "package": raw.get("componentSpecificationEn", ""),
            "stock": raw.get("stockCount", 0),
            "price": price,
            "is_basic": raw.get("componentLibraryType") == "basic",
            "datasheet_url": raw.get("dataManualUrl", ""),
            "category": raw.get("firstSortName", ""),
            "subcategory": raw.get("secondSortName", ""),
            "attributes": raw.get("attributes", []),
        }
