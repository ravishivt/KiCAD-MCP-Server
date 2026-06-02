"""
Schematic field-placement & layout-check commands.

Tools:
  - set_schematic_property_position:          move one Reference/Value field
  - batch_set_schematic_property_positions:   move many fields in one file read/write
  - check_schematic_layout:                   report layout violations (out-of-bounds,
                                              overlaps, fields inside bodies, label clutter,
                                              stray wires); optional autofix
  - autoplace_schematic_fields:               auto-position Ref/Value fields outside the
                                              component body and any attached net labels

This module is self-contained: it gathers the enriched component/label data it needs
(body bounding boxes, field positions, pin tips) directly from the schematic + PinLocator,
rather than depending on the output shape of other handlers.
"""

import logging
import math
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from commands.pin_locator import PinLocator
from commands.schematic import SchematicManager

logger = logging.getLogger("kicad_interface")

_GRID = 1.27  # 50-mil KiCad schematic grid (mm)
_BODY_PAD_MM = 1.27

_KICAD_INTERNAL_PROPS = frozenset(
    {"ki_keywords", "ki_description", "ki_fp_filters", "ki_locked", "ki_model"}
)

# Paper sizes (landscape, mm). Border frame is ~12.7mm from each edge.
_PAPER_DIMS = {
    "A4": (297.0, 210.0),
    "A3": (420.0, 297.0),
    "A2": (594.0, 420.0),
    "A1": (841.0, 594.0),
    "A0": (1189.0, 841.0),
    "A": (279.4, 215.9),
    "B": (431.8, 279.4),
    "C": (558.8, 431.8),
    "D": (863.6, 558.8),
    "E": (1117.6, 863.6),
}


# ── Text S-expression helpers (ported standalone to avoid importing KiCADInterface) ──


def _find_matching_paren(s: str, start: int) -> int:
    """Return index of the ')' matching the '(' at position *start*, or -1."""
    depth = 0
    for i in range(start, len(s)):
        if s[i] == "(":
            depth += 1
        elif s[i] == ")":
            depth -= 1
            if depth == 0:
                return i
    return -1


def _find_placed_symbol_block(content: str, reference: str) -> Tuple[Optional[str], int, int]:
    """Find the placed symbol block for *reference*. Returns (block, start, end) or (None, -1, -1)."""
    lib_sym_pos = content.find("(lib_symbols")
    lib_sym_end = _find_matching_paren(content, lib_sym_pos) if lib_sym_pos >= 0 else -1
    pattern = re.compile(r'\(symbol\s+\(lib_id\s+"')
    search_start = 0
    while True:
        m = pattern.search(content, search_start)
        if not m:
            break
        pos = m.start()
        if lib_sym_pos >= 0 and lib_sym_pos <= pos <= lib_sym_end:
            search_start = lib_sym_end + 1
            continue
        end = _find_matching_paren(content, pos)
        if end < 0:
            search_start = pos + 1
            continue
        block_text = content[pos : end + 1]
        if re.search(r'\(property\s+"Reference"\s+"' + re.escape(reference) + r'"', block_text):
            return block_text, pos, end
        search_start = end + 1
    return None, -1, -1


def _extract_component_properties(block_text: str, exclude_internal: bool = True) -> Dict[str, str]:
    """Extract {name: value} for all (property "name" "value" ...) entries in a symbol block."""
    props = {}
    for m in re.finditer(r'\(property\s+"([^"]*)"\s+"([^"]*)"', block_text):
        name, value = m.group(1), m.group(2)
        if exclude_internal and name in _KICAD_INTERNAL_PROPS:
            continue
        props[name] = value
    return props


def _extract_property_position(block_text: str, property_name: str) -> Optional[Dict[str, float]]:
    """Return {"x","y","angle"} of a named property's (at ...), or None."""
    pat = re.compile(
        r'\(property\s+"'
        + re.escape(property_name)
        + r'"\s+"[^"]*"\s+\(at\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\)'
    )
    m = pat.search(block_text)
    if m:
        return {"x": float(m.group(1)), "y": float(m.group(2)), "angle": float(m.group(3))}
    return None


def _extract_property_visible(block_text: str, property_name: str) -> bool:
    """True if the named property is visible (no hide flag)."""
    m = re.search(r'\(property\s+"' + re.escape(property_name) + r'"', block_text)
    if not m:
        return True
    end = _find_matching_paren(block_text, m.start())
    if end < 0:
        return True
    prop_sub = block_text[m.start() : end + 1]
    return "(hide yes)" not in prop_sub and "(hide)" not in prop_sub


def _get_sheet_usable_area(schematic_path) -> Tuple[float, float, float, float]:
    """Return (left, top, right, bottom) usable bounds in mm for the sheet's paper size."""
    border = 12.7
    width, height = 297.0, 210.0  # default A4
    try:
        with open(schematic_path, "r", encoding="utf-8") as f:
            content = f.read(4096)
        m = re.search(r'\(paper\s+"([^"]+)"', content)
        if m and m.group(1).strip() in _PAPER_DIMS:
            width, height = _PAPER_DIMS[m.group(1).strip()]
    except Exception:
        pass
    return (border, border, width - border, height - border)


def _apply_visibility(block: str, property_name: str, visible: bool) -> str:
    """Add or remove a (hide yes) flag on a property's (effects ...) sub-expression."""
    m = re.search(r'\(property\s+"' + re.escape(property_name) + r'"', block)
    if not m:
        return block
    ps = m.start()
    pe = _find_matching_paren(block, ps)
    if pe < 0:
        return block
    prop_sub = block[ps : pe + 1]
    is_hidden = "(hide yes)" in prop_sub or "(hide)" in prop_sub
    if not visible and not is_hidden:
        em = re.search(r"\(effects", prop_sub)
        if em:
            es = em.start()
            ee = _find_matching_paren(prop_sub, es)
            if ee >= 0:
                prop_sub = prop_sub[:es] + prop_sub[es:ee] + " (hide yes))" + prop_sub[ee + 1 :]
    elif visible and is_hidden:
        for tok in (" (hide yes)", "(hide yes) ", "(hide yes)", " (hide)", "(hide) ", "(hide)"):
            prop_sub = prop_sub.replace(tok, "")
    return block[:ps] + prop_sub + block[pe + 1 :]


def _move_property_in_block(block_text, property_name, x, y, angle, visible) -> Tuple[str, int]:
    """Replace a property's (at ...) and apply visibility. Returns (new_block, n_substitutions)."""
    prop_pat = re.compile(
        r'(\(property\s+"'
        + re.escape(property_name)
        + r'"\s+"[^"]*"\s+)\(at\s+[-\d.]+\s+[-\d.]+\s+[-\d.]+\)'
    )
    new_block, n_subs = prop_pat.subn(r"\g<1>" + f"(at {x} {y} {angle})", block_text)
    if n_subs == 0:
        return block_text, 0
    return _apply_visibility(new_block, property_name, visible), n_subs


def _find_project_root(start_dir: Path) -> Path:
    """Walk up from *start_dir* to the nearest dir containing a .kicad_pro (else start_dir)."""
    current = start_dir.resolve()
    while True:
        if list(current.glob("*.kicad_pro")):
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent
    return start_dir


def _find_facing_label(sch_path, net_name, position, orientation, proximity_mm=14.0):
    """Return [x, y] of an existing label for *net_name* that faces *position*, else None.

    "Facing" = within proximity_mm and oriented 180° opposite, so a single wire between
    the two pins is cleaner than two overlapping labels.
    """
    try:
        content = sch_path.read_text(encoding="utf-8")
        pat = re.compile(r'\(label\s+"([^"]+)"\s+\(at\s+([-\d.]+)\s+([-\d.]+)\s+([\d.]+)\)')
        px, py = float(position[0]), float(position[1])
        facing = (int(round(orientation)) % 360 + 180) % 360
        for m in pat.finditer(content):
            if m.group(1) != net_name:
                continue
            lx, ly, la = float(m.group(2)), float(m.group(3)), float(m.group(4))
            if math.hypot(lx - px, ly - py) > proximity_mm:
                continue
            if int(round(la)) % 360 == facing:
                return [lx, ly]
    except Exception:
        pass
    return None


# ── Enriched data gathering (replicates list_schematic_components' fork enrichment) ──


def _gather_components(
    schematic, sch_path: Path, raw_content: str, locator: PinLocator
) -> List[Dict[str, Any]]:
    """Build enriched component dicts: position, value, libId, pins, body_bbox, ref/value_field."""
    components: List[Dict[str, Any]] = []
    for symbol in schematic.symbol:
        if not hasattr(symbol.property, "Reference"):
            continue
        ref = symbol.property.Reference.value
        if ref.startswith("_TEMPLATE"):
            continue
        lib_id = symbol.lib_id.value if hasattr(symbol, "lib_id") else ""
        value = symbol.property.Value.value if hasattr(symbol.property, "Value") else ""
        position = symbol.at.value if hasattr(symbol, "at") else [0, 0, 0]

        comp: Dict[str, Any] = {
            "reference": ref,
            "libId": lib_id,
            "value": value,
            "position": {"x": float(position[0]), "y": float(position[1])},
            "rotation": float(position[2]) if len(position) > 2 else 0,
        }

        block_text, _, _ = _find_placed_symbol_block(raw_content, ref)
        if block_text:
            ref_pos = _extract_property_position(block_text, "Reference")
            if ref_pos:
                ref_pos["visible"] = _extract_property_visible(block_text, "Reference")
                comp["ref_field"] = ref_pos
            val_pos = _extract_property_position(block_text, "Value")
            if val_pos:
                val_pos["visible"] = _extract_property_visible(block_text, "Value")
                comp["value_field"] = val_pos

        try:
            all_pins = locator.get_all_symbol_pins(sch_path, ref)
            if all_pins:
                pins_def = locator.get_symbol_pins(sch_path, lib_id) or {}
                pin_list = []
                for pin_num, coords in all_pins.items():
                    pin_info = {"number": pin_num, "position": {"x": coords[0], "y": coords[1]}}
                    if pin_num in pins_def:
                        pin_info["name"] = pins_def[pin_num].get("name", pin_num)
                    pin_list.append(pin_info)
                comp["pins"] = pin_list
                xs = [p["position"]["x"] for p in pin_list]
                ys = [p["position"]["y"] for p in pin_list]
                comp["body_bbox"] = {
                    "x_min": min(xs) - _BODY_PAD_MM,
                    "y_min": min(ys) - _BODY_PAD_MM,
                    "x_max": max(xs) + _BODY_PAD_MM,
                    "y_max": max(ys) + _BODY_PAD_MM,
                }
        except Exception:
            pass  # pin lookup is best-effort

        components.append(comp)
    return components


def _gather_labels(schematic) -> List[Dict[str, Any]]:
    """Net + global labels as {type, name, position, angle}."""
    labels = []
    for attr, kind in (("label", "net"), ("global_label", "global")):
        for lbl in getattr(schematic, attr, []):
            if not hasattr(lbl, "value"):
                continue
            pos = lbl.at.value if hasattr(lbl, "at") and hasattr(lbl.at, "value") else [0, 0, 0]
            labels.append(
                {
                    "type": kind,
                    "name": lbl.value,
                    "position": {"x": float(pos[0]), "y": float(pos[1])},
                    "angle": float(pos[2]) if len(pos) > 2 else 0,
                }
            )
    return labels


def _bbox_overlaps(a, b, margin=0.0):
    return (
        a["x_min"] - margin < b["x_max"]
        and a["x_max"] + margin > b["x_min"]
        and a["y_min"] - margin < b["y_max"]
        and a["y_max"] + margin > b["y_min"]
    )


def _point_in_bbox(px, py, bbox):
    return bbox["x_min"] <= px <= bbox["x_max"] and bbox["y_min"] <= py <= bbox["y_max"]


class SchematicFieldLayoutCommands:
    """Handlers for schematic field placement and layout checking."""

    def set_schematic_property_position(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Move a symbol's Reference or Value property field to a new coordinate."""
        logger.info("Setting schematic property position")
        try:
            schematic_path = params.get("schematicPath")
            reference = params.get("reference")
            property_name = params.get("property")
            x = params.get("x")
            y = params.get("y")
            angle = params.get("angle", 0)
            visible = params.get("visible", True)

            if not all([schematic_path, reference, property_name, x is not None, y is not None]):
                return {
                    "success": False,
                    "message": "Missing required parameters: schematicPath, reference, property, x, y",
                }
            if property_name not in ("Reference", "Value"):
                return {"success": False, "message": "property must be 'Reference' or 'Value'"}

            sch_path = Path(schematic_path)
            if not sch_path.exists():
                return {"success": False, "message": f"Schematic not found: {schematic_path}"}

            content = sch_path.read_text(encoding="utf-8")
            block_text, block_start, block_end = _find_placed_symbol_block(content, reference)
            if block_text is None:
                return {
                    "success": False,
                    "message": f"Component '{reference}' not found in schematic",
                }

            old_pos = _extract_property_position(block_text, property_name)
            new_block, n_subs = _move_property_in_block(
                block_text, property_name, x, y, angle, visible
            )
            if n_subs == 0:
                return {
                    "success": False,
                    "message": f"Property '{property_name}' not found in {reference}",
                }

            new_content = content[:block_start] + new_block + content[block_end + 1 :]
            sch_path.write_text(new_content, encoding="utf-8")

            old_str = (
                f"({old_pos['x']}, {old_pos['y']}, {old_pos['angle']}°)" if old_pos else "unknown"
            )
            return {
                "success": True,
                "message": f"Moved {reference}.{property_name} from {old_str} to ({x}, {y}, {angle}°)",
            }
        except Exception as e:
            logger.error(f"Error setting property position: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def batch_set_schematic_property_positions(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Batch-move Reference/Value property fields for many components in one read/write."""
        logger.info("Batch setting schematic property positions")
        try:
            schematic_path = params.get("schematicPath")
            updates = params.get("updates", [])

            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}
            if not updates:
                return {"success": False, "message": "updates list is required"}

            sch_path = Path(schematic_path)
            if not sch_path.exists():
                return {"success": False, "message": f"Schematic not found: {schematic_path}"}

            content = sch_path.read_text(encoding="utf-8")
            applied: List[Dict[str, Any]] = []
            failed: List[Dict[str, Any]] = []

            for upd in updates:
                reference = upd.get("reference")
                property_name = upd.get("property")
                x = upd.get("x")
                y = upd.get("y")
                angle = upd.get("angle", 0)
                visible = upd.get("visible", True)

                if not reference or not property_name or x is None or y is None:
                    failed.append(
                        {
                            "reference": reference,
                            "property": property_name,
                            "reason": "Missing required fields: reference, property, x, y",
                        }
                    )
                    continue
                if property_name not in ("Reference", "Value"):
                    failed.append(
                        {
                            "reference": reference,
                            "property": property_name,
                            "reason": "property must be 'Reference' or 'Value'",
                        }
                    )
                    continue

                block_text, block_start, block_end = _find_placed_symbol_block(content, reference)
                if block_text is None:
                    failed.append(
                        {
                            "reference": reference,
                            "property": property_name,
                            "reason": f"Component '{reference}' not found in schematic",
                        }
                    )
                    continue

                new_block, n_subs = _move_property_in_block(
                    block_text, property_name, x, y, angle, visible
                )
                if n_subs == 0:
                    failed.append(
                        {
                            "reference": reference,
                            "property": property_name,
                            "reason": f"Property '{property_name}' not found in {reference} block",
                        }
                    )
                    continue

                content = content[:block_start] + new_block + content[block_end + 1 :]
                applied.append(
                    {
                        "reference": reference,
                        "property": property_name,
                        "x": x,
                        "y": y,
                        "angle": angle,
                        "visible": visible,
                    }
                )

            if applied:
                sch_path.write_text(content, encoding="utf-8")

            return {
                "success": len(failed) == 0,
                "applied": applied,
                "failed": failed,
                "applied_count": len(applied),
                "failed_count": len(failed),
            }
        except Exception as e:
            logger.error(f"Error in batch_set_schematic_property_positions: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def check_schematic_layout(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze a schematic for layout violations; optionally autofix field positions."""
        logger.info("Checking schematic layout")
        try:
            schematic_path = params.get("schematicPath")
            autofix = params.get("autofix", False)
            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}

            sch_path = Path(schematic_path)
            if not sch_path.exists():
                return {"success": False, "message": f"Schematic not found: {schematic_path}"}

            left_b, top_b, right_b, bottom_b = _get_sheet_usable_area(schematic_path)

            schematic = SchematicManager.load_schematic(schematic_path)
            if not schematic:
                return {"success": False, "message": "Failed to load schematic"}
            raw_content = sch_path.read_text(encoding="utf-8")
            locator = PinLocator()

            components = _gather_components(schematic, sch_path, raw_content, locator)
            labels = _gather_labels(schematic)

            violations: List[Dict[str, Any]] = []
            chars_per_mm = 1.5

            comp_bboxes: Dict[str, Dict[str, float]] = {}
            for c in components:
                if "body_bbox" in c:
                    comp_bboxes[c["reference"]] = c["body_bbox"]
                else:
                    cx, cy = c["position"]["x"], c["position"]["y"]
                    comp_bboxes[c["reference"]] = {
                        "x_min": cx - 2.54,
                        "y_min": cy - 2.54,
                        "x_max": cx + 2.54,
                        "y_max": cy + 2.54,
                    }

            # 1. Out-of-bounds components
            for c in components:
                bb = comp_bboxes.get(c["reference"])
                if bb and (
                    bb["x_min"] < left_b
                    or bb["x_max"] > right_b
                    or bb["y_min"] < top_b
                    or bb["y_max"] > bottom_b
                ):
                    violations.append(
                        {
                            "type": "out_of_bounds_component",
                            "affected_refs": [c["reference"]],
                            "position": c["position"],
                            "description": f"{c['reference']} body bbox extends outside sheet usable area "
                            f"[{left_b},{top_b},{right_b},{bottom_b}]",
                        }
                    )

            # 2. Out-of-bounds labels
            for lbl in labels:
                if lbl.get("type") not in ("net", "global"):
                    continue
                name = lbl.get("name", "")
                lx, ly = lbl["position"]["x"], lbl["position"]["y"]
                angle = lbl.get("angle", 0)
                text_len = len(name) * chars_per_mm
                rad = math.radians(angle)
                end_x = lx + text_len * math.cos(rad)
                end_y = ly + text_len * math.sin(rad)
                if (
                    min(lx, end_x) < left_b
                    or max(lx, end_x) > right_b
                    or min(ly, end_y) < top_b
                    or max(ly, end_y) > bottom_b
                ):
                    violations.append(
                        {
                            "type": "out_of_bounds_label",
                            "affected_refs": [name],
                            "position": lbl["position"],
                            "description": f"Label '{name}' at ({lx:.1f},{ly:.1f}) extends outside sheet boundary",
                        }
                    )

            # 3. Overlapping component bodies (within 2mm)
            ref_list = list(comp_bboxes.keys())
            for i in range(len(ref_list)):
                for j in range(i + 1, len(ref_list)):
                    ra, rb = ref_list[i], ref_list[j]
                    if _bbox_overlaps(comp_bboxes[ra], comp_bboxes[rb], margin=2.0):
                        violations.append(
                            {
                                "type": "overlapping_components",
                                "affected_refs": [ra, rb],
                                "position": None,
                                "description": f"{ra} and {rb} bodies overlap or are within 2mm",
                            }
                        )

            # 4. Ref/Val text inside its own parent body (with suggested fix)
            for c in components:
                parent_bb = comp_bboxes.get(c["reference"])
                if not parent_bb:
                    continue
                cx_c, cy_c = c["position"]["x"], c["position"]["y"]
                off = 2.54
                num_pins_c = len(c.get("pins", []))
                vertical_axis = (parent_bb["y_max"] - parent_bb["y_min"]) > (
                    parent_bb["x_max"] - parent_bb["x_min"]
                )
                for field_key, label in [("ref_field", "Reference"), ("value_field", "Value")]:
                    field = c.get(field_key)
                    if field and _point_in_bbox(field["x"], field["y"], parent_bb):
                        if num_pins_c == 2 and vertical_axis:
                            fix_x = (
                                round(cx_c - off, 4)
                                if label == "Reference"
                                else round(cx_c + off, 4)
                            )
                            fix_y = cy_c
                        elif num_pins_c == 2 and not vertical_axis:
                            fix_x = cx_c
                            fix_y = (
                                round(cy_c - off, 4)
                                if label == "Reference"
                                else round(cy_c + off, 4)
                            )
                        else:
                            fix_x = cx_c
                            fix_y = (
                                round(parent_bb["y_min"] - off, 4)
                                if label == "Reference"
                                else round(parent_bb["y_max"] + off, 4)
                            )
                        violations.append(
                            {
                                "type": "text_inside_parent_body",
                                "affected_refs": [c["reference"]],
                                "position": {"x": field["x"], "y": field["y"]},
                                "description": f"{c['reference']} {label} text is inside its own body bbox",
                                "suggested_fix": {
                                    "reference": c["reference"],
                                    "property": label,
                                    "x": fix_x,
                                    "y": fix_y,
                                    "angle": 0,
                                },
                            }
                        )

            # 5. Ref/Val text overlapping another component's body
            for c in components:
                for field_key, label in [("ref_field", "Reference"), ("value_field", "Value")]:
                    field = c.get(field_key)
                    if not field:
                        continue
                    for other_ref, other_bb in comp_bboxes.items():
                        if other_ref == c["reference"]:
                            continue
                        if _point_in_bbox(field["x"], field["y"], other_bb):
                            violations.append(
                                {
                                    "type": "text_overlaps_other_body",
                                    "affected_refs": [c["reference"], other_ref],
                                    "position": {"x": field["x"], "y": field["y"]},
                                    "description": f"{c['reference']} {label} text overlaps body of {other_ref}",
                                }
                            )

            # 6. Field-text bbox overlap between components (with suggested fix)
            char_w, text_h, margin = 0.75, 1.5, 0.5

            def field_text_bbox(fx, fy, text):
                half_w = max(len(str(text)) * char_w / 2.0, 1.0)
                half_h = text_h / 2.0
                return {
                    "x_min": fx - half_w,
                    "x_max": fx + half_w,
                    "y_min": fy - half_h,
                    "y_max": fy + half_h,
                }

            all_fields = []
            for c in components:
                for field_key, label in [("ref_field", "Reference"), ("value_field", "Value")]:
                    field = c.get(field_key)
                    if not field or field.get("visible") is False:
                        continue
                    text_val = c["reference"] if label == "Reference" else c.get("value", "")
                    all_fields.append((c["reference"], label, text_val, field["x"], field["y"]))

            for i in range(len(all_fields)):
                ref_a, fld_a, txt_a, fx_a, fy_a = all_fields[i]
                bb_a = field_text_bbox(fx_a, fy_a, txt_a)
                for j in range(i + 1, len(all_fields)):
                    ref_b, fld_b, txt_b, fx_b, fy_b = all_fields[j]
                    bb_b = field_text_bbox(fx_b, fy_b, txt_b)
                    if _bbox_overlaps(bb_a, bb_b, margin=margin):
                        dx, dy = fx_a - fx_b, fy_a - fy_b
                        dist = math.sqrt(dx * dx + dy * dy) or 1.0
                        sep = 3.0
                        violations.append(
                            {
                                "type": "field_text_overlap",
                                "affected_refs": [ref_a, ref_b],
                                "position": {"x": (fx_a + fx_b) / 2, "y": (fy_a + fy_b) / 2},
                                "description": f"{ref_a}.{fld_a} text overlaps {ref_b}.{fld_b} text",
                                "suggested_fix": {
                                    "reference": ref_a,
                                    "property": fld_a,
                                    "x": round(fx_a + sep * dx / dist, 4),
                                    "y": round(fy_a + sep * dy / dist, 4),
                                    "angle": 0,
                                },
                            }
                        )

            # 7. Net-label proximity / overlap (duplicate detection)
            label_char_w, label_half_h, label_gap = 1.27, 0.7, 0.5

            def label_text_bbox(lx, ly, name, angle):
                tw = max(len(name), 1) * label_char_w
                hh = label_half_h
                a = int(round(angle)) % 360
                if a == 0:
                    return {"x_min": lx, "y_min": ly - hh, "x_max": lx + tw, "y_max": ly + hh}
                if a == 180:
                    return {"x_min": lx - tw, "y_min": ly - hh, "x_max": lx, "y_max": ly + hh}
                if a == 90:
                    return {"x_min": lx - hh, "y_min": ly - tw, "x_max": lx + hh, "y_max": ly}
                if a == 270:
                    return {"x_min": lx - hh, "y_min": ly, "x_max": lx + hh, "y_max": ly + tw}
                rad = math.radians(angle)
                ex, ey = lx + tw * math.cos(rad), ly + tw * math.sin(rad)
                return {
                    "x_min": min(lx, ex) - hh,
                    "y_min": min(ly, ey) - hh,
                    "x_max": max(lx, ex) + hh,
                    "y_max": max(ly, ey) + hh,
                }

            net_labels_for_check = [lb for lb in labels if lb.get("type") in ("net", "global")]
            label_bb_list = [
                (
                    lb,
                    label_text_bbox(
                        lb["position"]["x"],
                        lb["position"]["y"],
                        lb.get("name", ""),
                        lb.get("angle", 0),
                    ),
                )
                for lb in net_labels_for_check
            ]
            for i in range(len(label_bb_list)):
                lbl_a, bb_a = label_bb_list[i]
                for j in range(i + 1, len(label_bb_list)):
                    lbl_b, bb_b = label_bb_list[j]
                    if _bbox_overlaps(bb_a, bb_b, margin=label_gap):
                        same_net = lbl_a.get("name") == lbl_b.get("name")
                        dist = (
                            (lbl_a["position"]["x"] - lbl_b["position"]["x"]) ** 2
                            + (lbl_a["position"]["y"] - lbl_b["position"]["y"]) ** 2
                        ) ** 0.5
                        is_duplicate = same_net and dist < 0.3
                        violation: Dict[str, Any] = {
                            "type": "label_overlap",
                            "affected_refs": [lbl_a.get("name"), lbl_b.get("name")],
                            "position": {
                                "x": (lbl_a["position"]["x"] + lbl_b["position"]["x"]) / 2,
                                "y": (lbl_a["position"]["y"] + lbl_b["position"]["y"]) / 2,
                            },
                            "description": (
                                f"Label '{lbl_a['name']}' overlaps/too close to '{lbl_b['name']}' — "
                                + (
                                    "exact duplicate: delete one with delete_schematic_net_label"
                                    if is_duplicate
                                    else "move components apart or use a shared net label"
                                )
                            ),
                        }
                        if is_duplicate:
                            violation["suggested_delete_label"] = {
                                "net": lbl_b.get("name"),
                                "position": lbl_b["position"],
                                "angle": lbl_b.get("angle", 0),
                                "action": "delete_schematic_net_label",
                            }
                        violations.append(violation)

            # 8. Stray wire detection
            self._check_stray_wires(schematic, sch_path, raw_content, labels, locator, violations)

            autofix_applied: List[Dict[str, Any]] = []
            autofix_failed: List[Dict[str, Any]] = []
            if autofix:
                fixable = [v["suggested_fix"] for v in violations if "suggested_fix" in v]
                if fixable:
                    fix_result = self.batch_set_schematic_property_positions(
                        {"schematicPath": schematic_path, "updates": fixable}
                    )
                    autofix_applied = fix_result.get("applied", [])
                    autofix_failed = fix_result.get("failed", [])
                    applied_keys = {(a["reference"], a["property"]) for a in autofix_applied}
                    violations = [
                        v
                        for v in violations
                        if "suggested_fix" not in v
                        or (v["suggested_fix"]["reference"], v["suggested_fix"]["property"])
                        not in applied_keys
                    ]

            result = {
                "success": True,
                "violations": violations,
                "violation_count": len(violations),
                "sheet_usable_area": {
                    "left": left_b,
                    "top": top_b,
                    "right": right_b,
                    "bottom": bottom_b,
                },
            }
            if autofix:
                result["autofix_applied_count"] = len(autofix_applied)
                result["autofix_failed_count"] = len(autofix_failed)
                if autofix_failed:
                    result["autofix_failed"] = autofix_failed
            return result

        except Exception as e:
            logger.error(f"Error in check_schematic_layout: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    @staticmethod
    def _check_stray_wires(schematic, sch_path, raw_content, labels, locator, violations):
        """Append stray_wire violations for wire endpoints with no connection."""
        try:
            import sexpdata
            from sexpdata import Symbol

            sch_sexp = sexpdata.loads(raw_content)
            tol = 0.3

            wire_segments = []
            wire_endpoints = []
            for item in sch_sexp:
                if not (isinstance(item, list) and len(item) > 0 and item[0] == Symbol("wire")):
                    continue
                pts = next(
                    (
                        p
                        for p in item
                        if isinstance(p, list) and len(p) > 0 and p[0] == Symbol("pts")
                    ),
                    None,
                )
                if not pts:
                    continue
                xy_items = [
                    p for p in pts if isinstance(p, list) and len(p) >= 3 and p[0] == Symbol("xy")
                ]
                if len(xy_items) >= 2:
                    x1, y1 = float(xy_items[0][1]), float(xy_items[0][2])
                    x2, y2 = float(xy_items[1][1]), float(xy_items[1][2])
                    wire_segments.append((x1, y1, x2, y2))
                    wire_endpoints.append((x1, y1))
                    wire_endpoints.append((x2, y2))

            if not wire_segments:
                return

            connected_pts: set = set()
            try:
                for sc in schematic.symbol:
                    if not hasattr(sc.property, "Reference"):
                        continue
                    sref = sc.property.Reference.value
                    if sref.startswith("_TEMPLATE") or sref.startswith("#"):
                        continue
                    for sp in (locator.get_all_symbol_pins(sch_path, sref) or {}).values():
                        spx = float(sp[0]) if isinstance(sp, (list, tuple)) else float(sp["x"])
                        spy = float(sp[1]) if isinstance(sp, (list, tuple)) else float(sp["y"])
                        connected_pts.add((round(spx, 2), round(spy, 2)))
            except Exception as pe:
                logger.warning(f"Stray wire: pin collection failed: {pe}")

            for lbl in labels:
                connected_pts.add((round(lbl["position"]["x"], 2), round(lbl["position"]["y"], 2)))

            for item in sch_sexp:
                if isinstance(item, list) and len(item) > 0 and item[0] == Symbol("junction"):
                    at = next(
                        (
                            p
                            for p in item
                            if isinstance(p, list) and len(p) >= 3 and p[0] == Symbol("at")
                        ),
                        None,
                    )
                    if at:
                        connected_pts.add((round(float(at[1]), 2), round(float(at[2]), 2)))

            def is_connected(ex, ey):
                ex_r, ey_r = round(ex, 2), round(ey, 2)
                for cx, cy in connected_pts:
                    if abs(ex_r - cx) <= tol and abs(ey_r - cy) <= tol:
                        return True
                count = sum(
                    1
                    for (wx, wy) in wire_endpoints
                    if abs(round(wx, 2) - ex_r) <= tol and abs(round(wy, 2) - ey_r) <= tol
                )
                return count >= 2

            for x1, y1, x2, y2 in wire_segments:
                d1, d2 = is_connected(x1, y1), is_connected(x2, y2)
                if not d1 and not d2:
                    violations.append(
                        {
                            "type": "stray_wire",
                            "affected_refs": [],
                            "position": {"x": (x1 + x2) / 2, "y": (y1 + y2) / 2},
                            "description": f"Isolated wire ({x1:.2f},{y1:.2f})-({x2:.2f},{y2:.2f}) has no "
                            "connection at either endpoint. Delete it with delete_schematic_wire.",
                        }
                    )
                elif not d1:
                    violations.append(
                        {
                            "type": "stray_wire",
                            "affected_refs": [],
                            "position": {"x": x1, "y": y1},
                            "description": f"Wire endpoint ({x1:.2f},{y1:.2f}) has no connection.",
                        }
                    )
                elif not d2:
                    violations.append(
                        {
                            "type": "stray_wire",
                            "affected_refs": [],
                            "position": {"x": x2, "y": y2},
                            "description": f"Wire endpoint ({x2:.2f},{y2:.2f}) has no connection.",
                        }
                    )
        except Exception as we:
            logger.warning(f"Stray wire check failed: {we}")

    def autoplace_schematic_fields(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Re-position Reference and Value fields outside the body and any attached net labels."""
        logger.info("Auto-placing schematic fields")
        try:
            schematic_path = params.get("schematicPath")
            references_filter = params.get("references")
            clearance = float(params.get("clearance", _GRID))

            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}
            sch_path = Path(schematic_path)
            if not sch_path.exists():
                return {"success": False, "message": f"Schematic not found: {schematic_path}"}

            chars_per_mm, text_height = 1.5, 1.27

            def snap(val):
                return round(round(val / _GRID) * _GRID, 4)

            def label_bbox(lx, ly, angle, name):
                length = max(len(name), 1) * chars_per_mm + 1.0
                half_h = text_height / 2.0
                a = round(angle / 90) * 90 % 360
                if a == 0:
                    return {
                        "x_min": lx,
                        "y_min": ly - half_h,
                        "x_max": lx + length,
                        "y_max": ly + half_h,
                    }
                if a == 90:
                    return {
                        "x_min": lx - half_h,
                        "y_min": ly - length,
                        "x_max": lx + half_h,
                        "y_max": ly,
                    }
                if a == 180:
                    return {
                        "x_min": lx - length,
                        "y_min": ly - half_h,
                        "x_max": lx,
                        "y_max": ly + half_h,
                    }
                return {
                    "x_min": lx - half_h,
                    "y_min": ly,
                    "x_max": lx + half_h,
                    "y_max": ly + length,
                }

            def union(bb, other):
                return {
                    "x_min": min(bb["x_min"], other["x_min"]),
                    "y_min": min(bb["y_min"], other["y_min"]),
                    "x_max": max(bb["x_max"], other["x_max"]),
                    "y_max": max(bb["y_max"], other["y_max"]),
                }

            def field_bbox(fx, fy, text):
                half_w = max(len(str(text)), 1) * 0.75 / 2.0
                half_h = text_height / 2.0
                return {
                    "x_min": fx - half_w,
                    "y_min": fy - half_h,
                    "x_max": fx + half_w,
                    "y_max": fy + half_h,
                }

            schematic = SchematicManager.load_schematic(schematic_path)
            if not schematic:
                return {"success": False, "message": "Failed to load schematic"}
            raw_content = sch_path.read_text(encoding="utf-8")
            locator = PinLocator()

            components = _gather_components(schematic, sch_path, raw_content, locator)
            if references_filter:
                components = [c for c in components if c["reference"] in references_filter]
            net_labels = [
                lb for lb in _gather_labels(schematic) if lb.get("type") in ("net", "global")
            ]

            comp_ext_bboxes: Dict[str, Dict[str, float]] = {}
            comp_pin_map: Dict[str, Dict[str, Any]] = {}

            for comp in components:
                ref = comp["reference"]
                cx, cy = comp["position"]["x"], comp["position"]["y"]
                body_bb = comp.get("body_bbox") or {
                    "x_min": cx - 2.54,
                    "y_min": cy - 2.54,
                    "x_max": cx + 2.54,
                    "y_max": cy + 2.54,
                }
                ext_bb = dict(body_bb)

                all_pins: Dict[str, Any] = {}
                for p in comp.get("pins", []):
                    pnum = str(p.get("number", p.get("name", "")))
                    px = p.get("x", p.get("position", {}).get("x", cx))
                    py = p.get("y", p.get("position", {}).get("y", cy))
                    all_pins[pnum] = [float(px), float(py)]
                if not all_pins:
                    all_pins = locator.get_all_symbol_pins(sch_path, ref) or {}
                comp_pin_map[ref] = all_pins

                for lbl in net_labels:
                    lx, ly = lbl["position"]["x"], lbl["position"]["y"]
                    for pin_coords in all_pins.values():
                        px = (
                            pin_coords[0]
                            if isinstance(pin_coords, (list, tuple))
                            else pin_coords["x"]
                        )
                        py = (
                            pin_coords[1]
                            if isinstance(pin_coords, (list, tuple))
                            else pin_coords["y"]
                        )
                        if abs(lx - px) < 0.6 and abs(ly - py) < 0.6:
                            ext_bb = union(
                                ext_bb, label_bbox(lx, ly, lbl.get("angle", 0), lbl.get("name", ""))
                            )
                            break
                comp_ext_bboxes[ref] = ext_bb

            updates: List[Dict[str, Any]] = []
            placed_field_bboxes: List[Dict[str, float]] = []

            def has_collision(ref_bb, val_bb, exclude_ref):
                for other_ref, other_ext in comp_ext_bboxes.items():
                    if other_ref == exclude_ref:
                        continue
                    if _bbox_overlaps(ref_bb, other_ext, 0.3) or _bbox_overlaps(
                        val_bb, other_ext, 0.3
                    ):
                        return True
                for fb in placed_field_bboxes:
                    if _bbox_overlaps(ref_bb, fb, 0.2) or _bbox_overlaps(val_bb, fb, 0.2):
                        return True
                return False

            for comp in components:
                ref = comp["reference"]
                lib_id = comp.get("libId", "")
                if ref.startswith("#") or ref.startswith("_TEMPLATE"):
                    continue
                cx, cy = comp["position"]["x"], comp["position"]["y"]
                val_text = comp.get("value", ref)

                is_power = lib_id.startswith("kicad_power:") or lib_id.startswith("power:")
                if is_power:
                    ext_bb = dict(
                        comp.get("body_bbox")
                        or {
                            "x_min": cx - 1.27,
                            "y_min": cy - 1.27,
                            "x_max": cx + 1.27,
                            "y_max": cy + 1.27,
                        }
                    )
                    num_pins = 0
                else:
                    ext_bb = comp_ext_bboxes[ref]
                    num_pins = len(comp_pin_map[ref])

                if num_pins == 2:
                    coords = list(comp_pin_map[ref].values())
                    p1x = (
                        float(coords[0][0])
                        if isinstance(coords[0], (list, tuple))
                        else float(coords[0]["x"])
                    )
                    p1y = (
                        float(coords[0][1])
                        if isinstance(coords[0], (list, tuple))
                        else float(coords[0]["y"])
                    )
                    p2x = (
                        float(coords[1][0])
                        if isinstance(coords[1], (list, tuple))
                        else float(coords[1]["x"])
                    )
                    p2y = (
                        float(coords[1][1])
                        if isinstance(coords[1], (list, tuple))
                        else float(coords[1]["y"])
                    )
                    sides = (
                        ["right", "left", "above", "below"]
                        if abs(p1y - p2y) > abs(p1x - p2x)
                        else ["above", "below", "right", "left"]
                    )
                else:
                    sides = ["above", "below", "right", "left"]

                def try_side(side):
                    half_ref_h = text_height / 2.0
                    half_ref_w = max(len(ref), 1) * 0.75 / 2.0
                    half_val_w = max(len(str(val_text)), 1) * 0.75 / 2.0
                    stack = text_height
                    if side == "above":
                        ref_y = snap(ext_bb["y_min"] - half_ref_h - clearance)
                        return cx, ref_y, cx, ref_y - stack
                    if side == "below":
                        ref_y = snap(ext_bb["y_max"] + half_ref_h + clearance)
                        return cx, ref_y, cx, ref_y + stack
                    if side == "right":
                        x0 = ext_bb["x_max"] + clearance
                        ref_y = snap(cy)
                        return snap(x0 + half_ref_w), ref_y, snap(x0 + half_val_w), ref_y + stack
                    x0 = ext_bb["x_min"] - clearance
                    ref_y = snap(cy)
                    return snap(x0 - half_ref_w), ref_y, snap(x0 - half_val_w), ref_y + stack

                ref_x = ref_y = val_x = val_y = ref_bb = val_bb = None
                for side in sides:
                    rx, ry, vx, vy = try_side(side)
                    rb, vb = field_bbox(rx, ry, ref), field_bbox(vx, vy, val_text)
                    if not has_collision(rb, vb, ref):
                        ref_x, ref_y, val_x, val_y, ref_bb, val_bb = rx, ry, vx, vy, rb, vb
                        break
                if ref_x is None:
                    ref_x, ref_y, val_x, val_y = try_side(sides[0])
                    ref_bb, val_bb = field_bbox(ref_x, ref_y, ref), field_bbox(
                        val_x, val_y, val_text
                    )

                placed_field_bboxes.append(ref_bb)
                placed_field_bboxes.append(val_bb)
                updates.append(
                    {"reference": ref, "property": "Reference", "x": ref_x, "y": ref_y, "angle": 0}
                )
                updates.append(
                    {"reference": ref, "property": "Value", "x": val_x, "y": val_y, "angle": 0}
                )

            if not updates:
                return {"success": True, "message": "No components to update.", "updated_count": 0}

            batch_result = self.batch_set_schematic_property_positions(
                {"schematicPath": schematic_path, "updates": updates}
            )
            applied = batch_result.get("applied_count", 0)
            failed = batch_result.get("failed_count", 0)
            return {
                "success": batch_result.get("success", False),
                "message": f"Auto-placed fields for {applied // 2} component(s) "
                f"({applied} fields updated{', ' + str(failed) + ' failed' if failed else ''}).",
                "updated_count": applied,
                "failed_count": failed,
                "failed": batch_result.get("failed", []),
            }

        except Exception as e:
            logger.error(f"Error in autoplace_schematic_fields: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}
