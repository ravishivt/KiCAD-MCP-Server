"""
JLCPCB Parts Database Manager

Manages local SQLite database of JLCPCB parts for fast searching
and component selection.
"""

import os
import re
import sqlite3
import json
import logging
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime

logger = logging.getLogger('kicad_interface')


def _build_fts_query(query: str) -> str:
    """
    Convert a free-text user query into a safe FTS5 MATCH expression.

    - Splits on whitespace and punctuation that FTS5 treats as operators
      (-, +, *, (, ), [, ], ^, ", ', /, :, =, <, >, !, comma, semicolon).
    - Drops single-character tokens (too broad to be useful).
    - Wraps each remaining token in double-quotes and appends * for prefix
      matching, so "ferrite bead" → `"ferrite"* "bead"*`.

    Returns an empty string if no usable tokens remain (caller should fall
    back to a LIKE query).
    """
    tokens = re.split(r'[\s\-+*()\[\]{}^"\'/:=<>!,;|\\]+', query.strip())
    safe = [f'"{t}"*' for t in tokens if len(t) >= 2]
    return ' '.join(safe)


class JLCPCBPartsManager:
    """
    Manages local database of JLCPCB parts

    Provides fast parametric search, filtering, and package-to-footprint mapping.
    """

    def __init__(self, db_path: Optional[str] = None):
        """
        Initialize parts database manager

        Args:
            db_path: Path to SQLite database file (default: data/jlcpcb_parts.db)
        """
        if db_path is None:
            # Default to data directory in project root
            project_root = Path(__file__).parent.parent.parent
            data_dir = project_root / "data"
            data_dir.mkdir(exist_ok=True)
            db_path = str(data_dir / "jlcpcb_parts.db")

        self.db_path = db_path
        self.conn = None
        self._init_database()

    def _init_database(self):
        """Initialize SQLite database with schema"""
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row  # Return rows as dicts

        cursor = self.conn.cursor()

        # Create components table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS components (
                lcsc TEXT PRIMARY KEY,
                category TEXT,
                subcategory TEXT,
                mfr_part TEXT,
                package TEXT,
                solder_joints INTEGER,
                manufacturer TEXT,
                library_type TEXT,
                description TEXT,
                datasheet TEXT,
                stock INTEGER,
                price_json TEXT,
                last_updated INTEGER
            )
        ''')

        # Create indexes for fast searching
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_category ON components(category, subcategory)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_package ON components(package)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_manufacturer ON components(manufacturer)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_library_type ON components(library_type)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_mfr_part ON components(mfr_part)')

        # Full-text search index for descriptions
        cursor.execute('''
            CREATE VIRTUAL TABLE IF NOT EXISTS components_fts USING fts5(
                lcsc,
                description,
                mfr_part,
                manufacturer,
                content=components
            )
        ''')

        self.conn.commit()
        logger.info(f"Initialized JLCPCB parts database at {self.db_path}")

    def import_parts(self, parts: List[Dict], progress_callback=None):
        """
        Import parts from JLCPCB Open API response.

        The official JLCPCB Open API returns only three fields per component:
          - componentCode  (LCSC number, e.g. "C25804")
          - componentModel (manufacturer part number)
          - componentSpecification (package / footprint)

        Args:
            parts: List of part dicts from JLCPCB Open API
            progress_callback: Optional callback(current, total, message)
        """
        cursor = self.conn.cursor()
        imported = 0
        skipped = 0
        now = int(datetime.now().timestamp())

        for i, part in enumerate(parts):
            try:
                cursor.execute('''
                    INSERT OR REPLACE INTO components (
                        lcsc, category, subcategory, mfr_part, package,
                        solder_joints, manufacturer, library_type, description,
                        datasheet, stock, price_json, last_updated
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    part.get('componentCode'),          # lcsc
                    '',                                  # category (not in open API)
                    '',                                  # subcategory
                    part.get('componentModel', ''),      # mfr_part
                    part.get('componentSpecification', ''),  # package
                    0,                                   # solder_joints
                    '',                                  # manufacturer
                    'Extended',                          # library_type (unknown, default Extended)
                    part.get('componentModel', ''),      # description (use model as description)
                    '',                                  # datasheet
                    0,                                   # stock (not in open API)
                    '[]',                                # price_json
                    now
                ))

                imported += 1

                if progress_callback and (i + 1) % 1000 == 0:
                    progress_callback(i + 1, len(parts), f"Imported {imported} parts...")

            except Exception as e:
                logger.error(f"Error importing part {part.get('componentCode')}: {e}")
                skipped += 1

        # Rebuild FTS index
        cursor.execute("INSERT INTO components_fts(components_fts) VALUES('rebuild')")

        self.conn.commit()
        logger.info(f"Import complete: {imported} parts imported, {skipped} skipped")

    def _determine_library_type(self, part: Dict) -> str:
        """Determine if part is Basic, Extended, or Preferred"""
        # JLCPCB API should provide this, but if not, we infer from assembly type
        assembly_type = part.get('assemblyType', '')

        if 'Basic' in assembly_type or part.get('libraryType') == 'base':
            return 'Basic'
        elif 'Extended' in assembly_type:
            return 'Extended'
        elif 'Prefer' in assembly_type:
            return 'Preferred'
        else:
            return 'Extended'  # Default to Extended

    # -------------------------------------------------------------------------
    # /demo/component/info import
    # -------------------------------------------------------------------------

    @staticmethod
    def _parse_component_info_price(price_str: str) -> str:
        """
        Convert /demo/component/info price string to JSON price_breaks format.

        Input:  "1-9:0.804724,10-29:0.585826,30-99:0.544881,100-:0.505511"
        Output: [{"qty": 1, "price": 0.804724}, {"qty": 10, "price": 0.585826}, ...]
        """
        if not price_str:
            return "[]"
        breaks = []
        try:
            for tier in price_str.split(","):
                tier = tier.strip()
                if not tier:
                    continue
                range_part, price_part = tier.split(":")
                start_str = range_part.split("-")[0]
                breaks.append({"qty": int(start_str), "price": float(price_part)})
        except Exception:
            return "[]"
        return json.dumps(breaks)

    @staticmethod
    def _parse_component_info_library_type(library_type: str) -> str:
        """Map /demo/component/info libraryType values to canonical form."""
        mapping = {"base": "Basic", "expand": "Extended", "preferred": "Preferred"}
        return mapping.get((library_type or "").lower(), "Extended")

    def import_component_info_parts(self, parts: List[Dict], progress_callback=None) -> int:
        """
        Import parts from /demo/component/info API response.

        Expected fields per item: lcscPart, firstCategory, secondCategory, mfrPart,
        packageInfo, solderJoint, manufacturer, libraryType, description, datasheet,
        price (range string "start-end:price,..."), stock.

        Does NOT rebuild the FTS index — call rebuild_fts_index() after all pages
        have been imported.

        Args:
            parts: List of component dicts from /demo/component/info
            progress_callback: Optional callback(current, total, message)

        Returns:
            Number of rows successfully imported
        """
        cursor = self.conn.cursor()
        imported = 0
        skipped = 0
        now = int(datetime.now().timestamp())

        for i, part in enumerate(parts):
            try:
                lcsc = part.get("lcscPart", "")
                if not lcsc:
                    skipped += 1
                    continue

                price_json = self._parse_component_info_price(part.get("price", ""))
                library_type = self._parse_component_info_library_type(part.get("libraryType", ""))

                cursor.execute('''
                    INSERT OR REPLACE INTO components (
                        lcsc, category, subcategory, mfr_part, package,
                        solder_joints, manufacturer, library_type, description,
                        datasheet, stock, price_json, last_updated
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    lcsc,
                    part.get("firstCategory", ""),
                    part.get("secondCategory", ""),
                    part.get("mfrPart", ""),
                    part.get("packageInfo") or "",
                    int(part.get("solderJoint") or 0),
                    part.get("manufacturer", ""),
                    library_type,
                    part.get("description", ""),
                    part.get("datasheet", ""),
                    int(part.get("stock") or 0),
                    price_json,
                    now,
                ))
                imported += 1

                if progress_callback and (i + 1) % 1000 == 0:
                    progress_callback(i + 1, len(parts), f"Imported {imported:,} parts...")

            except Exception as e:
                logger.error(f"Error importing part {part.get('lcscPart')}: {e}")
                skipped += 1

        self.conn.commit()
        logger.debug(f"Batch import: {imported} imported, {skipped} skipped")
        return imported

    def rebuild_fts_index(self):
        """Rebuild the full-text search index. Call after bulk imports."""
        cursor = self.conn.cursor()
        cursor.execute("INSERT INTO components_fts(components_fts) VALUES('rebuild')")
        self.conn.commit()
        logger.info("FTS index rebuilt")

    def import_jlcsearch_parts(self, parts: List[Dict], progress_callback=None):
        """
        Import parts into database from JLCSearch API response

        Args:
            parts: List of part dicts from JLCSearch API
            progress_callback: Optional callback(current, total, message)
        """
        cursor = self.conn.cursor()
        imported = 0
        skipped = 0

        for i, part in enumerate(parts):
            try:
                # JLCSearch format is different from official API
                # LCSC is an integer, we need to add 'C' prefix
                lcsc = part.get('lcsc')
                if isinstance(lcsc, int):
                    lcsc = f"C{lcsc}"

                # Build price JSON from jlcsearch single price
                price = part.get('price') or part.get('price1')
                price_json = json.dumps([{"qty": 1, "price": price}] if price else [])

                # Determine library type from is_basic flag
                library_type = 'Basic' if part.get('is_basic') else 'Extended'
                if part.get('is_preferred'):
                    library_type = 'Preferred'

                # Extract description from various fields
                description_parts = []
                if 'resistance' in part:
                    description_parts.append(f"{part['resistance']}Ω")
                if 'capacitance' in part:
                    description_parts.append(f"{part['capacitance']}F")
                if 'tolerance_fraction' in part:
                    tol = part['tolerance_fraction'] * 100
                    description_parts.append(f"±{tol}%")
                if 'power_watts' in part:
                    description_parts.append(f"{part['power_watts']}mW")
                if 'voltage' in part:
                    description_parts.append(f"{part['voltage']}V")

                description = part.get('description', ' '.join(description_parts))

                cursor.execute('''
                    INSERT OR REPLACE INTO components (
                        lcsc, category, subcategory, mfr_part, package,
                        solder_joints, manufacturer, library_type, description,
                        datasheet, stock, price_json, last_updated
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    lcsc,  # lcsc with C prefix
                    part.get('category', ''),  # category
                    part.get('subcategory', ''),  # subcategory
                    part.get('mfr', ''),  # mfr_part
                    part.get('package', ''),  # package
                    0,  # solder_joints (not in jlcsearch)
                    part.get('manufacturer', ''),  # manufacturer
                    library_type,  # library_type
                    description,  # description
                    '',  # datasheet (not in jlcsearch)
                    part.get('stock', 0),  # stock
                    price_json,  # price_json
                    int(datetime.now().timestamp())  # last_updated
                ))

                imported += 1

                if progress_callback and (i + 1) % 1000 == 0:
                    progress_callback(i + 1, len(parts), f"Imported {imported} parts...")

            except Exception as e:
                logger.error(f"Error importing part {part.get('lcsc')}: {e}")
                skipped += 1

        # Update FTS index
        cursor.execute('''
            INSERT INTO components_fts(components_fts)
            VALUES('rebuild')
        ''')

        self.conn.commit()
        logger.info(f"Import complete: {imported} parts imported, {skipped} skipped")

    def search_parts(
        self,
        query: Optional[str] = None,
        category: Optional[str] = None,
        subcategory: Optional[str] = None,
        package: Optional[str] = None,
        library_type: Optional[str] = None,
        manufacturer: Optional[str] = None,
        in_stock: bool = True,
        limit: int = 20
    ) -> List[Dict]:
        """
        Search for parts with filters

        Args:
            query: Free-text search (searches description, mfr part, LCSC)
            category: Filter by top-level category (e.g. "Resistors")
            subcategory: Filter by sub-category (e.g. "Chip Resistor - Surface Mount")
            package: Filter by package type
            library_type: Filter by "Basic", "Extended", or "Preferred"
            manufacturer: Filter by manufacturer name
            in_stock: Only return parts with stock > 0
            limit: Maximum number of results

        Returns:
            List of matching parts
        """
        cursor = self.conn.cursor()

        # Build query
        sql_parts = ["SELECT * FROM components WHERE 1=1"]
        params = []

        if query:
            # Split into significant tokens (>= 3 chars) for LIKE-based fallback.
            tokens = [
                t for t in re.split(r'[\s\-+*()\[\]{}^"\'/:=<>!,;|\\]+', query.strip())
                if len(t) >= 3
            ]

            # Build sub-conditions combined with OR so that a part matches if it
            # satisfies ANY of: FTS on description/mfr_part/manufacturer, OR a
            # category/subcategory LIKE for any query token.
            #
            # Why OR instead of AND:
            # - 90%+ of parts have empty descriptions; category/subcategory are the
            #   only searchable text for most parts.
            # - AND is too strict for multi-word queries ("ferrite bead 600 ohm 0805"
            #   requires all 5 terms in a single field, finding far fewer results).
            sub_conditions = []
            sub_params = []

            fts_query = _build_fts_query(query)
            if fts_query:
                sub_conditions.append(
                    "lcsc IN (SELECT lcsc FROM components_fts WHERE components_fts MATCH ?)"
                )
                sub_params.append(fts_query)

            # Category/subcategory LIKE per token — catches "USB Connectors",
            # "Ferrite Beads", "DC-DC Converters", etc. for parts with no description.
            for token in tokens[:5]:
                sub_conditions.append("(category LIKE ? OR subcategory LIKE ?)")
                sub_params.extend([f"%{token}%", f"%{token}%"])

            if sub_conditions:
                sql_parts.append(f"AND ({' OR '.join(sub_conditions)})")
                params.extend(sub_params)
            elif not fts_query:
                # All tokens were too short — fall back to description LIKE
                sql_parts.append("AND description LIKE ?")
                params.append(f"%{query}%")

        if category:
            sql_parts.append("AND category LIKE ?")
            params.append(f"%{category}%")

        if subcategory:
            sql_parts.append("AND subcategory LIKE ?")
            params.append(f"%{subcategory}%")

        if package:
            sql_parts.append("AND package LIKE ?")
            params.append(f"%{package}%")

        if library_type:
            sql_parts.append("AND library_type = ?")
            params.append(library_type)

        if manufacturer:
            sql_parts.append("AND manufacturer LIKE ?")
            params.append(f"%{manufacturer}%")

        if in_stock:
            sql_parts.append("AND stock > 0")

        sql_parts.append("LIMIT ?")
        params.append(limit)

        sql = " ".join(sql_parts)

        try:
            cursor.execute(sql, params)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Search error: {e}")
            return []

    def get_part_info(self, lcsc_number: str) -> Optional[Dict]:
        """
        Get detailed information for specific LCSC part

        Args:
            lcsc_number: LCSC part number (e.g., "C25804")

        Returns:
            Part info dict or None if not found
        """
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM components WHERE lcsc = ?", (lcsc_number,))
        row = cursor.fetchone()

        if row:
            part = dict(row)
            # Parse price JSON
            if part.get('price_json'):
                try:
                    part['price_breaks'] = json.loads(part['price_json'])
                except:
                    part['price_breaks'] = []
            part['price_approximate'] = True
            return part
        return None

    def get_categories(self, category: Optional[str] = None) -> Dict:
        """
        Return category/subcategory data from the local DB.

        If category is None: returns top-level categories with part counts only.
        If category is provided: returns subcategories for that category.
        Rows with empty category are omitted.
        """
        cursor = self.conn.cursor()

        if category:
            cursor.execute("""
                SELECT subcategory, COUNT(*) as cnt
                FROM components
                WHERE category = ? AND subcategory != '' AND subcategory IS NOT NULL
                GROUP BY subcategory
                ORDER BY cnt DESC
            """, (category,))
            rows = cursor.fetchall()
            return {
                'category': category,
                'subcategories': [
                    {'subcategory': row['subcategory'], 'count': row['cnt']}
                    for row in rows
                ]
            }
        else:
            cursor.execute("""
                SELECT category, COUNT(*) as cnt
                FROM components
                WHERE category != '' AND category IS NOT NULL
                GROUP BY category
                ORDER BY category
            """)
            rows = cursor.fetchall()
            return {
                'categories': [
                    {'category': row['category'], 'count': row['cnt']}
                    for row in rows
                ]
            }

    def get_database_stats(self) -> Dict:
        """Get statistics about the database"""
        cursor = self.conn.cursor()

        cursor.execute("SELECT COUNT(*) as total FROM components")
        total = cursor.fetchone()['total']

        cursor.execute("SELECT COUNT(*) as basic FROM components WHERE library_type = 'Basic'")
        basic = cursor.fetchone()['basic']

        cursor.execute("SELECT COUNT(*) as extended FROM components WHERE library_type = 'Extended'")
        extended = cursor.fetchone()['extended']

        cursor.execute("SELECT COUNT(*) as in_stock FROM components WHERE stock > 0")
        in_stock = cursor.fetchone()['in_stock']

        return {
            'total_parts': total,
            'basic_parts': basic,
            'extended_parts': extended,
            'in_stock': in_stock,
            'db_path': self.db_path
        }

    def map_package_to_footprint(self, package: str) -> List[str]:
        """
        Map JLCPCB package name to KiCAD footprint(s)

        Args:
            package: JLCPCB package name (e.g., "0603", "SOT-23")

        Returns:
            List of possible KiCAD footprint library refs
        """
        # Load mapping from JSON file or use defaults
        mappings = {
            "0402": [
                "Resistor_SMD:R_0402_1005Metric",
                "Capacitor_SMD:C_0402_1005Metric",
                "LED_SMD:LED_0402_1005Metric"
            ],
            "0603": [
                "Resistor_SMD:R_0603_1608Metric",
                "Capacitor_SMD:C_0603_1608Metric",
                "LED_SMD:LED_0603_1608Metric"
            ],
            "0805": [
                "Resistor_SMD:R_0805_2012Metric",
                "Capacitor_SMD:C_0805_2012Metric"
            ],
            "1206": [
                "Resistor_SMD:R_1206_3216Metric",
                "Capacitor_SMD:C_1206_3216Metric"
            ],
            "SOT-23": [
                "Package_TO_SOT_SMD:SOT-23",
                "Package_TO_SOT_SMD:SOT-23-3"
            ],
            "SOT-23-5": [
                "Package_TO_SOT_SMD:SOT-23-5"
            ],
            "SOT-23-6": [
                "Package_TO_SOT_SMD:SOT-23-6"
            ],
            "SOIC-8": [
                "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm"
            ],
            "SOIC-16": [
                "Package_SO:SOIC-16_3.9x9.9mm_P1.27mm"
            ],
            "QFN-20": [
                "Package_DFN_QFN:QFN-20-1EP_4x4mm_P0.5mm_EP2.5x2.5mm"
            ],
            "QFN-32": [
                "Package_DFN_QFN:QFN-32-1EP_5x5mm_P0.5mm_EP3.45x3.45mm"
            ]
        }

        # Normalize package name
        package_normalized = package.strip().upper()

        for key, footprints in mappings.items():
            if key.upper() in package_normalized:
                return footprints

        return []

    def suggest_alternatives(self, lcsc_number: str, limit: int = 5) -> List[Dict]:
        """
        Find alternative parts similar to the given LCSC number

        Prioritizes: cheaper price, higher stock, Basic library type

        Args:
            lcsc_number: Reference LCSC part number
            limit: Maximum alternatives to return

        Returns:
            List of alternative parts
        """
        part = self.get_part_info(lcsc_number)
        if not part:
            return []

        # Search for parts in same category with same package
        alternatives = self.search_parts(
            category=part['subcategory'],
            package=part['package'],
            in_stock=True,
            limit=limit * 3
        )

        # Filter out the original part
        alternatives = [p for p in alternatives if p['lcsc'] != lcsc_number]

        # Sort by: Basic first, then by price, then by stock
        def sort_key(p):
            is_basic = 1 if p.get('library_type') == 'Basic' else 0
            try:
                prices = json.loads(p.get('price_json', '[]'))
                price = float(prices[0].get('price', 999)) if prices else 999
            except:
                price = 999
            stock = p.get('stock', 0)

            return (-is_basic, price, -stock)

        alternatives.sort(key=sort_key)

        return alternatives[:limit]

    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()


if __name__ == '__main__':
    # Test the parts manager
    logging.basicConfig(level=logging.INFO)

    manager = JLCPCBPartsManager()

    # Get stats
    stats = manager.get_database_stats()
    print(f"\nDatabase Statistics:")
    print(f"  Total parts: {stats['total_parts']}")
    print(f"  Basic parts: {stats['basic_parts']}")
    print(f"  Extended parts: {stats['extended_parts']}")
    print(f"  In stock: {stats['in_stock']}")
    print(f"  Database: {stats['db_path']}")

    if stats['total_parts'] > 0:
        print("\nSearching for '10k resistor'...")
        results = manager.search_parts(query="10k resistor", limit=5)
        for part in results:
            print(f"  {part['lcsc']}: {part['mfr_part']} - {part['description']} ({part['library_type']})")
