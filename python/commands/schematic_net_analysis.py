"""
Schematic net & design analysis commands.

Read-only tools that summarise schematic connectivity for design review — useful for
an LLM (or human) trying to understand an existing schematic or spot wiring mistakes.

Tools:
  - list_unconnected_pins:  pins with no net and no no-connect marker
  - find_single_pin_nets:   named nets with exactly one connected pin (dangling)
  - classify_nets:          every net tagged power/ground/clock/diff-pair/signal + fan-out
  - get_net_graph:          compact component-to-component adjacency (driver --> loads)
  - get_schematic_summary:  one-shot text summary (component table + net adjacency)
  - get_net_topology:       full trace of one net (wires, labels, pins, dangling ends)

All connectivity comes from the shared ConnectionManager / PinLocator primitives, so
results match the rest of the server's net handling.
"""

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

from commands.connection_schematic import ConnectionManager
from commands.pin_locator import PinLocator
from commands.schematic import SchematicManager

logger = logging.getLogger("kicad_interface")

_DRIVER_TYPES = {"output", "power_out", "tri_state", "open_collector", "open_emitter"}
_LOAD_TYPES = {"input", "passive", "power_in", "no_connect"}

_GND_RE = re.compile(r"^(A?D?P?S?GND|EARTH|AGND|DGND|PGND|SGND)")
_PWR_RE = re.compile(
    r"^(\+?[\d]+V[\d]*[A-Z0-9_]*|VCC|VDD|VIN|VBAT|VREF|AVCC|DVCC|PVCC|3V3|5V|1V8|3\.3V|5\.0V)"
)
_CLK_RE = re.compile(r"(CLK|SCK|MCLK|XTAL|OSC)")


def _collect_net_names(schematic) -> set:
    """All net names declared via local + global labels."""
    names = set()
    for attr in ("label", "global_label"):
        for label in getattr(schematic, attr, []):
            if hasattr(label, "value"):
                names.add(label.value)
    return names


def _pin_metadata(locator: PinLocator, sch_path: Path, ref: str, pin_num: str) -> Dict[str, Any]:
    """{"name", "type", ...} for (ref, pin_num), or {} on miss.

    Reimplements the old PinLocator.get_pin_metadata using upstream primitives so we
    don't have to modify PinLocator itself.
    """
    lib_id = locator._get_lib_id(sch_path, ref)
    if not lib_id:
        return {}
    return locator.get_symbol_pins(sch_path, lib_id).get(str(pin_num), {})


def _build_full_netmap(schematic, schematic_path) -> Dict[Tuple[str, str], str]:
    """{(ref, pin_num_str): net_name} for the whole schematic (inverts get_net_connections)."""
    netmap: Dict[Tuple[str, str], str] = {}
    for net_name in _collect_net_names(schematic):
        for conn in ConnectionManager.get_net_connections(
            schematic, net_name, Path(schematic_path)
        ):
            netmap[(conn["component"], str(conn["pin"]))] = net_name
    return netmap


def _is_power_or_ground(name: str) -> bool:
    n = name.upper()
    return bool(_GND_RE.match(n) or _PWR_RE.match(n))


def _classify_net_type(net_name: str, has_pwr_symbol: bool, all_net_names: set) -> str:
    """Tag a net as ground/power_rail/clock/differential_pair/signal (priority order)."""
    n = net_name.upper()
    if _GND_RE.match(n):
        return "ground"
    if has_pwr_symbol or _PWR_RE.match(n):
        return "power_rail"
    if _CLK_RE.search(n):
        return "clock"
    if (net_name.endswith("_P") or net_name.endswith("_N")) and (
        net_name[:-2] + "_N" in all_net_names or net_name[:-2] + "_P" in all_net_names
    ):
        return "differential_pair"
    if (net_name.endswith("+") or net_name.endswith("-")) and (
        net_name[:-1] + "-" in all_net_names or net_name[:-1] + "+" in all_net_names
    ):
        return "differential_pair"
    return "signal"


def _get_prop(symbol, name: str, default: str = "-") -> str:
    """Read a placed symbol's property value (e.g. MPN, Description) via skip, or default."""
    try:
        val = getattr(symbol.property, name).value
        return val if val else default
    except Exception:
        return default


class SchematicNetAnalysisCommands:
    """Handlers for read-only schematic net/design analysis tools."""

    def list_unconnected_pins(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """List pins with no net connection and no no-connect marker."""
        logger.info("Listing unconnected pins")
        try:
            schematic_path = params.get("schematicPath")
            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}

            sch_path = Path(schematic_path)
            schematic = SchematicManager.load_schematic(schematic_path)
            if not schematic:
                return {"success": False, "message": "Failed to load schematic"}

            netlist = ConnectionManager.generate_netlist(schematic, sch_path)
            connected_pins = set()
            for net in netlist.get("nets", []):
                for conn in net.get("connections", []):
                    connected_pins.add((conn.get("component"), str(conn.get("pin"))))

            no_connect_positions = set()
            for nc in getattr(schematic, "no_connect", []):
                if hasattr(nc, "at") and hasattr(nc.at, "value"):
                    pos = nc.at.value
                    no_connect_positions.add((round(float(pos[0]), 2), round(float(pos[1]), 2)))

            locator = PinLocator()
            unconnected: List[Dict[str, Any]] = []

            for symbol in schematic.symbol:
                if not hasattr(symbol.property, "Reference"):
                    continue
                ref = symbol.property.Reference.value
                if ref.startswith("_TEMPLATE") or ref.startswith("#"):
                    continue
                lib_id = symbol.lib_id.value if hasattr(symbol, "lib_id") else ""
                if lib_id.startswith("power:"):
                    continue

                all_pins = locator.get_all_symbol_pins(sch_path, ref) or {}
                pins_def = locator.get_symbol_pins(sch_path, lib_id) or {}

                for pin_num, coords in all_pins.items():
                    if (ref, str(pin_num)) in connected_pins:
                        continue
                    pin_pos = (round(float(coords[0]), 2), round(float(coords[1]), 2))
                    if pin_pos in no_connect_positions:
                        continue
                    pin_info = pins_def.get(str(pin_num), {})
                    unconnected.append(
                        {
                            "reference": ref,
                            "pinNumber": str(pin_num),
                            "pinName": pin_info.get("name", str(pin_num)),
                            "pinType": pin_info.get("type", "unknown"),
                            "position": {"x": coords[0], "y": coords[1]},
                        }
                    )

            return {"success": True, "unconnected": unconnected, "count": len(unconnected)}

        except Exception as e:
            logger.error(f"Error listing unconnected pins: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def find_single_pin_nets(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Return all nets that have exactly one connected pin (dangling connections)."""
        logger.info("Finding single-pin nets")
        try:
            schematic_path = params.get("schematicPath")
            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}

            sch_path = Path(schematic_path)
            if not sch_path.exists():
                return {"success": False, "message": f"Schematic not found: {schematic_path}"}

            schematic = SchematicManager.load_schematic(schematic_path)
            if not schematic:
                return {"success": False, "message": "Failed to load schematic"}

            locator = PinLocator()
            single_pin_nets: List[Dict[str, Any]] = []
            for net_name in sorted(_collect_net_names(schematic)):
                connections = ConnectionManager.get_net_connections(schematic, net_name, sch_path)
                if len(connections) == 1:
                    conn = connections[0]
                    meta = _pin_metadata(locator, sch_path, conn["component"], str(conn["pin"]))
                    single_pin_nets.append(
                        {
                            "netName": net_name,
                            "component": conn["component"],
                            "pinNumber": str(conn["pin"]),
                            "pinName": meta.get("name", str(conn["pin"])),
                        }
                    )

            return {
                "success": True,
                "singlePinNets": single_pin_nets,
                "count": len(single_pin_nets),
            }

        except Exception as e:
            logger.error(f"Error finding single-pin nets: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def classify_nets(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Classify all nets by type and return driver/load pin counts."""
        logger.info("Classifying nets")
        try:
            schematic_path = params.get("schematicPath")
            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}

            sch_path = Path(schematic_path)
            if not sch_path.exists():
                return {"success": False, "message": f"Schematic not found: {schematic_path}"}

            schematic = SchematicManager.load_schematic(schematic_path)
            if not schematic:
                return {"success": False, "message": "Failed to load schematic"}

            netmap = _build_full_netmap(schematic, schematic_path)
            nets_to_conns: Dict[str, List[Tuple[str, str]]] = {}
            for (ref, pin_num), net_name in netmap.items():
                nets_to_conns.setdefault(net_name, []).append((ref, pin_num))

            all_net_names = set(nets_to_conns.keys()) | _collect_net_names(schematic)

            locator = PinLocator()
            classified: List[Dict[str, Any]] = []
            for net_name in sorted(all_net_names):
                conns = nets_to_conns.get(net_name, [])
                driver_count = 0
                load_count = 0
                has_pwr_symbol = False
                for ref, pin_num in conns:
                    if ref.startswith("#PWR") or ref.startswith("#FLG"):
                        has_pwr_symbol = True
                        continue
                    ptype = _pin_metadata(locator, sch_path, ref, pin_num).get("type", "")
                    if ptype in _DRIVER_TYPES:
                        driver_count += 1
                    elif ptype in _LOAD_TYPES:
                        load_count += 1

                classified.append(
                    {
                        "netName": net_name,
                        "type": _classify_net_type(net_name, has_pwr_symbol, all_net_names),
                        "fanout": len(conns),
                        "driverCount": driver_count,
                        "loadCount": load_count,
                    }
                )

            return {"success": True, "nets": classified, "count": len(classified)}

        except Exception as e:
            logger.error(f"Error classifying nets: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def get_net_graph(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Return a compact component-to-component adjacency graph via named nets."""
        logger.info("Building net graph")
        try:
            schematic_path = params.get("schematicPath")
            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}

            skip_power = params.get("skipPower", True)
            sch_path = Path(schematic_path)
            if not sch_path.exists():
                return {"success": False, "message": f"Schematic not found: {schematic_path}"}

            schematic = SchematicManager.load_schematic(schematic_path)
            if not schematic:
                return {"success": False, "message": "Failed to load schematic"}

            locator = PinLocator()
            lines: List[str] = []
            for net_name in sorted(_collect_net_names(schematic)):
                connections = ConnectionManager.get_net_connections(schematic, net_name, sch_path)
                real_conns = [c for c in connections if not c["component"].startswith("#")]

                if skip_power and _is_power_or_ground(net_name) and len(real_conns) < 3:
                    continue
                if len(real_conns) < 2:
                    continue

                enriched = []
                for conn in real_conns:
                    meta = _pin_metadata(locator, sch_path, conn["component"], str(conn["pin"]))
                    enriched.append(
                        (
                            conn["component"],
                            meta.get("name", str(conn["pin"])),
                            meta.get("type", ""),
                        )
                    )

                drivers = [(ref, pin) for ref, pin, ptype in enriched if ptype in _DRIVER_TYPES]
                non_drivers = [
                    (ref, pin) for ref, pin, ptype in enriched if ptype not in _DRIVER_TYPES
                ]

                if drivers:
                    src_ref, src_pin = drivers[0]
                    dests = ", ".join(f"{r}({p})" for r, p in non_drivers)
                    if len(drivers) > 1:
                        extra = ", ".join(f"{r}({p})" for r, p in drivers[1:])
                        dests = (extra + ", " + dests).strip(", ")
                    lines.append(f"{src_ref}({src_pin}) --[{net_name}]--> {dests}")
                else:
                    all_nodes = ", ".join(f"{r}({p})" for r, p, _ in enriched)
                    lines.append(f"[{net_name}]: {all_nodes}")

            return {"success": True, "graph": "\n".join(lines), "netCount": len(lines)}

        except Exception as e:
            logger.error(f"Error building net graph: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def get_schematic_summary(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Return a compact, LLM-optimised text summary of the entire schematic."""
        logger.info("Getting schematic summary")
        try:
            schematic_path = params.get("schematicPath")
            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}

            sch_path = Path(schematic_path)
            if not sch_path.exists():
                return {"success": False, "message": f"Schematic not found: {schematic_path}"}

            schematic = SchematicManager.load_schematic(schematic_path)
            if not schematic:
                return {"success": False, "message": "Failed to load schematic"}

            locator = PinLocator()

            # Components table
            rows = []
            for symbol in schematic.symbol:
                if not hasattr(symbol.property, "Reference"):
                    continue
                ref = symbol.property.Reference.value
                if ref.startswith("_TEMPLATE") or ref.startswith("#"):
                    continue
                lib_id = symbol.lib_id.value if hasattr(symbol, "lib_id") else ""
                if lib_id.lower().startswith("power:"):
                    continue

                footprint = _get_prop(symbol, "Footprint", "")
                rows.append(
                    {
                        "ref": ref,
                        "value": _get_prop(symbol, "Value"),
                        "mpn": _get_prop(symbol, "MPN"),
                        "description": _get_prop(symbol, "Description"),
                        "footprint": footprint.split(":")[-1] if footprint else "-",
                    }
                )

            def _ref_sort_key(r):
                m = re.match(r"^([A-Za-z_]+)(\d+)", r["ref"])
                return (m.group(1), int(m.group(2))) if m else (r["ref"], 0)

            rows.sort(key=_ref_sort_key)

            # Net adjacency list
            netmap = _build_full_netmap(schematic, schematic_path)
            nets_to_conns: Dict[str, List[Tuple[str, str]]] = {}
            for (ref, pin_num), net_name in netmap.items():
                nets_to_conns.setdefault(net_name, []).append((ref, pin_num))
            all_net_names = set(nets_to_conns.keys()) | _collect_net_names(schematic)

            out: List[str] = []
            out.append(f"=== COMPONENTS ({len(rows)}) ===")
            out.append(f"{'REF':<8} {'VALUE':<14} {'MPN':<22} {'DESCRIPTION':<26} FOOTPRINT")
            out.append("-" * 90)
            for r in rows:
                out.append(
                    f"{r['ref']:<8} {r['value']:<14} {r['mpn']:<22} {r['description']:<26} {r['footprint']}"
                )

            out.append("")
            out.append(f"=== NETS ({len(all_net_names)}) ===")
            out.append(f"{'TYPE':<16} {'NAME':<22} CONNECTIONS")
            out.append("-" * 90)
            for net_name in sorted(all_net_names):
                conns = nets_to_conns.get(net_name, [])
                has_pwr = any(r.startswith("#PWR") or r.startswith("#FLG") for r, _ in conns)
                net_type = _classify_net_type(net_name, has_pwr, all_net_names)

                conn_strs = []
                for ref, pin_num in sorted(conns):
                    if ref.startswith("#"):
                        continue
                    meta = _pin_metadata(locator, sch_path, ref, pin_num)
                    conn_strs.append(f"{ref}/{meta.get('name', pin_num)}")

                conn_str = ", ".join(conn_strs)
                if len(conn_str) > 64:
                    conn_str = conn_str[:61] + "..."
                out.append(f"{net_type:<16} {net_name:<22} {conn_str}")

            return {"success": True, "summary": "\n".join(out)}

        except Exception as e:
            logger.error(f"Error getting schematic summary: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def get_net_topology(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Trace a complete net: wire segments, labels, pins, and dangling endpoints."""
        logger.info("Getting net topology")
        try:
            schematic_path = params.get("schematicPath")
            net_name = params.get("netName")
            if not schematic_path or not net_name:
                return {"success": False, "message": "schematicPath and netName are required"}

            schematic = SchematicManager.load_schematic(schematic_path)
            if not schematic:
                return {"success": False, "message": "Failed to load schematic"}

            sch_path = Path(schematic_path)
            tol = 0.5  # mm

            def coincide(a, b):
                return abs(a[0] - b[0]) < tol and abs(a[1] - b[1]) < tol

            # 1. Label positions for this net (seed points for the trace)
            labels_out = []
            seed_pts: List[Tuple[float, float]] = []
            for attr, kind in (("label", "local"), ("global_label", "global")):
                for lbl in getattr(schematic, attr, []):
                    if hasattr(lbl, "value") and lbl.value == net_name:
                        pos = (
                            lbl.at.value
                            if hasattr(lbl, "at") and hasattr(lbl.at, "value")
                            else [0, 0]
                        )
                        x, y = float(pos[0]), float(pos[1])
                        labels_out.append(
                            {
                                "name": net_name,
                                "type": kind,
                                "position": {"x": x, "y": y},
                                "angle": float(pos[2]) if len(pos) > 2 else 0,
                            }
                        )
                        seed_pts.append((x, y))

            if not seed_pts:
                return {
                    "success": True,
                    "net": net_name,
                    "wire_segments": [],
                    "labels": [],
                    "pins": [],
                    "dangling_endpoints": [],
                    "message": f"No labels found for net '{net_name}'",
                }

            # 2. All wire segments
            all_segs: List[Tuple[Tuple[float, float], Tuple[float, float]]] = []
            for wire in getattr(schematic, "wire", []):
                if hasattr(wire, "pts") and hasattr(wire.pts, "xy"):
                    pts = [
                        (float(pt.value[0]), float(pt.value[1]))
                        for pt in wire.pts.xy
                        if hasattr(pt, "value")
                    ]
                    for i in range(len(pts) - 1):
                        all_segs.append((pts[i], pts[i + 1]))

            # 3. BFS from seeds to reachable segments
            reachable_pts = list(seed_pts)
            reachable_seg_indices: set = set()
            changed = True
            while changed:
                changed = False
                for i, (wa, wb) in enumerate(all_segs):
                    if i in reachable_seg_indices:
                        continue
                    for rpt in reachable_pts:
                        if coincide(rpt, wa):
                            reachable_seg_indices.add(i)
                            if not any(coincide(wb, e) for e in reachable_pts):
                                reachable_pts.append(wb)
                            changed = True
                            break
                        elif coincide(rpt, wb):
                            reachable_seg_indices.add(i)
                            if not any(coincide(wa, e) for e in reachable_pts):
                                reachable_pts.append(wa)
                            changed = True
                            break

            wire_segments_out = [
                {
                    "start": {"x": all_segs[i][0][0], "y": all_segs[i][0][1]},
                    "end": {"x": all_segs[i][1][0], "y": all_segs[i][1][1]},
                }
                for i in sorted(reachable_seg_indices)
            ]

            # 4. Component pins at reachable points
            locator = PinLocator()
            pins_out = []
            for symbol in getattr(schematic, "symbol", []):
                if not hasattr(symbol.property, "Reference"):
                    continue
                ref = symbol.property.Reference.value
                if ref.startswith("_TEMPLATE") or ref.startswith("#"):
                    continue
                try:
                    all_pins = locator.get_all_symbol_pins(sch_path, ref)
                    lib_id = symbol.lib_id.value if hasattr(symbol, "lib_id") else ""
                    pins_def = locator.get_symbol_pins(sch_path, lib_id) if lib_id else {}
                    for pin_num, coords in all_pins.items():
                        px, py = float(coords[0]), float(coords[1])
                        if any(coincide((px, py), rpt) for rpt in reachable_pts):
                            pd = pins_def.get(str(pin_num), {})
                            pins_out.append(
                                {
                                    "ref": ref,
                                    "pin_number": pin_num,
                                    "pin_name": pd.get("name", pin_num),
                                    "pin_type": pd.get("type", "unknown"),
                                    "position": {"x": px, "y": py},
                                }
                            )
                except Exception as pe:
                    logger.debug(f"Pin lookup failed for {ref}: {pe}")

            # 5. Dangling endpoints (exactly one wire, no label, no pin)
            endpoint_count: Dict[int, int] = {}
            indexed_pts = list(enumerate(reachable_pts))
            for i in reachable_seg_indices:
                for ep in all_segs[i]:
                    for idx, rpt in indexed_pts:
                        if coincide(ep, rpt):
                            endpoint_count[idx] = endpoint_count.get(idx, 0) + 1
                            break

            pin_positions = [(p["position"]["x"], p["position"]["y"]) for p in pins_out]
            label_positions = [(lb["position"]["x"], lb["position"]["y"]) for lb in labels_out]

            dangling_out = []
            for idx, rpt in indexed_pts:
                if endpoint_count.get(idx, 0) != 1:
                    continue
                if any(coincide(rpt, lp) for lp in label_positions):
                    continue
                if any(coincide(rpt, pp) for pp in pin_positions):
                    continue
                dangling_out.append({"x": rpt[0], "y": rpt[1]})

            return {
                "success": True,
                "net": net_name,
                "wire_segments": wire_segments_out,
                "labels": labels_out,
                "pins": pins_out,
                "dangling_endpoints": dangling_out,
            }

        except Exception as e:
            logger.error(f"Error getting net topology: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}
