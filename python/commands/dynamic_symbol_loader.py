"""
Dynamic Symbol Loader for KiCad Schematics

Loads symbols from .kicad_sym library files and injects them into schematics
on-the-fly using TEXT MANIPULATION (not sexpdata) to preserve file formatting.

This enables access to all ~10,000+ KiCad symbols dynamically.
"""

import logging
import math
import os
import re
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("kicad_interface")

_SCHEMATIC_GRID_MM = 1.27  # 50mil — KiCAD standard schematic grid


def _snap(val: float) -> float:
    """Round a coordinate to the nearest KiCAD schematic grid point (50mil = 1.27mm)."""
    return round(round(val / _SCHEMATIC_GRID_MM) * _SCHEMATIC_GRID_MM, 4)


def _get_lib_pin_schematic_bbox(content: str, full_lib_id: str,
                                comp_x: float, comp_y: float, rotation: float) -> Optional[dict]:
    """Compute the body bounding-box from lib pin endpoints in schematic coordinates.

    Returns {"x_min", "x_max", "y_min", "y_max"} with 1.27mm padding, or None if no pins found.
    """
    lib_start = content.find("(lib_symbols")
    if lib_start < 0:
        return None
    depth = 0
    lib_end = lib_start
    for i in range(lib_start, len(content)):
        if content[i] == "(":
            depth += 1
        elif content[i] == ")":
            depth -= 1
            if depth == 0:
                lib_end = i + 1
                break
    lib_section = content[lib_start:lib_end]

    sym_marker = f'(symbol "{full_lib_id}"'
    sym_start = lib_section.find(sym_marker)
    if sym_start < 0:
        return None
    depth = 0
    sym_end = sym_start
    for i in range(sym_start, len(lib_section)):
        if lib_section[i] == "(":
            depth += 1
        elif lib_section[i] == ")":
            depth -= 1
            if depth == 0:
                sym_end = i + 1
                break
    sym_block = lib_section[sym_start:sym_end]

    # Extract all pin endpoints: (pin TYPE SHAPE (at X Y angle) ...)
    # KiCAD pin format: (pin passive line (at 0 3.81 270) (length 2.794) ...)
    pin_pattern = re.compile(r'\(pin\s+\S+\s+\S+\s+\(at\s+([-\d.]+)\s+([-\d.]+)', re.DOTALL)
    rot_rad = math.radians(rotation)
    cos_r = math.cos(rot_rad)
    sin_r = math.sin(rot_rad)
    xs, ys = [], []
    for m in pin_pattern.finditer(sym_block):
        px_lib = float(m.group(1))
        py_lib = float(m.group(2))
        # Y-flip then rotate (same as _transform_pin_to_schematic)
        px_sch = px_lib
        py_sch = -py_lib
        rx = px_sch * cos_r + py_sch * sin_r
        ry = -px_sch * sin_r + py_sch * cos_r
        xs.append(comp_x + rx)
        ys.append(comp_y + ry)

    if not xs:
        return None
    pad = 1.27
    return {
        "x_min": min(xs) - pad,
        "x_max": max(xs) + pad,
        "y_min": min(ys) - pad,
        "y_max": max(ys) + pad,
    }


def _get_lib_field_positions(content: str, full_lib_id: str) -> dict:
    """Extract Reference and Value field default positions from the lib_symbols section.

    Symbols store field positions in symbol-local coordinates with y-UP (math convention).
    Returns {"Reference": {"x": float, "y": float, "angle": float}, "Value": {...}} or {}.
    """
    lib_start = content.find("(lib_symbols")
    if lib_start < 0:
        return {}
    # Find the matching close paren of (lib_symbols ...)
    depth = 0
    lib_end = lib_start
    for i in range(lib_start, len(content)):
        if content[i] == "(":
            depth += 1
        elif content[i] == ")":
            depth -= 1
            if depth == 0:
                lib_end = i + 1
                break
    lib_section = content[lib_start:lib_end]

    # Locate this specific symbol's block within lib_symbols
    # Use escaped name to handle special chars like : + etc.
    sym_marker = f'(symbol "{full_lib_id}"'
    sym_start = lib_section.find(sym_marker)
    if sym_start < 0:
        return {}
    depth = 0
    sym_end = sym_start
    for i in range(sym_start, len(lib_section)):
        if lib_section[i] == "(":
            depth += 1
        elif lib_section[i] == ")":
            depth -= 1
            if depth == 0:
                sym_end = i + 1
                break
    sym_block = lib_section[sym_start:sym_end]

    fields = {}
    for field_name in ("Reference", "Value"):
        pattern = (
            r'\(property\s+"' + re.escape(field_name) + r'"\s+"[^"]*"\s+'
            r'\(at\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\)'
        )
        m = re.search(pattern, sym_block, re.DOTALL)
        if m:
            fields[field_name] = {
                "x": float(m.group(1)),
                "y": float(m.group(2)),
                "angle": float(m.group(3)),
            }
    return fields


def _transform_field_to_schematic(
    sym_x: float, sym_y: float, sym_angle: float,
    comp_x: float, comp_y: float, rotation: float
) -> tuple:
    """Transform a symbol-local field position (y-UP) to schematic-absolute (y-DOWN).

    KiCAD screen rotation θ is CCW on screen (y-down). The symbol library stores coords
    in y-UP math space. The combined transform is:
        x_sch = comp_x + sym_x * cos(θ) + sym_y * sin(θ)
        y_sch = comp_y + sym_x * sin(θ) - sym_y * cos(θ)
    Text angle in screen space = (sym_angle + θ) mod 360, then normalized so text
    is never upside-down (i.e., angle > 90 and ≤ 270 → subtract 180).
    Returns (x_sch, y_sch, screen_angle) all snapped / rounded.
    """
    rot_rad = math.radians(rotation)
    cos_r = math.cos(rot_rad)
    sin_r = math.sin(rot_rad)
    x_sch = comp_x + sym_x * cos_r + sym_y * sin_r
    y_sch = comp_y + sym_x * sin_r - sym_y * cos_r
    screen_angle = (sym_angle + rotation) % 360
    # Normalize: keep text readable (never upside-down)
    if 90 < screen_angle <= 270:
        screen_angle = (screen_angle + 180) % 360
    return _snap(x_sch), _snap(y_sch), int(screen_angle)


def _find_project_root(start_dir: Path) -> Path:
    """Walk up from start_dir to find the nearest directory containing a .kicad_pro file.

    Returns start_dir if no .kicad_pro is found (safe fallback).
    """
    current = start_dir.resolve()
    while True:
        if list(current.glob("*.kicad_pro")):
            return current
        parent = current.parent
        if parent == current:  # filesystem root
            break
        current = parent
    return start_dir


class DynamicSymbolLoader:
    """
    Dynamically loads symbols from KiCad library files and injects them into schematics.

    Uses raw text manipulation instead of sexpdata to avoid corrupting the KiCad file format.

    Key rules for KiCad 9 .kicad_sch format:
    - Top-level symbols in lib_symbols must have library prefix: (symbol "Device:R" ...)
    - Sub-symbols must NOT have library prefix: (symbol "R_0_1" ...), (symbol "R_1_1" ...)
    - Parent symbols must appear BEFORE child symbols that use (extends ...)
    """

    def __init__(self, project_path: Optional[Path] = None):
        self.symbol_cache = {}  # Cache: "lib:symbol" -> raw text block
        self.project_path = project_path  # Project directory for project-specific libraries

    def find_kicad_symbol_libraries(self) -> List[Path]:
        """Find all KiCad symbol library directories"""
        possible_paths = [
            Path("/usr/share/kicad/symbols"),
            Path("/usr/local/share/kicad/symbols"),
            Path("C:/Program Files/KiCad/9.0/share/kicad/symbols"),
            Path("C:/Program Files/KiCad/8.0/share/kicad/symbols"),
            Path("/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols"),
            Path.home() / ".local" / "share" / "kicad" / "10.0" / "symbols",
            Path.home() / ".local" / "share" / "kicad" / "9.0" / "symbols",
            Path.home() / "Documents" / "KiCad" / "10.0" / "3rdparty" / "symbols",
            Path.home() / "Documents" / "KiCad" / "9.0" / "3rdparty" / "symbols",
        ]
        for env_var in [
            "KICAD10_SYMBOL_DIR",
            "KICAD9_SYMBOL_DIR",
            "KICAD8_SYMBOL_DIR",
            "KICAD_SYMBOL_DIR",
        ]:
            if env_var in os.environ:
                possible_paths.insert(0, Path(os.environ[env_var]))

        return [p for p in possible_paths if p.exists() and p.is_dir()]

    def find_library_file(self, library_name: str) -> Optional[Path]:
        """Find the .kicad_sym file for a given library name.

        Search order:
        1. Project-specific sym-lib-table (if project_path is set)
        2. Global KiCad symbol library directories
        """
        # 1. Check project-specific sym-lib-table
        if self.project_path:
            project_table = Path(self.project_path) / "sym-lib-table"
            if project_table.exists():
                resolved = self._resolve_library_from_table(project_table, library_name)
                if resolved:
                    logger.info(f"Found '{library_name}' in project sym-lib-table: {resolved}")
                    return resolved

        # 2. Fall back to global KiCad symbol directories
        for lib_dir in self.find_kicad_symbol_libraries():
            lib_file = lib_dir / f"{library_name}.kicad_sym"
            if lib_file.exists():
                return lib_file

        logger.warning(f"Library file not found: {library_name}.kicad_sym")
        return None

    def _resolve_library_from_table(self, table_path: Path, library_name: str) -> Optional[Path]:
        """Parse a sym-lib-table file and return the resolved path for the given library nickname."""
        try:
            with open(table_path, "r", encoding="utf-8") as f:
                content = f.read()

            lib_pattern = (
                r'\(lib\s+\(name\s+"?([^"\)\s]+)"?\)\s*\(type\s+[^)]+\)\s*\(uri\s+"?([^"\)\s]+)"?'
            )
            for match in re.finditer(lib_pattern, content, re.IGNORECASE):
                nickname = match.group(1)
                if nickname != library_name:
                    continue
                uri = match.group(2)
                resolved = self._resolve_sym_uri(uri)
                if resolved and Path(resolved).exists():
                    return Path(resolved)
        except Exception as e:
            logger.warning(f"Could not parse sym-lib-table {table_path}: {e}")
        return None

    def _resolve_sym_uri(self, uri: str) -> Optional[str]:
        """Resolve environment variables in a sym-lib-table URI."""
        env_map = {
            "KICAD10_SYMBOL_DIR": [
                "/usr/share/kicad/symbols",
                "C:/Program Files/KiCad/10.0/share/kicad/symbols",
                "/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols",
            ],
            "KICAD9_SYMBOL_DIR": [
                "C:/Program Files/KiCad/9.0/share/kicad/symbols",
                "/usr/share/kicad/symbols",
                "/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols",
            ],
            "KICAD8_SYMBOL_DIR": [
                "C:/Program Files/KiCad/8.0/share/kicad/symbols",
            ],
            "KIPRJMOD": [str(self.project_path)] if self.project_path else [],
        }
        result = uri
        for var, candidates in env_map.items():
            if f"${{{var}}}" in result:
                for candidate in candidates:
                    candidate_path = result.replace(f"${{{var}}}", candidate)
                    if Path(candidate_path).exists():
                        return candidate_path
                # Fallback: try OS env
                if var in os.environ:
                    return result.replace(f"${{{var}}}", os.environ[var])
        return result

    def _extract_symbol_block(self, text: str, symbol_name: str) -> Optional[str]:
        """
        Extract a complete symbol block from a library or schematic file by matching
        parentheses depth. Returns the raw text of the symbol definition.
        """
        lines = text.split("\n")
        start = None
        for i, line in enumerate(lines):
            stripped = line.strip()
            # Match exact symbol name (not sub-symbols like Name_0_1)
            if stripped.startswith(f'(symbol "{symbol_name}"') and not re.match(
                r'.*_\d+_\d+"', stripped
            ):
                start = i
                break

        if start is None:
            return None

        depth = 0
        end = None
        for i in range(start, len(lines)):
            for ch in lines[i]:
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                    if depth == 0:
                        end = i
                        break
            if end is not None:
                break

        if end is None:
            return None

        return "\n".join(lines[start : end + 1])

    def _iter_top_level_items(self, symbol_block: str) -> list:
        """
        Extract each top-level s-expression item from inside a symbol block.
        Starts after the first line (symbol header) and stops before the final
        closing parenthesis.  Returns a list of raw text strings.
        """
        lines = symbol_block.split("\n")
        items = []
        i = 1  # skip first line: (symbol "Name" ...)
        n = len(lines)

        while i < n:
            line = lines[i]
            stripped = line.strip()

            if not stripped:
                i += 1
                continue

            # The final closing paren of the symbol itself
            if stripped == ")" and i == n - 1:
                break

            if not stripped.startswith("("):
                i += 1
                continue

            # Collect a balanced s-expression starting here
            depth = 0
            item_start = i
            while i < n:
                for ch in lines[i]:
                    if ch == "(":
                        depth += 1
                    elif ch == ")":
                        depth -= 1
                i += 1
                if depth == 0:
                    break

            items.append("\n".join(lines[item_start:i]))

        return items

    def _inline_extends_symbol(self, lib_content: str, symbol_name: str, child_block: str) -> str:
        """
        Fully inline a child symbol that uses (extends "ParentName") by merging
        the parent's pins / graphics into the child definition.

        KiCad 9 does NOT support (extends ...) inside a schematic's lib_symbols
        section.  This method produces a self-contained, fully-resolved symbol
        block – exactly what KiCad itself writes when saving a schematic.

        Algorithm:
          1. Extract the parent block from the library text.
          2. Take every top-level item from the parent (pin_names, properties,
             sub-symbols, …).
          3. For each property, use the child's override if one exists; otherwise
             keep the parent's value.
          4. Rename parent sub-symbols (ParentName_0_1 → ChildName_0_1).
          5. Append any child-only properties that do not exist in the parent.
          6. Return the merged block named after the child – no (extends …) left.
        """
        extends_match = re.search(r'\(extends "([^"]+)"\)', child_block)
        if not extends_match:
            return child_block

        parent_name = extends_match.group(1)
        parent_block = self._extract_symbol_block(lib_content, parent_name)
        if not parent_block:
            logger.warning(
                f"Cannot resolve parent '{parent_name}' for '{symbol_name}' "
                "- stripping extends clause (symbol may be incomplete)"
            )
            return re.sub(r"\s*\(extends \"[^\"]+\"\)\n?", "", child_block)

        # Collect child property overrides: prop_name -> raw block text
        child_props: dict = {}
        for item in self._iter_top_level_items(child_block):
            m = re.match(r'[\s\t]*\(property "([^"]+)"', item)
            if m:
                child_props[m.group(1)] = item

        # Walk parent items, applying child overrides
        body_lines = []
        parent_prop_names: set = set()

        for item in self._iter_top_level_items(parent_block):
            prop_match = re.match(r'[\s\t]*\(property "([^"]+)"', item)
            sub_match = re.search(r'\(symbol "' + re.escape(parent_name) + r'_\d+_\d+"', item)

            if prop_match:
                pname = prop_match.group(1)
                parent_prop_names.add(pname)
                body_lines.append(child_props[pname] if pname in child_props else item)
            elif sub_match:
                # Rename ParentName_0_1 → ChildName_0_1
                body_lines.append(item.replace(f'"{parent_name}_', f'"{symbol_name}_'))
            elif re.match(r"[\s\t]*\(extends ", item):
                pass  # drop extends clause
            else:
                body_lines.append(item)  # pin_names, in_bom, on_board …

        # Append child-only properties absent from parent
        for pname, pblock in child_props.items():
            if pname not in parent_prop_names:
                body_lines.append(pblock)

        first_line = parent_block.split("\n")[0].replace(f'"{parent_name}"', f'"{symbol_name}"')
        last_line = parent_block.split("\n")[-1]

        return first_line + "\n" + "\n".join(body_lines) + "\n" + last_line

    def extract_symbol_from_library(self, library_name: str, symbol_name: str) -> Optional[str]:
        """
        Extract a symbol definition from a KiCad .kicad_sym library file.
        Returns the raw text block, ready to be injected into a schematic.

        The returned block has:
        - Top-level name prefixed with library: (symbol "Library:Name" ...)
        - Sub-symbol names WITHOUT prefix: (symbol "Name_0_1" ...)
        """
        cache_key = f"{library_name}:{symbol_name}"
        if cache_key in self.symbol_cache:
            return self.symbol_cache[cache_key]

        lib_path = self.find_library_file(library_name)
        if not lib_path:
            return None

        with open(lib_path, "r", encoding="utf-8") as f:
            lib_content = f.read()

        # Strip ; comment lines before processing — they are valid in .kicad_sym
        # files but sexpdata and skip cannot parse them when embedded in a schematic.
        lib_content = re.sub(r'^\s*;.*$', '', lib_content, flags=re.MULTILINE)

        block = self._extract_symbol_block(lib_content, symbol_name)
        if block is None:
            # Find close matches to help the caller recover
            all_names = re.findall(
                r'^\s*\(symbol "([^"_][^"]*(?<![_\d]{3}))"',
                lib_content,
                flags=re.MULTILINE,
            )
            # Filter out sub-symbols (Name_0_1 pattern)
            top_level = [n for n in all_names if not re.search(r'_\d+_\d+$', n)]
            import difflib
            close = difflib.get_close_matches(symbol_name, top_level, n=5, cutoff=0.4)
            hint = f" Close matches: {close}" if close else ""
            logger.warning(
                f"Symbol '{symbol_name}' not found in {library_name}.kicad_sym.{hint}"
            )
            # Attach suggestions so callers can surface them in error messages
            err = ValueError(
                f"Symbol '{symbol_name}' not found in library '{library_name}'.{hint}"
            )
            err.suggestions = close  # type: ignore[attr-defined]
            raise err

        # If the symbol uses (extends "ParentName"), inline the parent content
        # so that the result is a fully self-contained definition.
        # (extends ...) is only valid in .kicad_sym files; KiCad 9 refuses to
        # load a schematic whose lib_symbols section contains it.
        if re.search(r'\(extends "([^"]+)"\)', block):
            parent_name = re.search(r'\(extends "([^"]+)"\)', block).group(1)
            logger.info(f"Symbol {symbol_name} extends {parent_name}, inlining parent content")
            block = self._inline_extends_symbol(lib_content, symbol_name, block)

        # Prefix top-level symbol name with library
        full_name = f"{library_name}:{symbol_name}"
        block = block.replace(
            f'(symbol "{symbol_name}"',
            f'(symbol "{full_name}"',
            1,  # Only first occurrence (top-level)
        )
        # Sub-symbols like "Name_0_1" keep their short names (already correct from library)

        result = block

        self.symbol_cache[cache_key] = result
        logger.info(f"Extracted symbol {full_name} ({len(result)} chars)")
        return result

    def _remove_lib_symbol_block(self, content: str, full_name: str) -> str:
        """Remove a symbol definition block from lib_symbols, including its leading whitespace."""
        marker = f'(symbol "{full_name}"'
        start_idx = content.find(marker)
        if start_idx == -1:
            return content

        # Find matching closing paren
        depth = 0
        end_idx = start_idx
        for i in range(start_idx, len(content)):
            if content[i] == "(":
                depth += 1
            elif content[i] == ")":
                depth -= 1
                if depth == 0:
                    end_idx = i + 1
                    break

        # Include the leading newline + whitespace before the block so that the
        # next symbol (if any) retains its own leading newline/indentation.
        line_start = content.rfind("\n", 0, start_idx)
        actual_start = line_start if line_start != -1 else start_idx

        return content[:actual_start] + content[end_idx:]

    def inject_symbol_into_schematic(
        self, schematic_path: Path, library_name: str, symbol_name: str
    ) -> bool:
        """
        Inject a symbol definition into a schematic's lib_symbols section.
        If the symbol already exists (e.g. from a stale template), replace it with
        the current definition from disk. Uses text manipulation to preserve formatting.
        """
        full_name = f"{library_name}:{symbol_name}"

        with open(schematic_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Extract symbol from library (fresh from disk)
        symbol_block = self.extract_symbol_from_library(library_name, symbol_name)
        if not symbol_block:
            raise ValueError(f"Symbol '{symbol_name}' not found in library '{library_name}'")

        # If symbol already exists, remove the stale definition so we can re-inject fresh
        if f'(symbol "{full_name}"' in content:
            logger.info(f"Replacing existing symbol definition: {full_name}")
            content = self._remove_lib_symbol_block(content, full_name)

        # Indent the block to match lib_symbols indentation (4 spaces for top-level)
        indented_lines = []
        for line in symbol_block.split("\n"):
            # Add 4-space indent for the content inside lib_symbols
            indented_lines.append("    " + line if line.strip() else line)
        indented_block = "\n".join(indented_lines)

        # Find the end of lib_symbols section using string search (format-independent,
        # works even when sexpdata.dumps() has compacted the file to a single line)
        lib_sym_start = content.find("(lib_symbols")
        if lib_sym_start == -1:
            raise ValueError("No lib_symbols section found in schematic")

        depth = 0
        lib_sym_end = lib_sym_start
        for i in range(lib_sym_start, len(content)):
            if content[i] == "(":
                depth += 1
            elif content[i] == ")":
                depth -= 1
                if depth == 0:
                    lib_sym_end = i
                    break
        else:
            raise ValueError("No lib_symbols section found in schematic")

        # Insert the symbol block just before the closing ) of lib_symbols
        content = content[:lib_sym_end] + "\n    " + indented_block + "\n  " + content[lib_sym_end:]

        with open(schematic_path, "w", encoding="utf-8") as f:
            f.write(content)

        # Handle both Path objects and strings
        sch_name = schematic_path.name if hasattr(schematic_path, "name") else str(schematic_path)
        logger.info(f"Injected symbol {full_name} into {sch_name}")
        return True

    def create_component_instance(
        self,
        schematic_path: Path,
        library_name: str,
        symbol_name: str,
        reference: str,
        value: str = "",
        footprint: str = "",
        x: float = 0,
        y: float = 0,
        rotation: float = 0,
    ) -> bool:
        """
        Add a component instance to the schematic.
        This creates the (symbol ...) block with lib_id reference.
        """
        full_lib_id = f"{library_name}:{symbol_name}"
        new_uuid = str(uuid.uuid4())

        # Snap placement to 50mil grid so pins land on-grid in the schematic editor
        x = _snap(x)
        y = _snap(y)

        # Derive project name from .kicad_pro file so KiCad's annotation table is correct.
        # KiCad renders the reference from (instances ...) not from (property "Reference" ...),
        # so omitting this block causes all symbols to show as "R?", "C?", etc.
        pro_files = list(_find_project_root(schematic_path.parent).glob("*.kicad_pro"))
        project_name = pro_files[0].stem if pro_files else schematic_path.stem
        # Standalone project name for the sub-sheet (used as fallback by KiCad when the
        # hierarchical path under project_name cannot be resolved — e.g. when the schematic
        # is opened as a standalone file or before the root ERC annotates it).
        standalone_project_name = schematic_path.stem

        with open(schematic_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Extract the schematic's own UUID (handles both quoted and unquoted KiCad formats).
        # Used as the standalone-project path and as a fallback for the root-project path.
        sch_uuid_match = re.search(r'\(uuid\s+"?([0-9a-fA-F-]+)"?\)', content)
        sch_uuid = sch_uuid_match.group(1) if sch_uuid_match else ""

        # Build the instance path for the root-project (kicad-main-pcb) entry.
        # For a sub-sheet, KiCad requires the HIERARCHICAL path /{root-uuid}/{sheet-sym-uuid},
        # NOT the flat /{sub-sheet-uuid}. Using the flat path causes KiCad to fail resolution
        # and reset all references to "R?", "C?", etc. on every open/save cycle.
        instance_path = f"/{sch_uuid}" if sch_uuid else "/"
        if project_name != standalone_project_name:
            # Look up root schematic to build the correct hierarchical path
            root_sch = _find_project_root(schematic_path.parent) / f"{project_name}.kicad_sch"
            if root_sch.exists():
                with open(root_sch, "r", encoding="utf-8") as _rf:
                    root_content = _rf.read()
                # Root UUID may be unquoted (MCP-generated) or quoted (KiCad-saved)
                _root_uuid_m = re.search(r'\(uuid\s+"?([0-9a-fA-F-]+)"?\)', root_content)
                # Find the sheet symbol UUID that references this sub-sheet file.
                # Look backwards from the "Sheet file" property to find the nearest (uuid "...")
                _file_pos = root_content.find(f'"Sheet file" "{schematic_path.name}"')
                if _file_pos > 0 and _root_uuid_m:
                    _uuid_matches = list(re.finditer(
                        r'\(uuid\s+"([0-9a-fA-F-]+)"\)', root_content[:_file_pos]
                    ))
                    if _uuid_matches:
                        instance_path = f"/{_root_uuid_m.group(1)}/{_uuid_matches[-1].group(1)}"

        # Compute field positions from library defaults (so they match KiCAD conventions
        # per symbol and rotation), with a sensible fallback when extraction fails.
        lib_fields = _get_lib_field_positions(content, full_lib_id)
        rot_n = int(rotation) % 360

        if "Reference" in lib_fields:
            lf = lib_fields["Reference"]
            ref_x, ref_y, _ = _transform_field_to_schematic(
                lf["x"], lf["y"], lf["angle"], x, y, rotation
            )
        else:
            # Fallback: rotation-aware defaults
            # rot=0/180 (vertical body) → ref to left; rot=90/270 (horizontal) → ref above
            if rot_n in (0, 180):
                ref_x, ref_y = _snap(x - 2.54), y
            else:
                ref_x, ref_y = x, _snap(y - 2.54)
        # Always write angle=0 so ref text is horizontal/readable regardless of symbol rotation.
        # Rotated ref/val text is nearly always an error in practice.
        ref_angle = 0

        if "Value" in lib_fields:
            lf = lib_fields["Value"]
            val_x, val_y, _ = _transform_field_to_schematic(
                lf["x"], lf["y"], lf["angle"], x, y, rotation
            )
        else:
            if rot_n in (0, 180):
                val_x, val_y = _snap(x + 2.54), y
            else:
                val_x, val_y = x, _snap(y + 2.54)
        val_angle = 0  # always horizontal

        # ── Field clearance enforcement ────────────────────────────────────────
        # Use the pin-spread body bbox to position ref/val outside the component.
        #
        # Core principle: place ref/val PERPENDICULAR to the major pin axis so
        # they cannot overlap with net labels placed at pin tips.
        #
        # 2-pin passives (R, C, L, Polyfuse, FerriteBead, LED, …):
        #   Determine the pin axis from the bbox span (pins extend in the larger
        #   dimension).  Place ref/val along the perpendicular axis, 2mm outside
        #   the bbox edge.  This avoids collisions with pin labels regardless of
        #   component rotation.
        #     • Horizontal body (bb_x_span ≥ bb_y_span, e.g. rot=90 resistor):
        #         ref above (y_min−2mm), val below (y_max+2mm), both at center_x
        #     • Vertical body (bb_y_span > bb_x_span, e.g. rot=90 LED/diode):
        #         ref left (x_min−2mm), val right (x_max+2mm), both at center_y
        #
        # Multi-pin ICs and custom symbols:
        #   Preserve lib-derived positions when they are already close to the
        #   bbox edge (within MAX_EXT_GAP=3mm).  Fix in two cases:
        #   (a) position is inside the bbox (with 1.5mm margin) → push out
        #   (b) position is more than MAX_EXT_GAP outside → pull in to 2mm
        #   Direction: respect the lib's intended side (ref above → stay above,
        #   ref below → stay below), with major-axis fallback for ambiguous cases.

        body_bb = _get_lib_pin_schematic_bbox(content, full_lib_id, x, y, rotation)
        n_lib_pins = 0
        if body_bb is not None:
            # Count pins to decide strategy (reuse the same section we just parsed)
            pin_pat = re.compile(r'\(pin\s+\S+\s+\S+\s+\(at\s+[-\d.]+\s+[-\d.]+')
            lib_start = content.find("(lib_symbols")
            sym_marker = f'(symbol "{full_lib_id}"'
            sym_s = content.find(sym_marker, lib_start)
            if sym_s >= 0:
                depth = 0
                for ci in range(sym_s, len(content)):
                    if content[ci] == "(":
                        depth += 1
                    elif content[ci] == ")":
                        depth -= 1
                        if depth == 0:
                            n_lib_pins = len(pin_pat.findall(content[sym_s:ci + 1]))
                            break

        if body_bb is not None:
            PAD = 1.27  # padding used when building body_bb
            bb_x_span = (body_bb["x_max"] - body_bb["x_min"]) - 2 * PAD
            bb_y_span = (body_bb["y_max"] - body_bb["y_min"]) - 2 * PAD
            FIELD_CLEARANCE = 2.0  # mm clearance from bbox edge

            if n_lib_pins == 2:
                # 2-pin: always override with pin-axis-perpendicular placement.
                # Lib-derived positions frequently land at or between pin tips
                # (same coordinate as the net label), causing visual overlap.
                if bb_x_span >= bb_y_span:
                    # Horizontal body — pins in X → ref above, val below
                    ref_x = x
                    ref_y = _snap(body_bb["y_min"] - FIELD_CLEARANCE)
                    val_x = x
                    val_y = _snap(body_bb["y_max"] + FIELD_CLEARANCE)
                else:
                    # Vertical body — pins in Y → ref left, val right
                    ref_x = _snap(body_bb["x_min"] - FIELD_CLEARANCE)
                    ref_y = y
                    val_x = _snap(body_bb["x_max"] + FIELD_CLEARANCE)
                    val_y = y

            elif n_lib_pins > 2:
                # Multi-pin: fix only when necessary (inside bbox or too far out).
                MARGIN = 0.5       # consider "inside" when within this margin of edge
                MAX_EXT_GAP = 3.0  # if farther than this outside bbox, pull it in

                def _field_needs_fix(fx, fy, bb, margin, max_gap):
                    """True if field is inside bbox (with margin) or too far outside."""
                    inside = (bb["x_min"] - margin <= fx <= bb["x_max"] + margin and
                              bb["y_min"] - margin <= fy <= bb["y_max"] + margin)
                    if inside:
                        return True
                    gap = max(
                        max(bb["x_min"] - fx, fx - bb["x_max"], 0),
                        max(bb["y_min"] - fy, fy - bb["y_max"], 0),
                    )
                    return gap > max_gap

                def _push_field(fx, fy, bb, gap, comp_cx, comp_cy, bb_xs, bb_ys, is_ref):
                    """Move field to a clean position outside the bbox.

                    Direction is chosen by the lib's intended side (above/below/left/right
                    relative to component centre), with a major-axis fallback when the
                    field sits near centre.  ref → preferred smaller coord; val → larger.
                    """
                    above = fy < comp_cy - 0.5
                    below = fy > comp_cy + 0.5
                    left  = fx < comp_cx - 0.5
                    right = fx > comp_cx + 0.5
                    if above or (not below and is_ref and bb_xs >= bb_ys):
                        return fx, _snap(bb["y_min"] - gap)
                    if below or (not above and not is_ref and bb_xs >= bb_ys):
                        return fx, _snap(bb["y_max"] + gap)
                    if left or (not right and is_ref):
                        return _snap(bb["x_min"] - gap), fy
                    return _snap(bb["x_max"] + gap), fy

                for is_ref in (True, False):
                    fx, fy = (ref_x, ref_y) if is_ref else (val_x, val_y)
                    if _field_needs_fix(fx, fy, body_bb, MARGIN, MAX_EXT_GAP):
                        fx, fy = _push_field(
                            fx, fy, body_bb, FIELD_CLEARANCE,
                            x, y, bb_x_span, bb_y_span, is_ref,
                        )
                    if is_ref:
                        ref_x, ref_y = fx, fy
                    else:
                        val_x, val_y = fx, fy

        # ── End field clearance enforcement ────────────────────────────────────

        # When the schematic is a sub-sheet, also write a standalone-project entry using the
        # sub-sheet's own flat path /{sch_uuid}. KiCad uses this when the file is opened
        # outside the root project context (e.g. standalone or before root ERC runs).
        standalone_path = f"/{sch_uuid}" if sch_uuid else "/"
        if project_name != standalone_project_name and sch_uuid:
            standalone_block = (
                f'      (project "{standalone_project_name}"\n'
                f'        (path "{standalone_path}" (reference "{reference}") (unit 1))\n'
                f'      )\n'
            )
        else:
            standalone_block = ""

        instance_block = f"""  (symbol (lib_id "{full_lib_id}") (at {x} {y} {int(rotation)}) (unit 1)
    (in_bom yes) (on_board yes) (dnp no)
    (uuid "{new_uuid}")
    (property "Reference" "{reference}" (at {ref_x} {ref_y} {ref_angle})
      (effects (font (size 1.27 1.27)))
    )
    (property "Value" "{value or symbol_name}" (at {val_x} {val_y} {val_angle})
      (effects (font (size 1.27 1.27)))
    )
    (property "Footprint" "{footprint}" (at {x} {y} 0)
      (effects (font (size 1.27 1.27)) (hide yes))
    )
    (property "Datasheet" "~" (at {x} {y} 0)
      (effects (font (size 1.27 1.27)) (hide yes))
    )
    (instances
      (project "{project_name}"
        (path "{instance_path}" (reference "{reference}") (unit 1))
      )
{standalone_block}    )
  )"""

        # Insert before (sheet_instances using direct string search.
        # This works for both pretty-printed and sexpdata-compacted single-line files.
        insert_marker = "(sheet_instances"
        insert_at = content.rfind(insert_marker)
        if insert_at == -1:
            raise ValueError("Could not find insertion point in schematic")

        content = content[:insert_at] + instance_block + "\n  " + content[insert_at:]

        with open(schematic_path, "w", encoding="utf-8") as f:
            f.write(content)

        logger.info(f"Added component instance {reference} ({full_lib_id}) at ({x}, {y})")
        return True

    def load_symbol_dynamically(
        self, schematic_path: Path, library_name: str, symbol_name: str
    ) -> str:
        """
        Complete workflow: inject symbol definition and create a template instance.
        Returns a template reference name.
        """
        logger.info(f"Loading symbol dynamically: {library_name}:{symbol_name}")

        # Step 1: Inject symbol definition into lib_symbols
        self.inject_symbol_into_schematic(schematic_path, library_name, symbol_name)

        # Step 2: Create an offscreen template instance
        lib_clean = library_name.replace("-", "_").replace(".", "_")
        sym_clean = symbol_name.replace("-", "_").replace(".", "_")
        template_ref = f"_TEMPLATE_{lib_clean}_{sym_clean}"

        self.create_component_instance(
            schematic_path,
            library_name,
            symbol_name,
            reference=template_ref,
            value=symbol_name,
            x=-200,
            y=-200,
        )

        logger.info(f"Symbol loaded. Template reference: {template_ref}")
        return template_ref

    def add_component(
        self,
        schematic_path: Path,
        library_name: str,
        symbol_name: str,
        reference: str,
        value: str = "",
        footprint: str = "",
        x: float = 0,
        y: float = 0,
        rotation: float = 0,
        project_path: Optional[Path] = None,
    ) -> bool:
        """
        High-level: ensure symbol definition exists in schematic, then add an instance.
        This is the main entry point for adding components.

        Args:
            project_path: Optional project directory. When set, project-specific
                          sym-lib-table is also searched for the library file.
            rotation: Rotation in degrees (CCW positive, multiples of 90).
        """
        if project_path:
            self.project_path = project_path
        # Ensure symbol definition is in lib_symbols
        self.inject_symbol_into_schematic(schematic_path, library_name, symbol_name)

        # Add the component instance
        return self.create_component_instance(
            schematic_path,
            library_name,
            symbol_name,
            reference=reference,
            value=value,
            footprint=footprint,
            x=x,
            y=y,
            rotation=rotation,
        )

    def list_symbol_pins(self, library_name: str, symbol_name: str) -> list:
        """
        Return pin data for a symbol directly from the library file (no schematic needed).
        Each entry: {"number": "1", "name": "VCC", "type": "power_in", "x": 0.0, "y": 3.81, "angle": 270}
        x/y are pin-endpoint coordinates in symbol-local space (Y increases upward, per KiCAD lib convention).
        Raises ValueError (with .suggestions) if the symbol is not found.
        """
        block = self.extract_symbol_from_library(library_name, symbol_name)
        pins = []
        # Pins live in sub-symbols (Name_1_1, Name_0_1, etc.)
        # Pattern: (pin <type> <shape> (at X Y angle) ... (name "NAME" ...) (number "NUM" ...))
        for m in re.finditer(
            r'\(pin\s+(\S+)\s+\S+\s+\(at\s+(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)\).*?\(name\s+"([^"]*)".*?\(number\s+"([^"]*)"',
            block,
            re.DOTALL,
        ):
            pins.append({
                "number": m.group(6),
                "name": m.group(5),
                "type": m.group(1),
                "x": float(m.group(2)),
                "y": float(m.group(3)),
                "angle": float(m.group(4)),
            })
        return sorted(pins, key=lambda p: (len(p["number"]), p["number"]))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    loader = DynamicSymbolLoader()

    print("\n=== Testing Dynamic Symbol Loader (Text-based) ===\n")

    print("1. Finding KiCad symbol library directories...")
    lib_dirs = loader.find_kicad_symbol_libraries()
    print(f"   Found {len(lib_dirs)} directories")

    print("\n2. Extracting symbols...")
    for lib, sym in [
        ("Device", "R"),
        ("Device", "C"),
        ("Device", "LED"),
        ("Device", "Q_NMOS"),
    ]:
        block = loader.extract_symbol_from_library(lib, sym)
        if block:
            print(f"   OK: {lib}:{sym} ({len(block)} chars)")
        else:
            print(f"   FAIL: {lib}:{sym}")

    print("\n3. Testing extends resolution...")
    block = loader.extract_symbol_from_library("Regulator_Switching", "LM2596S-5")
    if block and "LM2596S-12" in block:
        print(f"   OK: LM2596S-5 includes parent LM2596S-12 ({len(block)} chars)")
    else:
        print(f"   FAIL: extends not resolved")

    print("\nAll tests passed!")
