"""
Pin Locator for KiCad Schematics

Discovers pin locations on symbol instances, accounting for position, rotation, and mirroring.
Uses S-expression parsing to extract pin data from symbol definitions.
"""

import logging
import math
import re
import tempfile
from pathlib import Path
from typing import List, Tuple, Optional, Dict
import sexpdata
from sexpdata import Symbol
from skip import Schematic

logger = logging.getLogger("kicad_interface")


class PinLocator:
    """Locate pins on symbol instances in KiCad schematics"""

    def __init__(self):
        """Initialize pin locator with empty cache"""
        self.pin_definition_cache = {}  # Cache: "lib_id:symbol_name" -> pin_data
        self._schematic_cache: Dict[str, object] = {}  # Cache: path -> loaded Schematic

    @staticmethod
    def parse_symbol_definition(symbol_def: list) -> Dict[str, Dict]:
        """
        Parse a symbol definition from lib_symbols to extract pin information

        Args:
            symbol_def: S-expression list representing symbol definition

        Returns:
            Dictionary mapping pin number -> pin data:
            {
                "1": {"x": 0, "y": 3.81, "angle": 270, "length": 1.27, "name": "~", "type": "passive"},
                "2": {"x": 0, "y": -3.81, "angle": 90, "length": 1.27, "name": "~", "type": "passive"}
            }
        """
        pins = {}

        def extract_pins_recursive(sexp):
            """Recursively search for pin definitions"""
            if not isinstance(sexp, list):
                return

            # Check if this is a pin definition
            if len(sexp) > 0 and sexp[0] == Symbol("pin"):
                # Pin format: (pin type shape (at x y angle) (length len) (name "name") (number "num"))
                pin_data = {
                    "x": 0,
                    "y": 0,
                    "angle": 0,
                    "length": 0,
                    "name": "",
                    "number": "",
                    "type": str(sexp[1]) if len(sexp) > 1 else "passive",
                }

                # Extract pin attributes
                for item in sexp:
                    if isinstance(item, list) and len(item) > 0:
                        if item[0] == Symbol("at") and len(item) >= 3:
                            pin_data["x"] = float(item[1])
                            pin_data["y"] = float(item[2])
                            if len(item) >= 4:
                                pin_data["angle"] = float(item[3])

                        elif item[0] == Symbol("length") and len(item) >= 2:
                            pin_data["length"] = float(item[1])

                        elif item[0] == Symbol("name") and len(item) >= 2:
                            pin_data["name"] = str(item[1]).strip('"')

                        elif item[0] == Symbol("number") and len(item) >= 2:
                            pin_data["number"] = str(item[1]).strip('"')

                # Store by pin number
                if pin_data["number"]:
                    pins[pin_data["number"]] = pin_data

            # Recurse into sublists
            for item in sexp:
                if isinstance(item, list):
                    extract_pins_recursive(item)

        extract_pins_recursive(symbol_def)
        return pins

    def get_symbol_pins(self, schematic_path: Path, lib_id: str) -> Dict[str, Dict]:
        """
        Get pin definitions for a symbol from the schematic's lib_symbols section

        Args:
            schematic_path: Path to .kicad_sch file
            lib_id: Library identifier (e.g., "Device:R", "MCU_ST_STM32F1:STM32F103C8Tx")

        Returns:
            Dictionary mapping pin number -> pin data
        """
        # Check cache
        cache_key = f"{schematic_path}:{lib_id}"
        if cache_key in self.pin_definition_cache:
            logger.debug(f"Using cached pin data for {lib_id}")
            return self.pin_definition_cache[cache_key]

        try:
            # Read schematic
            with open(schematic_path, "r", encoding="utf-8") as f:
                sch_content = f.read()

            # Strip ; comment lines — some .kicad_sym files contain them and they
            # get injected into lib_symbols, causing sexpdata to choke.
            sch_content = re.sub(r'^\s*;.*$', '', sch_content, flags=re.MULTILINE)

            sch_data = sexpdata.loads(sch_content)

            # Find lib_symbols section
            lib_symbols = None
            for item in sch_data:
                if (
                    isinstance(item, list)
                    and len(item) > 0
                    and item[0] == Symbol("lib_symbols")
                ):
                    lib_symbols = item
                    break

            if not lib_symbols:
                logger.error("No lib_symbols section found in schematic")
                return {}

            # Find the specific symbol definition
            for item in lib_symbols[1:]:  # Skip 'lib_symbols' itself
                if (
                    isinstance(item, list)
                    and len(item) > 1
                    and item[0] == Symbol("symbol")
                ):
                    symbol_name = str(item[1]).strip('"')
                    if symbol_name == lib_id:
                        # Found the symbol, parse pins
                        pins = self.parse_symbol_definition(item)
                        self.pin_definition_cache[cache_key] = pins
                        logger.info(f"Extracted {len(pins)} pins from {lib_id}")
                        return pins

            logger.warning(f"Symbol {lib_id} not found in lib_symbols")
            return {}

        except Exception as e:
            logger.error(f"Error getting symbol pins: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {}

    @staticmethod
    def rotate_point(x: float, y: float, angle_degrees: float) -> Tuple[float, float]:
        """
        Rotate a point around the origin

        Args:
            x: X coordinate
            y: Y coordinate
            angle_degrees: Rotation angle in degrees (counterclockwise)

        Returns:
            (rotated_x, rotated_y)
        """
        if angle_degrees == 0:
            return (x, y)

        angle_rad = math.radians(angle_degrees)
        cos_a = math.cos(angle_rad)
        sin_a = math.sin(angle_rad)

        rotated_x = x * cos_a - y * sin_a
        rotated_y = x * sin_a + y * cos_a

        return (rotated_x, rotated_y)

    def _get_lib_id(self, schematic_path: Path, symbol_reference: str) -> Optional[str]:
        """Helper: return the lib_id string for a placed symbol"""
        try:
            sch_key = str(schematic_path)
            if sch_key not in self._schematic_cache:
                self._schematic_cache[sch_key] = Schematic(sch_key)
            sch = self._schematic_cache[sch_key]
            for symbol in sch.symbol:
                if symbol.property.Reference.value == symbol_reference:
                    return symbol.lib_id.value if hasattr(symbol, "lib_id") else None
        except Exception:
            pass
        return None

    def _find_symbol(self, sch_key: str, symbol_reference: str):
        """Helper: load schematic (cached) and find a symbol by reference."""
        if sch_key not in self._schematic_cache:
            self._schematic_cache[sch_key] = Schematic(sch_key)
        sch = self._schematic_cache[sch_key]
        for symbol in sch.symbol:
            if symbol.property.Reference.value == symbol_reference:
                return symbol
        return None

    def _find_skip_pin(self, symbol, pin_id: str):
        """
        Find a SymbolPin on a skip Symbol by pin number or name.
        Returns the SymbolPin or None.
        """
        for pin in symbol.pin:
            if str(pin.number) == str(pin_id) or pin.name == str(pin_id):
                return pin
        return None

    def get_pin_angle(
        self, schematic_path: Path, symbol_reference: str, pin_number: str
    ) -> Optional[float]:
        """
        Get the outward angle of a pin endpoint in degrees (0=right, 90=up, 180=left, 270=down).
        Uses skip's SymbolPin.location which correctly handles symbol rotation and Y-axis flip.
        """
        try:
            symbol = self._find_symbol(str(schematic_path), symbol_reference)
            if not symbol:
                return None
            pin = self._find_skip_pin(symbol, pin_number)
            if not pin:
                return None
            return float(pin.location.rotation)
        except Exception:
            return None

    def get_pin_location(
        self, schematic_path: Path, symbol_reference: str, pin_number: str
    ) -> Optional[List[float]]:
        """
        Get the absolute location of a pin on a symbol instance.

        Uses skip's SymbolPin.location which correctly handles symbol rotation,
        mirroring, and KiCad's Y-axis convention (lib editor uses Y-up;
        schematic uses Y-down — skip applies the negation automatically).

        Args:
            schematic_path: Path to .kicad_sch file
            symbol_reference: Symbol reference designator (e.g., "R1", "U1")
            pin_number: Pin number or name (e.g., "1", "GND", "SDA")

        Returns:
            [x, y] absolute schematic coordinates of the pin endpoint (Y-axis DOWN),
            or None if not found.

        Coordinate convention:
            KiCad symbol library files use Y-UP (positive Y goes up).
            KiCad schematics use Y-DOWN (positive Y goes down).
            The correct manual formula would be:
                schematic_y = component_y - pin_symbol_y
            skip's pin.location applies this flip automatically, so callers
            receive ready-to-use schematic coordinates and must NOT apply any
            additional Y transformation.
        """
        try:
            symbol = self._find_symbol(str(schematic_path), symbol_reference)
            if not symbol:
                logger.error(f"Symbol {symbol_reference} not found in schematic")
                return None
            pin = self._find_skip_pin(symbol, pin_number)
            if not pin:
                available = [(str(p.number), p.name) for p in symbol.pin]
                logger.error(
                    f"Pin {pin_number} not found on {symbol_reference}. "
                    f"Available: {available}"
                )
                return None
            loc = pin.location
            logger.info(f"Pin {symbol_reference}/{pin_number} located at ({loc.x}, {loc.y})")
            return [loc.x, loc.y]
        except Exception as e:
            logger.error(f"Error getting pin location: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None

    def get_all_symbol_pins(
        self, schematic_path: Path, symbol_reference: str
    ) -> Dict[str, List[float]]:
        """
        Get locations of all pins on a symbol instance.

        Returns:
            Dictionary mapping pin number -> [x, y] coordinates
        """
        try:
            symbol = self._find_symbol(str(schematic_path), symbol_reference)
            if not symbol:
                logger.error(f"Symbol {symbol_reference} not found")
                return {}
            result = {}
            for pin in symbol.pin:
                loc = pin.location
                result[str(pin.number)] = [loc.x, loc.y]
            logger.info(f"Located {len(result)} pins on {symbol_reference}")
            return result
        except Exception as e:
            logger.error(f"Error getting all symbol pins: {e}")
            return {}


if __name__ == "__main__":
    # Test pin location discovery
    import sys

    sys.path.insert(0, "/home/chris/MCP/KiCAD-MCP-Server/python")

    from pathlib import Path
    from commands.component_schematic import ComponentManager
    from commands.schematic import SchematicManager
    import shutil

    print("=" * 80)
    print("PIN LOCATOR TEST")
    print("=" * 80)

    # Create test schematic with components (cross-platform temp directory)
    test_path = Path(tempfile.gettempdir()) / "test_pin_locator.kicad_sch"
    template_path = Path(
        "/home/chris/MCP/KiCAD-MCP-Server/python/templates/template_with_symbols_expanded.kicad_sch"
    )

    shutil.copy(template_path, test_path)
    print(f"\n✓ Created test schematic: {test_path}")

    # Add some components
    print("\n[1/4] Adding test components...")
    sch = SchematicManager.load_schematic(str(test_path))

    # Add resistor at (100, 100), rotation 0
    r1_def = {
        "type": "R",
        "reference": "R1",
        "value": "10k",
        "x": 100,
        "y": 100,
        "rotation": 0,
    }
    ComponentManager.add_component(sch, r1_def, test_path)

    # Add capacitor at (150, 100), rotation 90
    c1_def = {
        "type": "C",
        "reference": "C1",
        "value": "100nF",
        "x": 150,
        "y": 100,
        "rotation": 90,
    }
    ComponentManager.add_component(sch, c1_def, test_path)

    SchematicManager.save_schematic(sch, str(test_path))
    print("  ✓ Added R1 and C1")

    # Test pin locator
    print("\n[2/4] Testing pin location discovery...")
    locator = PinLocator()

    # Find R1 pins
    r1_pin1 = locator.get_pin_location(test_path, "R1", "1")
    r1_pin2 = locator.get_pin_location(test_path, "R1", "2")

    print(f"  R1 pin 1: {r1_pin1}")
    print(f"  R1 pin 2: {r1_pin2}")

    # Find C1 pins (rotated 90 degrees)
    c1_pin1 = locator.get_pin_location(test_path, "C1", "1")
    c1_pin2 = locator.get_pin_location(test_path, "C1", "2")

    print(f"  C1 pin 1: {c1_pin1}")
    print(f"  C1 pin 2: {c1_pin2}")

    # Test get all pins
    print("\n[3/4] Testing get all pins...")
    r1_all_pins = locator.get_all_symbol_pins(test_path, "R1")
    print(f"  R1 all pins: {r1_all_pins}")

    c1_all_pins = locator.get_all_symbol_pins(test_path, "C1")
    print(f"  C1 all pins: {c1_all_pins}")

    # Verify results
    print("\n[4/4] Verification...")
    success = True

    if not r1_pin1 or not r1_pin2:
        print("  ✗ Failed to locate R1 pins")
        success = False
    else:
        print("  ✓ R1 pins located")

    if not c1_pin1 or not c1_pin2:
        print("  ✗ Failed to locate C1 pins")
        success = False
    else:
        print("  ✓ C1 pins located")

    # Check rotation (C1 pins should be rotated 90 degrees from R1)
    if r1_pin1 and c1_pin1:
        # R1 is not rotated, pins should be at y offset from symbol center
        # C1 is rotated 90°, pins should be at x offset from symbol center
        print(f"\n  Pin offset analysis:")
        print(f"    R1 (0°):  pin 1 y-offset = {r1_pin1[1] - 100}")
        print(f"    C1 (90°): pin 1 x-offset = {c1_pin1[0] - 150}")

    print("\n" + "=" * 80)
    if success:
        print("✅ PIN LOCATOR TEST PASSED!")
    else:
        print("❌ PIN LOCATOR TEST FAILED!")
    print("=" * 80)
    print(f"\nTest schematic saved: {test_path}")
