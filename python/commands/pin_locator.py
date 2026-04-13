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
from typing import Any, Dict, List, Optional, Tuple

import sexpdata
from sexpdata import Symbol
from skip import Schematic

logger = logging.getLogger("kicad_interface")


class PinLocator:
    """Locate pins on symbol instances in KiCad schematics"""

    def __init__(self) -> None:
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
        pins: Dict[str, Dict[str, Any]] = {}

        def extract_pins_recursive(sexp: Any) -> None:
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
                if isinstance(item, list) and len(item) > 0 and item[0] == Symbol("lib_symbols"):
                    lib_symbols = item
                    break

            if not lib_symbols:
                logger.error("No lib_symbols section found in schematic")
                return {}

            # Find the specific symbol definition
            for item in lib_symbols[1:]:  # Skip 'lib_symbols' itself
                if isinstance(item, list) and len(item) > 1 and item[0] == Symbol("symbol"):
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

    def _get_component_transform(self, symbol) -> Tuple[float, float, float, bool, bool]:
        """
        Extract (comp_x, comp_y, rotation_deg, mirror_x, mirror_y) from a skip symbol.

        In KiCAD schematics, rotation is CCW-positive when viewed on screen (Y-down).
        """
        at_val = symbol.at.value if hasattr(symbol, "at") and hasattr(symbol.at, "value") else [0, 0, 0]
        comp_x = float(at_val[0])
        comp_y = float(at_val[1])
        rotation = float(at_val[2]) if len(at_val) > 2 else 0.0

        mirror_x = False
        mirror_y = False
        try:
            if hasattr(symbol, "mirror"):
                mirror_val = str(symbol.mirror.value if hasattr(symbol.mirror, "value") else symbol.mirror)
                mirror_x = "x" in mirror_val.lower()
                mirror_y = "y" in mirror_val.lower()
        except Exception:
            pass

        return comp_x, comp_y, rotation, mirror_x, mirror_y

    def _transform_pin_to_schematic(
        self,
        px_lib: float,
        py_lib: float,
        comp_x: float,
        comp_y: float,
        rotation: float,
        mirror_x: bool = False,
        mirror_y: bool = False,
    ) -> Tuple[float, float]:
        """
        Transform a pin endpoint from library space to absolute schematic coordinates.

        KiCAD library files use Y-UP; schematics use Y-DOWN.
        KiCAD rotation in schematics is CCW-positive when viewed on screen.

        The transformation steps are:
          1. Apply mirror (in lib Y-up space)
          2. Y-flip: py_sch = -py_lib
          3. Rotate by component rotation (CCW positive in screen/schematic space):
               rx = px_sch * cos(R) + py_sch * sin(R)
               ry = -px_sch * sin(R) + py_sch * cos(R)
          4. Translate by component position
        """
        # Step 1: mirror in lib space (before Y-flip)
        if mirror_x:
            py_lib = -py_lib
        if mirror_y:
            px_lib = -px_lib

        # Step 2: Y-flip
        px_sch = px_lib
        py_sch = -py_lib

        # Step 3: rotate in schematic space (CCW positive on screen)
        if rotation != 0.0:
            R_rad = math.radians(rotation)
            cos_r = math.cos(R_rad)
            sin_r = math.sin(R_rad)
            rx = px_sch * cos_r + py_sch * sin_r
            ry = -px_sch * sin_r + py_sch * cos_r
        else:
            rx, ry = px_sch, py_sch

        # Step 4: translate
        return round(comp_x + rx, 4), round(comp_y + ry, 4)

    def _transform_pin_angle_to_schematic(
        self, angle_lib: float, rotation: float, mirror_x: bool = False, mirror_y: bool = False
    ) -> float:
        """
        Transform a pin's outward angle from library space to schematic space.

        In lib space (Y-up), angle 0 = right, 90 = up, 180 = left, 270 = down.
        In schematic space (Y-down), the Y-flip negates Y, so angles in the upper
        half (0-180) map to angles in the lower half.

        Y-flip formula:  angle_sch = (-angle_lib) % 360
        Then apply component rotation (CCW-positive on screen):
                         angle_final = (angle_sch - rotation) % 360
        """
        a = float(angle_lib)
        if mirror_x:
            a = (-a) % 360
        if mirror_y:
            a = (180 - a) % 360
        # Y-flip
        a = (-a) % 360
        # CCW rotation on screen subtracts from angle
        a = (a - rotation) % 360
        return a

    def _get_all_pins_from_lib_symbols(
        self, schematic_path: Path, symbol, symbol_reference: str
    ) -> Dict[str, List[float]]:
        """
        Compute absolute pin endpoints from the lib_symbols section + component transform.
        Used as fallback when skip's symbol.pin is empty.
        """
        lib_id = symbol.lib_id.value if hasattr(symbol, "lib_id") else None
        if not lib_id:
            logger.error(f"Cannot get lib_id for {symbol_reference}")
            return {}

        pins_def = self.get_symbol_pins(schematic_path, lib_id)
        if not pins_def:
            logger.warning(f"No pin definitions found in lib_symbols for {lib_id}")
            return {}

        comp_x, comp_y, rotation, mirror_x, mirror_y = self._get_component_transform(symbol)
        result = {}
        for pin_num, pin_data in pins_def.items():
            px_lib = float(pin_data["x"])
            py_lib = float(pin_data["y"])
            abs_x, abs_y = self._transform_pin_to_schematic(
                px_lib, py_lib, comp_x, comp_y, rotation, mirror_x, mirror_y
            )
            result[str(pin_num)] = [abs_x, abs_y]

        logger.info(
            f"Fallback: computed {len(result)} pin locations for {symbol_reference} "
            f"from lib_symbols (rotation={rotation}, mirror_x={mirror_x}, mirror_y={mirror_y})"
        )
        return result

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
        Get the outward angle of a pin endpoint in degrees (0=right, 90=up in screen, 180=left, 270=down in screen).
        Tries skip's SymbolPin.location first; falls back to lib_symbols + component transform.
        """
        try:
            symbol = self._find_symbol(str(schematic_path), symbol_reference)
            if not symbol:
                return None

            # Try skip's pin.location.rotation first
            try:
                pin = self._find_skip_pin(symbol, pin_number)
                if pin:
                    return float(pin.location.rotation)
            except Exception:
                pass

            # Fallback: compute from lib_symbols definition
            lib_id = symbol.lib_id.value if hasattr(symbol, "lib_id") else None
            if not lib_id:
                return None
            pins_def = self.get_symbol_pins(schematic_path, lib_id)

            # Find pin by number or name
            pin_data = pins_def.get(str(pin_number))
            if pin_data is None:
                for num, data in pins_def.items():
                    if data.get("name") == str(pin_number):
                        pin_data = data
                        break

            if pin_data is None:
                return None

            comp_x, comp_y, rotation, mirror_x, mirror_y = self._get_component_transform(symbol)
            # Compute outward pin angle: lib_angle + component_rotation.
            # kicad-skip returns the raw lib angle (no Y-flip); the fallback must match.
            # The Y-flip in _transform_pin_angle_to_schematic incorrectly inverts 90°/270°
            # angles at rotation=0, causing bottom-facing pins to get "upward" orientation.
            lib_angle = float(pin_data.get("angle", 0))
            angle = (lib_angle + rotation) % 360
            if mirror_x:
                angle = (180 - angle) % 360  # reflect about Y-axis: swaps left↔right
            if mirror_y:
                angle = (-angle) % 360        # reflect about X-axis: swaps up↔down
            return angle
        except Exception:
            return None

    def get_pin_location(
        self, schematic_path: Path, symbol_reference: str, pin_number: str
    ) -> Optional[List[float]]:
        """
        Get the absolute location of a pin on a symbol instance.

        Tries skip's SymbolPin.location first (handles rotation/mirror/Y-flip automatically).
        Falls back to lib_symbols-based manual computation when skip returns nothing —
        this covers custom library symbols (connectors, power, project-specific libs)
        where skip may not expose pins via symbol.pin.

        Args:
            schematic_path: Path to .kicad_sch file
            symbol_reference: Symbol reference designator (e.g., "R1", "U1")
            pin_number: Pin number or name (e.g., "1", "GND", "SDA")

        Returns:
            [x, y] absolute schematic coordinates of the pin endpoint (Y-axis DOWN),
            or None if not found.
        """
        try:
            symbol = self._find_symbol(str(schematic_path), symbol_reference)
            if not symbol:
                logger.error(f"Symbol {symbol_reference} not found in schematic")
                return None

            # Always use lib_symbols fallback: skip's pin.location does not apply the
            # Y-flip between KiCad library (Y-up) and schematic (Y-down) coordinate
            # systems, causing K/A positions to be swapped for components with
            # non-zero rotation angles. The lib_symbols path correctly handles this.
            logger.info(
                f"Computing pin location for {symbol_reference}/{pin_number} "
                "via lib_symbols fallback"
            )
            all_pins = self._get_all_pins_from_lib_symbols(schematic_path, symbol, symbol_reference)
            if not all_pins:
                logger.error(f"Could not find pin {pin_number} on {symbol_reference} via any method")
                return None

            # Match by pin number
            if str(pin_number) in all_pins:
                coords = all_pins[str(pin_number)]
                logger.info(
                    f"Pin {symbol_reference}/{pin_number} located at {coords} via lib_symbols fallback"
                )
                return [coords[0], coords[1]]

            # Match by pin name
            lib_id = symbol.lib_id.value if hasattr(symbol, "lib_id") else None
            if lib_id:
                pins_def = self.get_symbol_pins(schematic_path, lib_id)
                for num, data in pins_def.items():
                    if data.get("name") == str(pin_number) and str(num) in all_pins:
                        coords = all_pins[str(num)]
                        logger.info(
                            f"Pin {symbol_reference}/{pin_number} (name match on #{num}) "
                            f"located at {coords} via lib_symbols fallback"
                        )
                        return [coords[0], coords[1]]

            logger.error(
                f"Pin {pin_number} not found on {symbol_reference}. "
                f"Available pins: {sorted(all_pins.keys())}"
            )
            return None
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

        Tries skip's symbol.pin first; falls back to lib_symbols + component transform
        when skip returns no pins (common for custom/connector/power symbols).

        Returns:
            Dictionary mapping pin number -> [x, y] coordinates
        """
        try:
            symbol = self._find_symbol(str(schematic_path), symbol_reference)
            if not symbol:
                logger.error(f"Symbol {symbol_reference} not found")
                return {}

            # Always use lib_symbols fallback: skip's pin.location does not apply the
            # Y-flip between KiCad library (Y-up) and schematic (Y-down) coordinate
            # systems, causing pin positions to be swapped for rotated components.
            fallback = self._get_all_pins_from_lib_symbols(schematic_path, symbol, symbol_reference)
            return fallback
        except Exception as e:
            logger.error(f"Error getting all symbol pins: {e}")
            return {}

    def get_pin_metadata(self, schematic_path: Path, ref: str, pin_num: str) -> dict:
        """
        Return {"name": str, "type": str} for a given (ref, pin_num), or {} on miss.
        Uses _get_lib_id() + get_symbol_pins() with their caches — fast for bulk lookups.
        """
        lib_id = self._get_lib_id(schematic_path, ref)
        if not lib_id:
            return {}
        pins_def = self.get_symbol_pins(schematic_path, lib_id)
        return pins_def.get(str(pin_num), {})


if __name__ == "__main__":
    # Test pin location discovery
    import shutil
    import sys
    from pathlib import Path

    from commands.component_schematic import ComponentManager
    from commands.schematic import SchematicManager

    sys.path.insert(0, str(Path(__file__).parent.parent))

    print("=" * 80)
    print("PIN LOCATOR TEST")
    print("=" * 80)

    # Create test schematic with components (cross-platform temp directory)
    test_path = Path(tempfile.gettempdir()) / "test_pin_locator.kicad_sch"
    template_path = (
        Path(__file__).parent.parent / "templates" / "template_with_symbols_expanded.kicad_sch"
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
