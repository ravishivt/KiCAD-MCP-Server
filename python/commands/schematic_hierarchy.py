"""
Schematic connectivity & hierarchy commands.

Tools:
  - add_schematic_junction:      add a junction dot (splitting any wire it lands on)
  - place_net_label_at_pin:      place a net label exactly at a component pin endpoint
  - add_hierarchical_sheet:      insert a hierarchical-sheet reference into a parent schematic
  - create_hierarchical_subsheet: create a sub-sheet file and link it in one call
  - validate_schematic:          fast parenthesis-balance / structure check (no full parse)

The command class holds a back-reference to KiCADInterface so it can reuse the existing
create_schematic handler, and exposes fix_subsheet_instances for the batch module to call.
"""

import logging
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List

import sexpdata
from sexpdata import Symbol

from commands.pin_locator import PinLocator
from commands.schematic_field_layout import _find_facing_label
from commands.wire_manager import WireManager

logger = logging.getLogger("kicad_interface")

_SHEET_INSTANCES = Symbol("sheet_instances")
# Pin angle -> label orientation (label text extends outward from the pin).
_LABEL_ORIENTATION = {0: 180, 90: 270, 180: 0, 270: 90}


def _add_junction(sch_path: Path, position, diameter: float = 0) -> bool:
    """Insert a junction at *position*, splitting any wire that passes through it."""
    try:
        sch_data = sexpdata.loads(sch_path.read_text(encoding="utf-8"))

        try:
            WireManager._break_wires_at_point(sch_data, position)
        except Exception as e:
            logger.warning(f"add_junction: wire split skipped: {e}")

        junction = [
            Symbol("junction"),
            [Symbol("at"), position[0], position[1]],
            [Symbol("diameter"), diameter],
            [Symbol("color"), 0, 0, 0, 0],
            [Symbol("uuid"), str(uuid.uuid4())],
        ]

        insert_at = None
        for i, item in enumerate(sch_data):
            if isinstance(item, list) and len(item) > 0 and item[0] == _SHEET_INSTANCES:
                insert_at = i
                break
        if insert_at is None:
            logger.error("add_junction: no sheet_instances section found")
            return False

        sch_data.insert(insert_at, junction)
        sch_path.write_text(sexpdata.dumps(sch_data), encoding="utf-8")
        return True
    except Exception as e:
        logger.error(f"Error adding junction: {e}")
        return False


class SchematicHierarchyCommands:
    """Handlers for junctions, pin labels, hierarchical sheets, and validation."""

    def __init__(self, iface):
        self.iface = iface

    def add_schematic_junction(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Add a junction (connection dot) to a schematic."""
        logger.info("Adding junction to schematic")
        try:
            schematic_path = params.get("schematicPath")
            position = params.get("position")
            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}
            if not position:
                return {"success": False, "message": "position is required"}

            if _add_junction(Path(schematic_path), position):
                return {"success": True, "message": "Junction added successfully"}
            return {"success": False, "message": "Failed to add junction"}
        except Exception as e:
            logger.error(f"Error adding junction: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def place_net_label_at_pin(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Place a net label at the exact endpoint of a component pin (no wire stub)."""
        logger.info("Placing net label at pin")
        try:
            schematic_path = params.get("schematicPath")
            reference = params.get("reference")
            pin_number = params.get("pinNumber")
            net_name = params.get("netName")

            if not all([schematic_path, reference, pin_number, net_name]):
                return {
                    "success": False,
                    "message": "Missing required parameters: schematicPath, reference, pinNumber, netName",
                }

            locator = PinLocator()
            sch_path = Path(schematic_path)

            position = locator.get_pin_location(sch_path, reference, str(pin_number))
            if not position:
                all_pins = locator.get_all_symbol_pins(sch_path, reference) or {}
                if len(all_pins) == 1:
                    pin_number = next(iter(all_pins))
                    position = all_pins[pin_number]
                else:
                    return {
                        "success": False,
                        "message": f"Could not find pin '{pin_number}' on {reference}. "
                        f"Available pins: {sorted(all_pins.keys()) if all_pins else 'none found'}",
                    }

            raw_angle = locator.get_pin_angle(sch_path, reference, str(pin_number)) or 0
            cardinal = round(raw_angle / 90) * 90 % 360
            orientation = _LABEL_ORIENTATION.get(cardinal, 0)

            existing_pos = _find_facing_label(sch_path, net_name, position, orientation)
            if existing_pos:
                wire_ok = WireManager.add_wire(sch_path, list(position), existing_pos)
                return {
                    "success": wire_ok,
                    "reference": reference,
                    "pinNumber": pin_number,
                    "netName": net_name,
                    "position": {"x": position[0], "y": position[1]},
                    "labelOrientation": orientation,
                    "note": f"Wired to existing '{net_name}' label at ({existing_pos[0]},{existing_pos[1]}) instead of duplicate",
                }

            if WireManager.add_label(
                sch_path, net_name, position, label_type="label", orientation=orientation
            ):
                return {
                    "success": True,
                    "reference": reference,
                    "pinNumber": pin_number,
                    "netName": net_name,
                    "position": {"x": position[0], "y": position[1]},
                    "labelOrientation": orientation,
                }
            return {"success": False, "message": "Failed to place net label"}

        except Exception as e:
            logger.error(f"Error placing net label at pin: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def add_hierarchical_sheet(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Insert a hierarchical sheet reference block into a parent schematic."""
        logger.info("Adding hierarchical sheet")
        try:
            schematic_path = params.get("schematicPath")
            subsheet_path = params.get("subsheetPath")
            sheet_name = params.get("sheetName", "Sheet")
            position = params.get("position", {})
            size = params.get("size", {})

            if not schematic_path or not subsheet_path:
                return {"success": False, "message": "schematicPath and subsheetPath are required"}

            x = float(position.get("x", 50))
            y = float(position.get("y", 50))
            w = float(size.get("width", 80))
            h = float(size.get("height", 50))

            parent_file = Path(schematic_path)
            try:
                rel_str = str(
                    Path(subsheet_path).resolve().relative_to(parent_file.parent.resolve())
                ).replace("\\", "/")
            except ValueError:
                rel_str = str(subsheet_path).replace("\\", "/")

            sheet_block_uuid = str(uuid.uuid4())
            name_x, name_y = round(x + 2.54, 4), round(y - 1.27, 4)
            file_x, file_y = round(x + 2.54, 4), round(y + h + 1.27, 4)

            sheet_block = (
                f"  (sheet (at {x} {y}) (size {w} {h}) (fields_autoplaced yes)\n"
                f"    (stroke (width 0.0006) (type default))\n"
                f"    (fill (color 0 0 0 0.0000))\n"
                f'    (uuid "{sheet_block_uuid}")\n'
                f'    (property "Sheet name" "{sheet_name}" (at {name_x} {name_y} 0)\n'
                f"      (effects (font (size 1.27 1.27)) (justify left bottom))\n"
                f"    )\n"
                f'    (property "Sheet file" "{rel_str}" (at {file_x} {file_y} 0)\n'
                f"      (effects (font (size 1.27 1.27)) (justify left bottom))\n"
                f"    )\n"
                f"  )\n"
            )

            content = parent_file.read_text(encoding="utf-8")
            parent_uuid_match = re.search(r"\(uuid\s+([0-9a-fA-F-]+)\)", content)
            parent_uuid = parent_uuid_match.group(1) if parent_uuid_match else ""
            existing_pages = re.findall(r'\(page\s+"(\d+)"\)', content)
            next_page = max((int(p) for p in existing_pages), default=0) + 1

            instance_path = (
                f"/{parent_uuid}/{sheet_block_uuid}" if parent_uuid else f"/{sheet_block_uuid}"
            )
            path_entry = f'    (path "{instance_path}" (page "{next_page}"))\n'

            insert_at = content.rfind("(sheet_instances")
            if insert_at == -1:
                return {"success": False, "message": "Could not find (sheet_instances in schematic"}
            content = content[:insert_at] + sheet_block + "  " + content[insert_at:]

            si_start = content.rfind("(sheet_instances")
            depth = 0
            si_close = len(content) - 1
            for i in range(si_start, len(content)):
                if content[i] == "(":
                    depth += 1
                elif content[i] == ")":
                    depth -= 1
                    if depth == 0:
                        si_close = i
                        break
            content = content[:si_close] + path_entry + "  " + content[si_close:]

            parent_file.write_text(content, encoding="utf-8")

            # Ensure each sub-sheet component has the hierarchical instance entry.
            self.fix_subsheet_instances(str(parent_file), content)

            return {
                "success": True,
                "sheet_uuid": sheet_block_uuid,
                "sheet_name": sheet_name,
                "subsheet_path": rel_str,
                "page": next_page,
            }

        except Exception as e:
            logger.error(f"Error adding hierarchical sheet: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def create_hierarchical_subsheet(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new sub-sheet file and link it into a parent schematic in one call."""
        logger.info("Creating hierarchical subsheet")
        try:
            parent_path = params.get("parentSchematicPath")
            subsheet_path = params.get("subsheetPath")
            sheet_name = params.get("sheetName", "Sheet")
            position = params.get("position", {})
            size = params.get("size", {})
            metadata = params.get("metadata", {})

            if not parent_path or not subsheet_path:
                return {
                    "success": False,
                    "message": "parentSchematicPath and subsheetPath are required",
                }

            create_result = self.iface._handle_create_schematic(
                {"filename": subsheet_path, "metadata": metadata}
            )
            if not create_result.get("success"):
                return {
                    "success": False,
                    "message": f"Failed to create sub-sheet: {create_result.get('message')}",
                }

            link_result = self.add_hierarchical_sheet(
                {
                    "schematicPath": parent_path,
                    "subsheetPath": subsheet_path,
                    "sheetName": sheet_name,
                    "position": position,
                    "size": size,
                }
            )
            if not link_result.get("success"):
                return {
                    "success": False,
                    "message": f"Created sub-sheet but failed to link: {link_result.get('message')}",
                    "subsheet_created": create_result.get("file_path", subsheet_path),
                }

            return {
                "success": True,
                "subsheet_path": create_result.get("file_path", subsheet_path),
                "subsheet_uuid": create_result.get("schematic_uuid"),
                "sheet_block_uuid": link_result.get("sheet_uuid"),
                "sheet_name": sheet_name,
                "page": link_result.get("page"),
                "message": (
                    f"Created sub-sheet '{sheet_name}' at {subsheet_path} "
                    f"and linked it into {parent_path} (page {link_result.get('page')})"
                ),
            }
        except Exception as e:
            logger.error(f"Error in create_hierarchical_subsheet: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def validate_schematic(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Check parenthesis balance / basic structure of a .kicad_sch without fully loading it."""
        logger.info("Validating schematic syntax")
        try:
            schematic_path = params.get("schematicPath")
            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}
            sch_file = Path(schematic_path)
            if not sch_file.exists():
                return {"success": False, "message": f"File not found: {schematic_path}"}

            content = sch_file.read_text(encoding="utf-8")
            depth = 0
            in_string = False
            escape_next = False
            error_line = None
            error_char = None
            line_num = 1

            for i, ch in enumerate(content):
                if escape_next:
                    escape_next = False
                    continue
                if ch == "\n":
                    line_num += 1
                if in_string:
                    if ch == "\\":
                        escape_next = True
                    elif ch == '"':
                        in_string = False
                    continue
                if ch == '"':
                    in_string = True
                    continue
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                    if depth < 0:
                        error_line = line_num
                        error_char = i
                        break

            if error_line is not None:
                return {
                    "success": False,
                    "valid": False,
                    "error": f"Parenthesis underflow at line {error_line} (char {error_char}): unexpected ')'",
                    "line": error_line,
                }
            if depth != 0:
                return {
                    "success": False,
                    "valid": False,
                    "error": f"Parenthesis mismatch: {depth} unclosed '(' at end of file",
                    "unclosed": depth,
                }
            return {
                "success": True,
                "valid": True,
                "message": f"Schematic syntax OK ({len(content)} bytes, {line_num} lines)",
            }
        except Exception as e:
            logger.error(f"Error validating schematic: {e}")
            return {"success": False, "message": str(e)}

    def fix_subsheet_instances(self, parent_path: str, parent_content: str) -> List[str]:
        """Ensure every component in each referenced sub-sheet has an instances entry for the
        sheet-block UUID, so ERC resolves references correctly. Returns modified sub-sheet paths.
        """
        modified_sheets: List[str] = []
        try:
            parent_file = Path(parent_path)
            parent_data = sexpdata.loads(parent_content)

            for item in parent_data:
                if not (isinstance(item, list) and len(item) > 0 and item[0] == Symbol("sheet")):
                    continue

                sheet_block_uuid = None
                sheet_file_rel = None
                for sub in item:
                    if isinstance(sub, list) and len(sub) >= 2 and sub[0] == Symbol("uuid"):
                        sheet_block_uuid = str(sub[1])
                    elif (
                        isinstance(sub, list)
                        and len(sub) >= 3
                        and sub[0] == Symbol("property")
                        and sub[1] == "Sheet file"
                    ):
                        sheet_file_rel = str(sub[2])
                if not sheet_block_uuid or not sheet_file_rel:
                    continue

                sub_sheet_path = parent_file.parent / sheet_file_rel
                if not sub_sheet_path.exists():
                    logger.warning(f"Sub-sheet not found: {sub_sheet_path}")
                    continue

                parent_uuid_match = re.search(r"\(uuid\s+([0-9a-fA-F-]+)\)", parent_content)
                parent_uuid = parent_uuid_match.group(1) if parent_uuid_match else ""
                target_path = (
                    f"/{parent_uuid}/{sheet_block_uuid}" if parent_uuid else f"/{sheet_block_uuid}"
                )

                sub_content = sub_sheet_path.read_text(encoding="utf-8")

                def _balanced_end(s: str, start: int) -> int:
                    depth = 0
                    for j in range(start, len(s)):
                        if s[j] == "(":
                            depth += 1
                        elif s[j] == ")":
                            depth -= 1
                            if depth == 0:
                                return j
                    return len(s) - 1

                result_parts: List[str] = []
                pos = 0
                changed = False
                while True:
                    idx = sub_content.find("(instances", pos)
                    if idx == -1:
                        result_parts.append(sub_content[pos:])
                        break
                    result_parts.append(sub_content[pos:idx])
                    end = _balanced_end(sub_content, idx)
                    block = sub_content[idx : end + 1]

                    if target_path not in block:
                        existing = re.search(r'\(reference\s+"([^"]+)"\)\s*\(unit\s+(\d+)\)', block)
                        if existing:
                            new_entry = (
                                f'(path "{target_path}" (reference "{existing.group(1)}") '
                                f"(unit {existing.group(2)}))"
                            )
                            proj_start = block.find("(project ")
                            if proj_start != -1:
                                proj_end = _balanced_end(block, proj_start)
                                block = block[:proj_end] + " " + new_entry + block[proj_end:]
                                changed = True
                    result_parts.append(block)
                    pos = end + 1

                if changed:
                    sub_sheet_path.write_text("".join(result_parts), encoding="utf-8")
                    modified_sheets.append(str(sub_sheet_path))
                    logger.info(
                        f"Fixed instances in {sub_sheet_path} for sheet-block {sheet_block_uuid}"
                    )

        except Exception as e:
            logger.error(f"Error fixing sub-sheet instances: {e}")
        return modified_sheets
