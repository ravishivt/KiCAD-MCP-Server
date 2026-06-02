"""
Symbol & pin discovery commands.

Read-only tools for inspecting symbol pins and searching symbol libraries without
needing a schematic loaded. Useful as a pre-flight step before placing components
and wiring nets (e.g. discover pin numbers/names before connect_to_net / batch_connect).

Tools:
  - search_schematic_symbols:    name-substring search across KiCad symbol libraries
  - list_symbol_pins:            pins for one symbol, read straight from the library file
  - batch_list_symbol_pins:      pins for many symbols in one call (+ body bounding box)
  - get_component_pin_positions: world coordinates of a placed component's pins
"""

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from commands.dynamic_symbol_loader import DynamicSymbolLoader
from commands.pin_locator import PinLocator

logger = logging.getLogger("kicad_interface")

# Standard symmetric 2-pin passives that qualify for compact output in
# batch_list_symbol_pins (their pin detail is rarely needed when placing).
COMPACT_SYMBOLS = {
    "Device:R",
    "Device:R_Small",
    "Device:R_US",
    "Device:C",
    "Device:C_Small",
    "Device:C_Polarized",
    "Device:C_Polarized_Small",
    "Device:L",
    "Device:L_Small",
    "Device:LED",
    "Device:D",
    "Device:D_Zener",
    "Device:D_Schottky",
    "Device:Ferrite_Bead",
}

# Pin-envelope padding (mm) used to derive a symbol body bounding box (50 mil).
_BODY_PAD_MM = 1.27

# Matches a pin S-expression inside a symbol definition, capturing
# type, x, y, angle, name and number.
_PIN_RE = re.compile(
    r"\(pin\s+(\S+)\s+\S+\s+\(at\s+(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)\)"
    r'.*?\(name\s+"([^"]*)".*?\(number\s+"([^"]*)"',
    re.DOTALL,
)

# Sub-symbol unit suffix, e.g. "R_0_1", "MCU_1_1" — skipped when listing symbol names.
_SUB_SYMBOL_RE = re.compile(r".+_\d+_\d+$")


def _parse_symbol_pins(
    loader: DynamicSymbolLoader, library_name: str, symbol_name: str
) -> List[Dict[str, Any]]:
    """Return pin data for a symbol read directly from its library file (no schematic needed).

    Each entry: {"number", "name", "type", "x", "y", "angle"} where x/y/angle are in
    symbol-local coordinates (Y increases upward, per the KiCad library convention).

    Raises ValueError (carrying .suggestions) if the symbol cannot be found — this mirrors
    DynamicSymbolLoader.extract_symbol_from_library's behaviour for close-match hints.
    """
    block = loader.extract_symbol_from_library(library_name, symbol_name)
    if not block:
        err = ValueError(f"Symbol '{library_name}:{symbol_name}' not found")
        err.suggestions = []  # type: ignore[attr-defined]
        raise err
    pins: List[Dict[str, Any]] = []
    for m in _PIN_RE.finditer(block):
        pins.append(
            {
                "number": m.group(6),
                "name": m.group(5),
                "type": m.group(1),
                "x": float(m.group(2)),
                "y": float(m.group(3)),
                "angle": float(m.group(4)),
            }
        )
    return sorted(pins, key=lambda p: (len(p["number"]), p["number"]))


def _body_bbox(pins: List[Dict[str, Any]]) -> Optional[Dict[str, float]]:
    """Bounding box of the pin envelope expanded by _BODY_PAD_MM on each side."""
    coords = [(p["x"], p["y"]) for p in pins if "x" in p]
    if not coords:
        return None
    xs = [c[0] for c in coords]
    ys = [c[1] for c in coords]
    return {
        "x_min": round(min(xs) - _BODY_PAD_MM, 4),
        "y_min": round(min(ys) - _BODY_PAD_MM, 4),
        "x_max": round(max(xs) + _BODY_PAD_MM, 4),
        "y_max": round(max(ys) + _BODY_PAD_MM, 4),
        "width": round(max(xs) - min(xs) + 2 * _BODY_PAD_MM, 4),
        "height": round(max(ys) - min(ys) + 2 * _BODY_PAD_MM, 4),
    }


class SymbolPinCommands:
    """Handlers for symbol/pin discovery tools. Stateless; each call builds its own loader."""

    def search_schematic_symbols(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Search for symbol names across KiCad symbol libraries by name substring."""
        logger.info("Searching schematic symbols")
        try:
            query = params.get("query", "").strip()
            max_results = min(int(params.get("maxResults", 20)), 100)
            schematic_path = params.get("schematicPath")

            if not query:
                return {"success": False, "message": "query is required"}

            # Project-local libraries (nickname -> resolved path) shadow global libs of the same name.
            project_libs: Dict[str, Path] = {}
            project_path = None
            if schematic_path:
                project_path = Path(schematic_path).parent
                loader_proj = DynamicSymbolLoader(project_path=project_path)
                sym_lib_table = project_path / "sym-lib-table"
                if sym_lib_table.exists():
                    try:
                        table_content = sym_lib_table.read_text(encoding="utf-8")
                        for m in re.finditer(
                            r'\(lib\s+\(name\s+"?([^"\)\s]+)"?\)\s*\(type\s+[^)]+\)\s*\(uri\s+"?([^"\)\s]+)"?',
                            table_content,
                            re.IGNORECASE,
                        ):
                            resolved = loader_proj._resolve_sym_uri(m.group(2))
                            if resolved and Path(resolved).exists():
                                project_libs[m.group(1)] = Path(resolved)
                    except Exception as e:
                        logger.warning(f"Could not parse project sym-lib-table: {e}")

            loader = DynamicSymbolLoader(project_path=project_path)
            lib_dirs = loader.find_kicad_symbol_libraries()

            results: List[Dict[str, Any]] = []
            query_lower = query.lower()

            def _search_lib_file(lib_file: Path, lib_name: str) -> None:
                try:
                    content = lib_file.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    return
                for sym_name in re.findall(r'\(symbol\s+"([^"]+)"', content):
                    if len(results) >= max_results:
                        return
                    if _SUB_SYMBOL_RE.match(sym_name):
                        continue
                    if query_lower in sym_name.lower() or query_lower in lib_name.lower():
                        results.append(
                            {
                                "library": lib_name,
                                "symbol": sym_name,
                                "fullName": f"{lib_name}:{sym_name}",
                            }
                        )

            # Project-local libraries first (highest priority).
            for nickname, lib_file in project_libs.items():
                if len(results) >= max_results:
                    break
                _search_lib_file(lib_file, nickname)

            # Global libraries, skipping any nickname shadowed by a project lib.
            for lib_dir in lib_dirs:
                if len(results) >= max_results:
                    break
                for lib_file in sorted(lib_dir.glob("*.kicad_sym")):
                    if len(results) >= max_results:
                        break
                    lib_name = lib_file.stem
                    if lib_name in project_libs:
                        continue
                    _search_lib_file(lib_file, lib_name)

            return {"success": True, "results": results, "count": len(results)}

        except Exception as e:
            logger.error(f"Error searching schematic symbols: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def list_symbol_pins(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """List pin numbers, names and types for one symbol, read from its library."""
        logger.info("Listing symbol pins from library")
        try:
            symbol_spec = params.get("symbol", "")
            schematic_path = params.get("schematicPath")

            if not symbol_spec or ":" not in symbol_spec:
                return {"success": False, "message": "symbol must be 'Library:SymbolName'"}

            library_name, symbol_name = symbol_spec.split(":", 1)
            project_path = Path(schematic_path).parent if schematic_path else None
            loader = DynamicSymbolLoader(project_path=project_path)

            try:
                pins = _parse_symbol_pins(loader, library_name, symbol_name)
            except ValueError as e:
                return {
                    "success": False,
                    "message": str(e),
                    "suggestions": getattr(e, "suggestions", []),
                }

            return {
                "success": True,
                "symbol": symbol_spec,
                "pin_count": len(pins),
                "pins": pins,
            }

        except Exception as e:
            logger.error(f"Error listing symbol pins: {e}")
            return {"success": False, "message": str(e)}

    def batch_list_symbol_pins(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """List pins (+ body bounding box) for multiple symbols in a single call."""
        logger.info("Batch listing symbol pins")
        try:
            symbols = params.get("symbols", [])
            schematic_path = params.get("schematicPath")
            compact = bool(params.get("compact", False))

            if not symbols:
                return {"success": False, "message": "symbols list is required"}

            project_path = Path(schematic_path).parent if schematic_path else None
            loader = DynamicSymbolLoader(project_path=project_path)
            results: Dict[str, Any] = {}
            errors: Dict[str, Any] = {}

            for symbol_spec in symbols:
                if ":" not in symbol_spec:
                    errors[symbol_spec] = "symbol must be 'Library:SymbolName'"
                    continue
                library_name, symbol_name = symbol_spec.split(":", 1)
                try:
                    pins = _parse_symbol_pins(loader, library_name, symbol_name)
                except ValueError as e:
                    errors[symbol_spec] = {
                        "message": str(e),
                        "suggestions": getattr(e, "suggestions", []),
                    }
                    continue

                body_bbox = _body_bbox(pins)
                is_symmetric_2pin = len(pins) == 2 and (
                    symbol_spec in COMPACT_SYMBOLS
                    or all(p.get("type", "") == "passive" for p in pins)
                )
                if compact and is_symmetric_2pin:
                    results[symbol_spec] = {
                        "pin_count": len(pins),
                        "body_bbox": body_bbox,
                        "is_symmetric": True,
                        "compact": True,
                        "note": "Pin detail omitted (compact mode, symmetric 2-pin passive). "
                        "Set compact=false to see individual pin coords.",
                    }
                else:
                    results[symbol_spec] = {
                        "pins": pins,
                        "pin_count": len(pins),
                        "body_bbox": body_bbox,
                    }

            return {
                "success": len(errors) == 0,
                "symbols": results,
                "errors": errors if errors else None,
            }

        except Exception as e:
            logger.error(f"Error in batch_list_symbol_pins: {e}")
            return {"success": False, "message": str(e)}

    def get_component_pin_positions(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Return world coordinates (and stub angle) for all pins of a placed component."""
        logger.info("Getting component pin positions")
        try:
            schematic_path = params.get("schematicPath")
            reference = params.get("reference")
            if not schematic_path or not reference:
                return {"success": False, "message": "schematicPath and reference are required"}

            sch_path = Path(schematic_path)
            locator = PinLocator()

            all_pins = locator.get_all_symbol_pins(sch_path, reference)
            if not all_pins:
                return {
                    "success": False,
                    "message": f"No pins found for {reference} — check reference designator",
                }

            lib_id = locator._get_lib_id(sch_path, reference)
            pins_def = locator.get_symbol_pins(sch_path, lib_id) if lib_id else {}

            pins_out: List[Dict[str, Any]] = []
            for pin_num, coords in all_pins.items():
                pd = pins_def.get(str(pin_num), {})
                pin_info = {
                    "pin_number": pin_num,
                    "pin_name": pd.get("name", pin_num),
                    "pin_type": pd.get("type", "unknown"),
                    "position": {"x": float(coords[0]), "y": float(coords[1])},
                }
                try:
                    angle = locator.get_pin_angle(sch_path, reference, str(pin_num))
                    if angle is not None:
                        pin_info["stub_direction_angle"] = angle
                except Exception:
                    pass
                pins_out.append(pin_info)

            return {
                "success": True,
                "reference": reference,
                "pins": pins_out,
                "count": len(pins_out),
            }

        except Exception as e:
            logger.error(f"Error getting component pin positions: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}
