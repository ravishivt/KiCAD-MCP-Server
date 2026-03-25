#!/usr/bin/env python3
"""
KiCAD Python Interface Script for Model Context Protocol

This script handles communication between the MCP TypeScript server
and KiCAD's Python API (pcbnew). It receives commands via stdin as
JSON and returns responses via stdout also as JSON.
"""

import sys
import json
import traceback
import logging
import os
from pathlib import Path
from typing import Dict, Any, Optional

# Load .env file from project root (if present) before anything else reads env vars
def _load_dotenv():
    env_path = Path(__file__).parent.parent / '.env'
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, _, value = line.partition('=')
                    key = key.strip()
                    value = value.strip()
                    if key and key not in os.environ:
                        os.environ[key] = value

_load_dotenv()

# Import tool schemas and resource definitions
from schemas.tool_schemas import TOOL_SCHEMAS
from resources.resource_definitions import RESOURCE_DEFINITIONS, handle_resource_read

# Configure logging
log_dir = os.path.join(os.path.expanduser("~"), ".kicad-mcp", "logs")
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, "kicad_interface.log")

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(log_file)],
)
logger = logging.getLogger("kicad_interface")

# Log Python environment details
logger.info(f"Python version: {sys.version}")
logger.info(f"Python executable: {sys.executable}")
logger.info(f"Platform: {sys.platform}")
logger.info(f"Working directory: {os.getcwd()}")

# Windows-specific diagnostics
if sys.platform == "win32":
    logger.info("=== Windows Environment Diagnostics ===")
    logger.info(f"PYTHONPATH: {os.environ.get('PYTHONPATH', 'NOT SET')}")
    logger.info(f"PATH: {os.environ.get('PATH', 'NOT SET')[:200]}...")  # Truncate PATH

    # Check for common KiCAD installations
    common_kicad_paths = [r"C:\Program Files\KiCad", r"C:\Program Files (x86)\KiCad"]

    found_kicad = False
    for base_path in common_kicad_paths:
        if os.path.exists(base_path):
            logger.info(f"Found KiCAD installation at: {base_path}")
            # List versions
            try:
                versions = [
                    d
                    for d in os.listdir(base_path)
                    if os.path.isdir(os.path.join(base_path, d))
                ]
                logger.info(f"  Versions found: {', '.join(versions)}")
                for version in versions:
                    python_path = os.path.join(
                        base_path, version, "lib", "python3", "dist-packages"
                    )
                    if os.path.exists(python_path):
                        logger.info(f"  ✓ Python path exists: {python_path}")
                        found_kicad = True
                    else:
                        logger.warning(f"  ✗ Python path missing: {python_path}")
            except Exception as e:
                logger.warning(f"  Could not list versions: {e}")

    if not found_kicad:
        logger.warning("No KiCAD installations found in standard locations!")
        logger.warning(
            "Please ensure KiCAD 9.0+ is installed from https://www.kicad.org/download/windows/"
        )

    logger.info("========================================")

# Add utils directory to path for imports
utils_dir = os.path.join(os.path.dirname(__file__))
if utils_dir not in sys.path:
    sys.path.insert(0, utils_dir)

# Import platform helper and add KiCAD paths
from utils.platform_helper import PlatformHelper
from utils.kicad_process import check_and_launch_kicad, KiCADProcessManager

logger.info(f"Detecting KiCAD Python paths for {PlatformHelper.get_platform_name()}...")
paths_added = PlatformHelper.add_kicad_to_python_path()

if paths_added:
    logger.info("Successfully added KiCAD Python paths to sys.path")
else:
    logger.warning(
        "No KiCAD Python paths found - attempting to import pcbnew from system path"
    )

logger.info(f"Current Python path: {sys.path}")

# Check if auto-launch is enabled
AUTO_LAUNCH_KICAD = os.environ.get("KICAD_AUTO_LAUNCH", "false").lower() == "true"
if AUTO_LAUNCH_KICAD:
    logger.info("KiCAD auto-launch enabled")

# Check which backend to use
# KICAD_BACKEND can be: 'auto', 'ipc', or 'swig'
KICAD_BACKEND = os.environ.get("KICAD_BACKEND", "auto").lower()
logger.info(f"KiCAD backend preference: {KICAD_BACKEND}")

# Try to use IPC backend first if available and preferred
USE_IPC_BACKEND = False
ipc_backend = None

if KICAD_BACKEND in ("auto", "ipc"):
    try:
        logger.info("Checking IPC backend availability...")
        from kicad_api.ipc_backend import IPCBackend

        # Try to connect to running KiCAD
        ipc_backend = IPCBackend()
        if ipc_backend.connect():
            USE_IPC_BACKEND = True
            logger.info(f"✓ Using IPC backend - real-time UI sync enabled!")
            logger.info(f"  KiCAD version: {ipc_backend.get_version()}")
        else:
            logger.info("IPC backend available but KiCAD not running with IPC enabled")
            ipc_backend = None
    except ImportError:
        logger.info("IPC backend not available (kicad-python not installed)")
    except Exception as e:
        logger.info(f"IPC backend connection failed: {e}")
        ipc_backend = None

# Fall back to SWIG backend if IPC not available
if not USE_IPC_BACKEND and KICAD_BACKEND != "ipc":
    # Import KiCAD's Python API (SWIG)
    try:
        logger.info("Attempting to import pcbnew module (SWIG backend)...")
        import pcbnew  # type: ignore

        logger.info(f"Successfully imported pcbnew module from: {pcbnew.__file__}")
        logger.info(f"pcbnew version: {pcbnew.GetBuildVersion()}")
        logger.warning("Using SWIG backend - changes require manual reload in KiCAD UI")
    except ImportError as e:
        logger.error(f"Failed to import pcbnew module: {e}")
        logger.error(f"Current sys.path: {sys.path}")

        # Platform-specific help message
        help_message = ""
        if sys.platform == "win32":
            help_message = """
Windows Troubleshooting:
1. Verify KiCAD is installed: C:\\Program Files\\KiCad\\9.0
2. Check PYTHONPATH environment variable points to:
   C:\\Program Files\\KiCad\\9.0\\lib\\python3\\dist-packages
3. Test with: "C:\\Program Files\\KiCad\\9.0\\bin\\python.exe" -c "import pcbnew"
4. Log file location: %USERPROFILE%\\.kicad-mcp\\logs\\kicad_interface.log
5. Run setup-windows.ps1 for automatic configuration
"""
        elif sys.platform == "darwin":
            help_message = """
macOS Troubleshooting:
1. Verify KiCAD is installed: /Applications/KiCad/KiCad.app
2. Check PYTHONPATH points to KiCAD's Python packages
3. Run: python3 -c "import pcbnew" to test
"""
        else:  # Linux
            help_message = """
Linux Troubleshooting:
1. Verify KiCAD is installed: apt list --installed | grep kicad
2. Check: /usr/lib/kicad/lib/python3/dist-packages exists
3. Test: python3 -c "import pcbnew"
"""

        logger.error(help_message)

        error_response = {
            "success": False,
            "message": "Failed to import pcbnew module - KiCAD Python API not found",
            "errorDetails": f"Error: {str(e)}\n\n{help_message}\n\nPython sys.path:\n{chr(10).join(sys.path)}",
        }
        print(json.dumps(error_response))
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected error importing pcbnew: {e}")
        logger.error(traceback.format_exc())
        error_response = {
            "success": False,
            "message": "Error importing pcbnew module",
            "errorDetails": str(e),
        }
        print(json.dumps(error_response))
        sys.exit(1)

# If IPC-only mode requested but not available, exit with error
elif KICAD_BACKEND == "ipc" and not USE_IPC_BACKEND:
    error_response = {
        "success": False,
        "message": "IPC backend requested but not available",
        "errorDetails": "KiCAD must be running with IPC API enabled. Enable at: Preferences > Plugins > Enable IPC API Server",
    }
    print(json.dumps(error_response))
    sys.exit(1)

# Import command handlers
try:
    logger.info("Importing command handlers...")
    from commands.project import ProjectCommands
    from commands.board import BoardCommands
    from commands.component import ComponentCommands
    from commands.routing import RoutingCommands
    from commands.design_rules import DesignRuleCommands
    from commands.export import ExportCommands
    from commands.schematic import SchematicManager
    from commands.component_schematic import ComponentManager
    from commands.connection_schematic import ConnectionManager
    from commands.library_schematic import LibraryManager as SchematicLibraryManager
    from commands.library import (
        LibraryManager as FootprintLibraryManager,
        LibraryCommands,
    )
    from commands.library_symbol import SymbolLibraryManager, SymbolLibraryCommands
    from commands.jlcpcb import JLCPCBClient, test_jlcpcb_connection
    from commands.jlcpcb_parts import JLCPCBPartsManager
    from commands.datasheet_manager import DatasheetManager
    from commands.footprint import FootprintCreator
    from commands.symbol_creator import SymbolCreator
    from commands.freerouting import FreeroutingCommands

    logger.info("Successfully imported all command handlers")
except ImportError as e:
    logger.error(f"Failed to import command handlers: {e}")
    error_response = {
        "success": False,
        "message": "Failed to import command handlers",
        "errorDetails": str(e),
    }
    print(json.dumps(error_response))
    sys.exit(1)


class KiCADInterface:
    """Main interface class to handle KiCAD operations"""

    def __init__(self):
        """Initialize the interface and command handlers"""
        self.board = None
        self.project_filename = None
        self.use_ipc = USE_IPC_BACKEND
        self.ipc_backend = ipc_backend
        self.ipc_board_api = None

        if self.use_ipc:
            logger.info("Initializing with IPC backend (real-time UI sync enabled)")
            try:
                self.ipc_board_api = self.ipc_backend.get_board()
                logger.info("✓ Got IPC board API")
            except Exception as e:
                logger.warning(f"Could not get IPC board API: {e}")
        else:
            logger.info("Initializing with SWIG backend")

        logger.info("Initializing command handlers...")

        # Initialize footprint library manager
        self.footprint_library = FootprintLibraryManager()

        # Initialize command handlers
        self.project_commands = ProjectCommands(self.board)
        self.board_commands = BoardCommands(self.board)
        self.component_commands = ComponentCommands(self.board, self.footprint_library)
        self.routing_commands = RoutingCommands(self.board)
        self.freerouting_commands = FreeroutingCommands(self.board)
        self.design_rule_commands = DesignRuleCommands(self.board)
        self.export_commands = ExportCommands(self.board)
        self.library_commands = LibraryCommands(self.footprint_library)
        self._current_project_path: Optional[Path] = None  # set when boardPath is known

        # Initialize symbol library manager (for searching local KiCad symbol libraries)
        self.symbol_library_commands = SymbolLibraryCommands()

        # Initialize JLCPCB API integration
        self.jlcpcb_client = JLCPCBClient()  # Official API (requires auth)
        self.jlcpcb_parts = JLCPCBPartsManager()

        # Schematic-related classes don't need board reference
        # as they operate directly on schematic files

        # Command routing dictionary
        self.command_routes = {
            # Project commands
            "create_project": self.project_commands.create_project,
            "open_project": self.project_commands.open_project,
            "save_project": self.project_commands.save_project,
            "snapshot_project": self._handle_snapshot_project,
            "get_project_info": self.project_commands.get_project_info,
            # Board commands
            "set_board_size": self.board_commands.set_board_size,
            "add_layer": self.board_commands.add_layer,
            "set_active_layer": self.board_commands.set_active_layer,
            "get_board_info": self.board_commands.get_board_info,
            "get_layer_list": self.board_commands.get_layer_list,
            "get_board_2d_view": self.board_commands.get_board_2d_view,
            "get_board_extents": self.board_commands.get_board_extents,
            "add_board_outline": self.board_commands.add_board_outline,
            "add_mounting_hole": self.board_commands.add_mounting_hole,
            "add_text": self.board_commands.add_text,
            "add_board_text": self.board_commands.add_text,  # Alias for TypeScript tool
            # Component commands
            "route_pad_to_pad": self.routing_commands.route_pad_to_pad,
            "place_component": self._handle_place_component,
            "move_component": self.component_commands.move_component,
            "rotate_component": self.component_commands.rotate_component,
            "delete_component": self.component_commands.delete_component,
            "edit_component": self.component_commands.edit_component,
            "get_component_properties": self.component_commands.get_component_properties,
            "get_component_list": self.component_commands.get_component_list,
            "find_component": self.component_commands.find_component,
            "get_component_pads": self.component_commands.get_component_pads,
            "get_pad_position": self.component_commands.get_pad_position,
            "place_component_array": self.component_commands.place_component_array,
            "align_components": self.component_commands.align_components,
            "duplicate_component": self.component_commands.duplicate_component,
            # Routing commands
            "add_net": self.routing_commands.add_net,
            "route_trace": self.routing_commands.route_trace,
            "add_via": self.routing_commands.add_via,
            "delete_trace": self.routing_commands.delete_trace,
            "query_traces": self.routing_commands.query_traces,
            "modify_trace": self.routing_commands.modify_trace,
            "copy_routing_pattern": self.routing_commands.copy_routing_pattern,
            "get_nets_list": self.routing_commands.get_nets_list,
            "create_netclass": self.routing_commands.create_netclass,
            "add_copper_pour": self.routing_commands.add_copper_pour,
            "route_differential_pair": self.routing_commands.route_differential_pair,
            "refill_zones": self._handle_refill_zones,
            # Design rule commands
            "set_design_rules": self.design_rule_commands.set_design_rules,
            "get_design_rules": self.design_rule_commands.get_design_rules,
            "run_drc": self.design_rule_commands.run_drc,
            "get_drc_violations": self.design_rule_commands.get_drc_violations,
            # Export commands
            "export_gerber": self.export_commands.export_gerber,
            "export_pdf": self.export_commands.export_pdf,
            "export_svg": self.export_commands.export_svg,
            "export_3d": self.export_commands.export_3d,
            "export_bom": self.export_commands.export_bom,
            # Library commands (footprint management)
            "list_libraries": self.library_commands.list_libraries,
            "search_footprints": self.library_commands.search_footprints,
            "list_library_footprints": self.library_commands.list_library_footprints,
            "get_footprint_info": self.library_commands.get_footprint_info,
            # Symbol library commands (local KiCad symbol library search)
            "list_symbol_libraries": self.symbol_library_commands.list_symbol_libraries,
            "search_symbols": self.symbol_library_commands.search_symbols,
            "list_library_symbols": self.symbol_library_commands.list_library_symbols,
            "get_symbol_info": self.symbol_library_commands.get_symbol_info,
            # JLCPCB commands
            "search_jlcpcb_parts": self._handle_search_jlcpcb_parts,
            "get_jlcpcb_part": self._handle_get_jlcpcb_part,
            "get_jlcpcb_database_stats": self._handle_get_jlcpcb_database_stats,
            "get_jlcpcb_categories": self._handle_get_jlcpcb_categories,
            "suggest_jlcpcb_alternatives": self._handle_suggest_jlcpcb_alternatives,
            # Datasheet commands
            "enrich_datasheets": self._handle_enrich_datasheets,
            "get_datasheet_url": self._handle_get_datasheet_url,
            # Schematic commands
            "create_schematic": self._handle_create_schematic,
            "load_schematic": self._handle_load_schematic,
            "add_schematic_component": self._handle_add_schematic_component,
            "batch_add_components": self._handle_batch_add_components,
            "delete_schematic_component": self._handle_delete_schematic_component,
            "edit_schematic_component": self._handle_edit_schematic_component,
            "batch_edit_schematic_components": self._handle_batch_edit_schematic_components,
            "get_schematic_component": self._handle_get_schematic_component,
            "add_schematic_wire": self._handle_add_schematic_wire,
            "add_schematic_connection": self._handle_add_schematic_connection,
            "add_schematic_net_label": self._handle_add_schematic_net_label,
            "set_schematic_property_position": self._handle_set_schematic_property_position,
            "batch_set_schematic_property_positions": self._handle_batch_set_schematic_property_positions,
            "add_no_connect": self._handle_add_no_connect,
            "batch_add_no_connects": self._handle_batch_add_no_connects,
            "save_schematic": self._handle_save_schematic,
            "connect_to_net": self._handle_connect_to_net,
            "batch_connect": self._handle_batch_connect,
            "batch_add_and_connect": self._handle_batch_add_and_connect,
            "connect_passthrough": self._handle_connect_passthrough,
            "get_schematic_pin_locations": self._handle_get_schematic_pin_locations,
            "get_net_connections": self._handle_get_net_connections,
            "validate_schematic": self._handle_validate_schematic,
            "run_erc": self._handle_run_erc,
            "place_net_label_at_pin": self._handle_place_net_label_at_pin,
            "list_unconnected_pins": self._handle_list_unconnected_pins,
            "search_schematic_symbols": self._handle_search_schematic_symbols,
            "list_symbol_pins": self._handle_list_symbol_pins,
            "batch_list_symbol_pins": self._handle_batch_list_symbol_pins,
            "generate_netlist": self._handle_generate_netlist,
            "sync_schematic_to_board": self._handle_sync_schematic_to_board,
            "list_schematic_libraries": self._handle_list_schematic_libraries,
            "get_schematic_view": self._handle_get_schematic_view,
            "list_schematic_components": self._handle_list_schematic_components,
            "check_schematic_layout": self._handle_check_schematic_layout,
            "autoplace_schematic_fields": self._handle_autoplace_schematic_fields,
            "list_schematic_nets": self._handle_list_schematic_nets,
            "find_single_pin_nets": self._handle_find_single_pin_nets,
            "classify_nets": self._handle_classify_nets,
            "get_net_graph": self._handle_get_net_graph,
            "get_schematic_summary": self._handle_get_schematic_summary,
            "list_schematic_wires": self._handle_list_schematic_wires,
            "list_schematic_labels": self._handle_list_schematic_labels,
            "move_schematic_component": self._handle_move_schematic_component,
            "rotate_schematic_component": self._handle_rotate_schematic_component,
            "annotate_schematic": self._handle_annotate_schematic,
            "add_hierarchical_sheet": self._handle_add_hierarchical_sheet,
            "create_hierarchical_subsheet": self._handle_create_hierarchical_subsheet,
            "delete_schematic_wire": self._handle_delete_schematic_wire,
            "delete_schematic_net_label": self._handle_delete_schematic_net_label,
            "export_schematic_pdf": self._handle_export_schematic_pdf,
            "export_schematic_svg": self._handle_export_schematic_svg,
            "import_svg_logo": self._handle_import_svg_logo,
            # UI/Process management commands
            "check_kicad_ui": self._handle_check_kicad_ui,
            "launch_kicad_ui": self._handle_launch_kicad_ui,
            # IPC-specific commands (real-time operations)
            "get_backend_info": self._handle_get_backend_info,
            "ipc_add_track": self._handle_ipc_add_track,
            "ipc_add_via": self._handle_ipc_add_via,
            "ipc_add_text": self._handle_ipc_add_text,
            "ipc_list_components": self._handle_ipc_list_components,
            "ipc_get_tracks": self._handle_ipc_get_tracks,
            "ipc_get_vias": self._handle_ipc_get_vias,
            "ipc_save_board": self._handle_ipc_save_board,
            # Footprint commands
            "create_footprint": self._handle_create_footprint,
            "edit_footprint_pad": self._handle_edit_footprint_pad,
            "list_footprint_libraries": self._handle_list_footprint_libraries,
            "register_footprint_library": self._handle_register_footprint_library,
            # Symbol creator commands
            "create_symbol": self._handle_create_symbol,
            "delete_symbol": self._handle_delete_symbol,
            "list_symbols_in_library": self._handle_list_symbols_in_library,
            "register_symbol_library": self._handle_register_symbol_library,
            # Freerouting autoroute commands
            "autoroute": self.freerouting_commands.autoroute,
            "export_dsn": self.freerouting_commands.export_dsn,
            "import_ses": self.freerouting_commands.import_ses,
            "check_freerouting": self.freerouting_commands.check_freerouting,
        }

        logger.info(
            f"KiCAD interface initialized (backend: {'IPC' if self.use_ipc else 'SWIG'})"
        )

    # Commands that can be handled via IPC for real-time updates
    IPC_CAPABLE_COMMANDS = {
        # Routing commands
        "route_trace": "_ipc_route_trace",
        "add_via": "_ipc_add_via",
        "add_net": "_ipc_add_net",
        "delete_trace": "_ipc_delete_trace",
        "get_nets_list": "_ipc_get_nets_list",
        # Zone commands
        "add_copper_pour": "_ipc_add_copper_pour",
        "refill_zones": "_ipc_refill_zones",
        # Board commands
        "add_text": "_ipc_add_text",
        "add_board_text": "_ipc_add_text",
        "set_board_size": "_ipc_set_board_size",
        "get_board_info": "_ipc_get_board_info",
        "add_board_outline": "_ipc_add_board_outline",
        "add_mounting_hole": "_ipc_add_mounting_hole",
        "get_layer_list": "_ipc_get_layer_list",
        # Component commands
        "place_component": "_ipc_place_component",
        "move_component": "_ipc_move_component",
        "rotate_component": "_ipc_rotate_component",
        "delete_component": "_ipc_delete_component",
        "get_component_list": "_ipc_get_component_list",
        "get_component_properties": "_ipc_get_component_properties",
        # Save command
        "save_project": "_ipc_save_project",
    }

    # KiCad-internal property names that are not user-visible component properties
    _KICAD_INTERNAL_PROPS = frozenset(
        {"ki_keywords", "ki_description", "ki_fp_filters", "ki_locked", "ki_model"}
    )

    @staticmethod
    def _find_matching_paren(s: str, start: int) -> int:
        """Return index of the closing ')' that matches the '(' at position start."""
        depth = 0
        i = start
        while i < len(s):
            if s[i] == "(":
                depth += 1
            elif s[i] == ")":
                depth -= 1
                if depth == 0:
                    return i
            i += 1
        return -1

    @staticmethod
    def _extract_component_properties(block_text: str, exclude_internal: bool = True) -> dict:
        """
        Extract all (property "Name" "Value" ...) entries from a placed symbol block.
        Returns {"Name": "Value", ...}.  When exclude_internal=True, ki_* fields are skipped.
        """
        import re
        prop_pattern = re.compile(r'\(property\s+"([^"]*)"\s+"([^"]*)"')
        props = {}
        for m in prop_pattern.finditer(block_text):
            name, value = m.group(1), m.group(2)
            if exclude_internal and name in KiCADInterface._KICAD_INTERNAL_PROPS:
                continue
            props[name] = value
        return props

    @staticmethod
    def _extract_property_position(block_text: str, property_name: str):
        """Extract the (at x y angle) from a named property inside a symbol block.
        Returns {"x": float, "y": float, "angle": float} or None if not found."""
        import re
        pat = re.compile(
            r'\(property\s+"' + re.escape(property_name) + r'"\s+"[^"]*"\s+\(at\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\)'
        )
        m = pat.search(block_text)
        if m:
            return {"x": float(m.group(1)), "y": float(m.group(2)), "angle": float(m.group(3))}
        return None

    @staticmethod
    def _extract_property_visible(block_text: str, property_name: str) -> bool:
        """Return True if the named property is visible (no hide flag), False if hidden."""
        import re
        prop_pat = re.compile(r'\(property\s+"' + re.escape(property_name) + r'"')
        m = prop_pat.search(block_text)
        if not m:
            return True
        # Walk parens to extract the full property sub-expression
        start = m.start()
        depth = 0
        i = start
        while i < len(block_text):
            if block_text[i] == '(':
                depth += 1
            elif block_text[i] == ')':
                depth -= 1
                if depth == 0:
                    prop_sub = block_text[start:i + 1]
                    return '(hide yes)' not in prop_sub and '(hide)' not in prop_sub
            i += 1
        return True

    @staticmethod
    def _find_placed_symbol_block(content: str, reference: str):
        """
        Find the placed symbol block for *reference* in schematic file content.
        Returns (block_text, block_start, block_end) or (None, -1, -1) if not found.
        Skips the lib_symbols section.
        """
        import re
        lib_sym_pos = content.find("(lib_symbols")
        lib_sym_end = (
            KiCADInterface._find_matching_paren(content, lib_sym_pos)
            if lib_sym_pos >= 0
            else -1
        )
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
            end = KiCADInterface._find_matching_paren(content, pos)
            if end < 0:
                search_start = pos + 1
                continue
            block_text = content[pos: end + 1]
            if re.search(
                r'\(property\s+"Reference"\s+"' + re.escape(reference) + r'"',
                block_text,
            ):
                return block_text, pos, end
            search_start = end + 1
        return None, -1, -1

    def handle_command(self, command: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Route command to appropriate handler, preferring IPC when available"""
        logger.info(f"Handling command: {command}")
        logger.debug(f"Command parameters: {params}")

        try:
            # Check if we can use IPC for this command (real-time UI sync)
            if (
                self.use_ipc
                and self.ipc_board_api
                and command in self.IPC_CAPABLE_COMMANDS
            ):
                ipc_handler_name = self.IPC_CAPABLE_COMMANDS[command]
                ipc_handler = getattr(self, ipc_handler_name, None)

                if ipc_handler:
                    logger.info(f"Using IPC backend for {command} (real-time sync)")
                    result = ipc_handler(params)

                    # Add indicator that IPC was used
                    if isinstance(result, dict):
                        result["_backend"] = "ipc"
                        result["_realtime"] = True

                    logger.debug(f"IPC command result: {result}")
                    return result

            # Fall back to SWIG-based handler
            if self.use_ipc and command in self.IPC_CAPABLE_COMMANDS:
                logger.warning(
                    f"IPC handler not available for {command}, falling back to SWIG (deprecated)"
                )

            # Get the handler for the command
            handler = self.command_routes.get(command)

            if handler:
                # Execute the command
                result = handler(params)
                logger.debug(f"Command result: {result}")

                # Add backend indicator
                if isinstance(result, dict):
                    result["_backend"] = "swig"
                    result["_realtime"] = False

                # Update board reference if command was successful
                if result.get("success", False):
                    if command == "create_project" or command == "open_project":
                        logger.info("Updating board reference...")
                        # Get board from the project commands handler
                        self.board = self.project_commands.board
                        self._update_command_handlers()
                    elif command in self._BOARD_MUTATING_COMMANDS:
                        # Auto-save after every board mutation via SWIG.
                        # Prevents data loss if Claude hits context limit before
                        # an explicit save_project call.
                        self._auto_save_board()

                return result
            else:
                logger.error(f"Unknown command: {command}")
                return {
                    "success": False,
                    "message": f"Unknown command: {command}",
                    "errorDetails": "The specified command is not supported",
                }

        except Exception as e:
            # Get the full traceback
            traceback_str = traceback.format_exc()
            logger.error(f"Error handling command {command}: {str(e)}\n{traceback_str}")
            return {
                "success": False,
                "message": f"Error handling command: {command}",
                "errorDetails": f"{str(e)}\n{traceback_str}",
            }

    # Board-mutating commands that trigger auto-save on SWIG path
    _BOARD_MUTATING_COMMANDS = {
        "place_component",
        "move_component",
        "rotate_component",
        "delete_component",
        "route_trace",
        "route_pad_to_pad",
        "add_via",
        "delete_trace",
        "add_net",
        "add_board_outline",
        "add_mounting_hole",
        "add_text",
        "add_board_text",
        "add_copper_pour",
        "refill_zones",
        "import_svg_logo",
        "sync_schematic_to_board",
        "connect_passthrough",
    }

    def _auto_save_board(self):
        """Save board to disk after SWIG mutations.
        Called automatically after every board-mutating SWIG command so that
        data is not lost if Claude hits the context limit before save_project.
        """
        try:
            if self.board:
                board_path = self.board.GetFileName()
                if board_path:
                    pcbnew.SaveBoard(board_path, self.board)
                    logger.debug(f"Auto-saved board to: {board_path}")
        except Exception as e:
            logger.warning(f"Auto-save failed: {e}")

    def _update_command_handlers(self):
        """Update board reference in all command handlers"""
        logger.debug("Updating board reference in command handlers")
        self.project_commands.board = self.board
        self.board_commands.board = self.board
        self.component_commands.board = self.board
        self.routing_commands.board = self.board
        self.design_rule_commands.board = self.board
        self.export_commands.board = self.board
        self.freerouting_commands.board = self.board

    # Schematic command handlers
    def _handle_create_schematic(self, params):
        """Create a new schematic"""
        logger.info("Creating schematic")
        try:
            # Support multiple parameter naming conventions for compatibility:
            # - TypeScript tools use: name, path
            # - Python schema uses: filename, title
            # - Legacy uses: projectName, path, metadata
            project_name = (
                params.get("projectName") or params.get("name") or params.get("title")
            )

            # Compute the full output file_path before calling create_schematic.
            # BUG-2 fix (a): if `path` ends with .kicad_sch, treat it as the full
            #   output path (don't append name again).
            # BUG-2 fix (b): when no path given and a project board is loaded,
            #   default to the project directory instead of CWD.
            filename = params.get("filename")
            if filename:
                if filename.endswith(".kicad_sch"):
                    file_path = os.path.abspath(filename)
                    project_name = project_name or os.path.splitext(os.path.basename(file_path))[0]
                else:
                    path = os.path.dirname(filename) or "."
                    project_name = project_name or os.path.basename(filename)
                    file_path = os.path.abspath(os.path.join(path, f"{project_name}.kicad_sch"))
            else:
                path_param = params.get("path", "")
                if path_param and path_param.endswith(".kicad_sch"):
                    # path is actually a full file path — use it directly
                    file_path = os.path.abspath(path_param)
                    project_name = project_name or os.path.splitext(os.path.basename(file_path))[0]
                elif path_param:
                    file_path = os.path.abspath(os.path.join(path_param, f"{project_name}.kicad_sch"))
                elif self.board:
                    # Default to project directory when a project is open
                    board_dir = os.path.dirname(self.board.GetFileName())
                    file_path = os.path.abspath(os.path.join(board_dir, f"{project_name}.kicad_sch"))
                else:
                    file_path = os.path.abspath(f"{project_name}.kicad_sch")

            metadata = params.get("metadata", {})

            if not project_name:
                return {
                    "success": False,
                    "message": "Schematic name is required. Provide 'name', 'projectName', or 'filename' parameter.",
                }

            # Warn if the schematic is in a subdirectory relative to the nearest .kicad_pro.
            # ${KIPRJMOD} is resolved relative to the project root, so sub-sheet paths
            # outside the root directory cause "Symbol not found" errors.
            _subdir_warning = None
            try:
                from commands.dynamic_symbol_loader import _find_project_root as _fpr
                _fp = Path(file_path)
                _proj_root = _fpr(_fp.parent)
                if _fp.parent.resolve() != _proj_root.resolve() and _proj_root != _fp.parent:
                    _rel = _fp.relative_to(_proj_root) if _fp.is_relative_to(_proj_root) else _fp.name
                    _subdir_warning = (
                        f"Sub-sheet created at {_rel} — library paths using ${{KIPRJMOD}} "
                        f"may not resolve correctly from this location. Place the sub-sheet "
                        f"in the same directory as the .kicad_pro file to avoid lookup errors."
                    )
            except Exception:
                pass

            # Pass the full file_path so create_schematic writes to the right location
            schematic = SchematicManager.create_schematic(file_path, metadata)
            success = SchematicManager.save_schematic(schematic, file_path)

            from commands.schematic import _last_removed_templates
            # Read back the schematic UUID from the saved file so callers can use it
            schematic_uuid = None
            try:
                import re as _re
                with open(file_path, "r", encoding="utf-8") as _f:
                    _content = _f.read()
                _m = _re.search(r'\(uuid\s+([0-9a-fA-F-]+)\)', _content)
                if _m:
                    schematic_uuid = _m.group(1)
            except Exception:
                pass

            result = {"success": success, "file_path": file_path}
            if schematic_uuid:
                result["schematic_uuid"] = schematic_uuid
            if _last_removed_templates:
                result["removed_template_components"] = list(_last_removed_templates)
                result["note"] = f"Removed {len(_last_removed_templates)} template placeholder components"
            if _subdir_warning:
                result["warning"] = _subdir_warning
            return result
        except Exception as e:
            logger.error(f"Error creating schematic: {str(e)}")
            return {"success": False, "message": str(e)}

    def _handle_load_schematic(self, params):
        """Load an existing schematic"""
        logger.info("Loading schematic")
        try:
            filename = params.get("filename")

            if not filename:
                return {"success": False, "message": "Filename is required"}

            schematic = SchematicManager.load_schematic(filename)
            success = schematic is not None

            if success:
                metadata = SchematicManager.get_schematic_metadata(schematic)
                return {"success": success, "metadata": metadata}
            else:
                return {"success": False, "message": "Failed to load schematic"}
        except Exception as e:
            logger.error(f"Error loading schematic: {str(e)}")
            return {"success": False, "message": str(e)}

    def _handle_place_component(self, params):
        """Place a component on the PCB, with project-local fp-lib-table support.
        If boardPath is given and differs from the currently loaded board, the
        board is reloaded from boardPath before placing — prevents silent failures
        when Claude provides a boardPath that was not yet loaded.
        """
        from pathlib import Path

        board_path = params.get("boardPath")
        if board_path:
            board_path_norm = str(Path(board_path).resolve())
            current_board_file = (
                str(Path(self.board.GetFileName()).resolve()) if self.board else ""
            )
            if board_path_norm != current_board_file:
                logger.info(
                    f"boardPath differs from current board — reloading: {board_path}"
                )
                try:
                    self.board = pcbnew.LoadBoard(board_path)
                    self._update_command_handlers()
                    logger.info("Board reloaded from boardPath")
                except Exception as e:
                    logger.error(f"Failed to reload board from boardPath: {e}")
                    return {
                        "success": False,
                        "message": f"Could not load board from boardPath: {board_path}",
                        "errorDetails": str(e),
                    }

            project_path = Path(board_path).parent
            if project_path != getattr(self, "_current_project_path", None):
                self._current_project_path = project_path
                local_lib = FootprintLibraryManager(project_path=project_path)
                self.component_commands = ComponentCommands(self.board, local_lib)
                logger.info(
                    f"Reloaded FootprintLibraryManager with project_path={project_path}"
                )

        return self.component_commands.place_component(params)

    def _handle_add_schematic_component(self, params):
        """Add a component to a schematic using text-based injection (no sexpdata)"""
        logger.info("Adding component to schematic")
        try:
            from pathlib import Path
            from commands.dynamic_symbol_loader import DynamicSymbolLoader, _find_project_root

            schematic_path = params.get("schematicPath")
            component = params.get("component", {})

            if not schematic_path:
                return {"success": False, "message": "Schematic path is required"}
            if not component:
                return {"success": False, "message": "Component definition is required"}

            from commands.dynamic_symbol_loader import _snap

            comp_type = component.get("type", "R")
            library = component.get("library", "Device")
            reference = component.get("reference", "X?")
            value = component.get("value", comp_type)
            footprint = component.get("footprint", "")
            x = component.get("x", 0)
            y = component.get("y", 0)
            rotation = component.get("rotation", 0)
            include_pins = component.get("includePins", False)

            # Snap to KiCAD 50mil grid so pins land on-grid (same snap applied inside loader)
            snapped_x = _snap(x)
            snapped_y = _snap(y)

            # Derive project path: walk up from the schematic's directory to find the
            # nearest .kicad_pro so ${KIPRJMOD} resolves correctly for sub-sheets in
            # subdirectories (e.g. project/sheets/foo.kicad_sch → project/).
            schematic_file = Path(schematic_path)
            derived_project_path = _find_project_root(schematic_file.parent)

            loader = DynamicSymbolLoader(project_path=derived_project_path)
            loader.add_component(
                schematic_file,
                library,
                comp_type,
                reference=reference,
                value=value,
                footprint=footprint,
                x=x,
                y=y,
                rotation=rotation,
                project_path=derived_project_path,
            )

            # Resolve footprint: use the caller-supplied value, or extract from library
            resolved_footprint = footprint
            if not resolved_footprint:
                try:
                    sym_block = loader.extract_symbol_from_library(library, comp_type)
                    if sym_block:
                        import re as _re
                        fp_match = _re.search(r'\(property\s+"Footprint"\s+"([^"]*)"', sym_block)
                        if fp_match:
                            resolved_footprint = fp_match.group(1)
                except Exception:
                    pass

            # If this schematic is a sub-sheet of another, fix hierarchical instance
            # paths so parent-context ERC shows correct references even when
            # annotate_schematic is never called (clients often supply explicit refs).
            sch_name = schematic_file.name
            for candidate in schematic_file.parent.glob("*.kicad_sch"):
                if candidate.resolve() == schematic_file.resolve():
                    continue
                try:
                    candidate_content = candidate.read_text(encoding="utf-8")
                    if sch_name in candidate_content:
                        self._fix_subsheet_instances(str(candidate), candidate_content)
                except Exception:
                    pass

            response = {
                "success": True,
                "component_reference": reference,
                "symbol_source": f"{library}:{comp_type}",
                "snapped_position": {"x": snapped_x, "y": snapped_y},
                "footprint": resolved_footprint or "",
            }

            if include_pins:
                # Return pin locations so caller doesn't need a separate round-trip
                from commands.pin_locator import PinLocator
                locator = PinLocator()
                pins_raw = locator.get_all_symbol_pins(schematic_file, reference) or {}
                # Enrich with pin names from lib definition
                lib_id = f"{library}:{comp_type}"
                pins_def = locator.get_symbol_pins(schematic_file, lib_id) or {}
                pins = {}
                for pin_num, coords in pins_raw.items():
                    pins[pin_num] = {
                        "x": coords[0],
                        "y": coords[1],
                        "name": pins_def.get(str(pin_num), {}).get("name", str(pin_num)),
                    }
                response["pins"] = pins

            return response
        except Exception as e:
            logger.error(f"Error adding component to schematic: {str(e)}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_batch_add_components(self, params):
        """Add multiple components to a schematic in a single call."""
        logger.info("Batch adding components to schematic")
        try:
            import re as _re
            from pathlib import Path
            from commands.dynamic_symbol_loader import DynamicSymbolLoader, _snap
            from commands.pin_locator import PinLocator

            schematic_path = params.get("schematicPath")
            components = params.get("components", [])
            origin_x = params.get("origin_x", 0) or 0
            origin_y = params.get("origin_y", 0) or 0
            auto_position_fields = params.get("auto_position_fields", True)

            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}
            if not components:
                return {"success": False, "message": "components list is required and must be non-empty"}

            schematic_file = Path(schematic_path)
            project_path = schematic_file.parent
            loader = DynamicSymbolLoader(project_path=project_path)
            locator = PinLocator()

            results = []
            errors = []

            for comp in components:
                symbol = comp.get("symbol", "")
                if ":" not in symbol:
                    errors.append({"symbol": symbol, "reference": comp.get("reference", "?"), "error": "symbol must be 'Library:SymbolName'"})
                    continue

                library, sym_name = symbol.split(":", 1)
                reference = comp.get("reference", "X?")
                value = comp.get("value", sym_name)
                footprint = comp.get("footprint", "")
                pos = comp.get("position", {})
                x = (pos.get("x", 0) if isinstance(pos, dict) else 0) + origin_x
                y = (pos.get("y", 0) if isinstance(pos, dict) else 0) + origin_y
                rotation = comp.get("rotation", 0)
                include_pins = comp.get("includePins", False)

                try:
                    loader.add_component(
                        schematic_file,
                        library,
                        sym_name,
                        reference=reference,
                        value=value,
                        footprint=footprint,
                        x=x,
                        y=y,
                        rotation=rotation,
                        project_path=project_path,
                    )

                    entry = {
                        "reference": reference,
                        "symbol": symbol,
                        "snapped_position": {"x": _snap(x), "y": _snap(y)},
                    }

                    # Validate footprint — warn per-component without blocking placement.
                    if footprint:
                        fp_resolved = self.footprint_library.find_footprint(footprint)
                        if fp_resolved is None:
                            entry["footprint_warning"] = (
                                f"Footprint '{footprint}' was not found in any registered footprint library "
                                "(validation only — the footprint string WAS written to the schematic's "
                                "Footprint property field). If the string is correct it will still work in KiCad. "
                                "Use search_footprints to find a valid footprint string."
                            )

                    # Invalidate cache immediately so fresh pin lookups see the just-placed symbol
                    locator._schematic_cache.pop(str(schematic_file), None)

                    # Fetch all pins once — reused for field positioning, includePins, and body_bbox
                    _all_pins = locator.get_all_symbol_pins(schematic_file, reference) or {}

                    # Auto-position ref/value fields using actual pin axis direction.
                    # Rules (always angle=0 for readable horizontal text):
                    #   2-pin: axis is vertical (dy>dx) → labels left/right of body
                    #          axis is horizontal (dx>dy) → labels above/below body
                    #   multi-pin: labels above the topmost pin and below the bottommost pin
                    block_text = None
                    if auto_position_fields:
                        cx, cy = _snap(x), _snap(y)
                        _OFF = 2.54
                        _num_pins = len(_all_pins)
                        if _num_pins == 2:
                            _coords = list(_all_pins.values())
                            _p1x = float(_coords[0][0]) if isinstance(_coords[0], (list, tuple)) else float(_coords[0]["x"])
                            _p1y = float(_coords[0][1]) if isinstance(_coords[0], (list, tuple)) else float(_coords[0]["y"])
                            _p2x = float(_coords[1][0]) if isinstance(_coords[1], (list, tuple)) else float(_coords[1]["x"])
                            _p2y = float(_coords[1][1]) if isinstance(_coords[1], (list, tuple)) else float(_coords[1]["y"])
                            if abs(_p1y - _p2y) > abs(_p1x - _p2x):
                                # Vertical pin axis (pins top/bottom) → labels left/right
                                _field_positions = [
                                    ("Reference", round(cx - _OFF, 4), cy, 0),
                                    ("Value",     round(cx + _OFF, 4), cy, 0),
                                ]
                            else:
                                # Horizontal pin axis (pins left/right) → labels above/below
                                _field_positions = [
                                    ("Reference", cx, round(cy - _OFF, 4), 0),
                                    ("Value",     cx, round(cy + _OFF, 4), 0),
                                ]
                        elif _all_pins:
                            # Multi-pin: above the topmost pin tip, below the bottommost pin tip
                            _pin_ys = [float(c[1]) if isinstance(c, (list, tuple)) else float(c["y"]) for c in _all_pins.values()]
                            _field_positions = [
                                ("Reference", cx, round(min(_pin_ys) - _OFF, 4), 0),
                                ("Value",     cx, round(max(_pin_ys) + _OFF, 4), 0),
                            ]
                        else:
                            # No pins found — fallback to above/below center
                            _field_positions = [
                                ("Reference", cx, round(cy - _OFF, 4), 0),
                                ("Value",     cx, round(cy + _OFF, 4), 0),
                            ]
                        try:
                            raw_content = schematic_file.read_text(encoding="utf-8")
                            block_text, block_start, block_end = KiCADInterface._find_placed_symbol_block(raw_content, reference)
                            if block_text:
                                new_block = block_text
                                for _prop, _px, _py, _pa in _field_positions:
                                    _pat = _re.compile(
                                        r'(\(property\s+"' + _re.escape(_prop) + r'"\s+"[^"]*"\s+)'
                                        r'\(at\s+[-\d.]+\s+[-\d.]+\s+[-\d.]+\)'
                                    )
                                    new_block, _ = _pat.subn(
                                        r'\g<1>' + f"(at {_px} {_py} {_pa})", new_block
                                    )
                                if new_block != block_text:
                                    raw_content = raw_content[:block_start] + new_block + raw_content[block_end + 1:]
                                    schematic_file.write_text(raw_content, encoding="utf-8")
                                    block_text = new_block
                        except Exception:
                            pass
                    else:
                        # Read block_text for property position extraction only
                        try:
                            raw_content = schematic_file.read_text(encoding="utf-8")
                            block_text, _, _ = KiCADInterface._find_placed_symbol_block(raw_content, reference)
                        except Exception:
                            pass

                    if block_text:
                        ref_pos = KiCADInterface._extract_property_position(block_text, "Reference")
                        val_pos = KiCADInterface._extract_property_position(block_text, "Value")
                        if ref_pos:
                            entry["ref_position"] = ref_pos
                        if val_pos:
                            entry["value_position"] = val_pos

                    if include_pins:
                        pins_def = locator.get_symbol_pins(schematic_file, symbol) or {}
                        pins = {}
                        for pin_num, coords in _all_pins.items():
                            pins[pin_num] = {
                                "x": coords[0],
                                "y": coords[1],
                                "name": pins_def.get(str(pin_num), {}).get("name", str(pin_num)),
                            }
                        entry["pins"] = pins
                        if not pins:
                            entry["pins_error"] = (
                                f"Pin extraction returned no data for {reference} ({symbol}). "
                                "Use get_schematic_pin_locations as a follow-up if pin coordinates are needed."
                            )

                    # Compute body_bbox from pin spread (best-effort), fall back to center ± 2.54mm
                    try:
                        if _all_pins:
                            xs = [c[0] if isinstance(c, (list, tuple)) else c["x"] for c in _all_pins.values()]
                            ys = [c[1] if isinstance(c, (list, tuple)) else c["y"] for c in _all_pins.values()]
                            pad = 1.27
                            entry["body_bbox"] = {
                                "x_min": min(xs) - pad, "y_min": min(ys) - pad,
                                "x_max": max(xs) + pad, "y_max": max(ys) + pad,
                            }
                        else:
                            cx, cy = _snap(x), _snap(y)
                            entry["body_bbox"] = {"x_min": cx - 2.54, "y_min": cy - 2.54, "x_max": cx + 2.54, "y_max": cy + 2.54}
                    except Exception:
                        cx, cy = _snap(x), _snap(y)
                        entry["body_bbox"] = {"x_min": cx - 2.54, "y_min": cy - 2.54, "x_max": cx + 2.54, "y_max": cy + 2.54}

                    results.append(entry)

                except Exception as e:
                    logger.error(f"Error adding {reference} ({symbol}): {e}")
                    errors.append({"symbol": symbol, "reference": reference, "error": str(e)})

            # If this schematic is a sub-sheet of another, fix hierarchical instance
            # paths now so parent-context ERC shows correct references even when
            # annotate_schematic is never called (clients often supply explicit refs).
            sch_name = schematic_file.name
            for candidate in project_path.glob("*.kicad_sch"):
                if candidate.resolve() == schematic_file.resolve():
                    continue
                try:
                    candidate_content = candidate.read_text(encoding="utf-8")
                    if sch_name in candidate_content:
                        self._fix_subsheet_instances(str(candidate), candidate_content)
                except Exception:
                    pass

            # Compute overall placement bounding box from all placed components
            placement_bbox = None
            if results:
                all_x_min = [r["body_bbox"]["x_min"] for r in results if "body_bbox" in r]
                all_y_min = [r["body_bbox"]["y_min"] for r in results if "body_bbox" in r]
                all_x_max = [r["body_bbox"]["x_max"] for r in results if "body_bbox" in r]
                all_y_max = [r["body_bbox"]["y_max"] for r in results if "body_bbox" in r]
                if all_x_min:
                    placement_bbox = {
                        "x_min": min(all_x_min), "y_min": min(all_y_min),
                        "x_max": max(all_x_max), "y_max": max(all_y_max),
                    }

            return {
                "success": len(errors) == 0,
                "added": results,
                "errors": errors,
                "added_count": len(results),
                "error_count": len(errors),
                "placement_bbox": placement_bbox,
            }

        except Exception as e:
            logger.error(f"Error in batch_add_components: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_delete_schematic_component(self, params):
        """Remove a placed symbol from a schematic using text-based manipulation (no skip writes)"""
        logger.info("Deleting schematic component")
        try:
            from pathlib import Path
            import re

            schematic_path = params.get("schematicPath")
            reference = params.get("reference")

            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}
            if not reference:
                return {"success": False, "message": "reference is required"}

            sch_file = Path(schematic_path)
            if not sch_file.exists():
                return {
                    "success": False,
                    "message": f"Schematic not found: {schematic_path}",
                }

            with open(sch_file, "r", encoding="utf-8") as f:
                content = f.read()

            def find_matching_paren(s, start):
                """Find the closing paren matching the opening paren at start."""
                depth = 0
                i = start
                while i < len(s):
                    if s[i] == "(":
                        depth += 1
                    elif s[i] == ")":
                        depth -= 1
                        if depth == 0:
                            return i
                    i += 1
                return -1

            # Skip lib_symbols section
            lib_sym_pos = content.find("(lib_symbols")
            lib_sym_end = (
                find_matching_paren(content, lib_sym_pos) if lib_sym_pos >= 0 else -1
            )

            # Find ALL placed symbol blocks matching the reference (handles duplicates).
            # Use content-string search so multi-line KiCAD format is handled correctly:
            # KiCAD writes (symbol\n\t\t(lib_id "...") across two lines, which a
            # line-by-line regex would never match.
            blocks_to_delete = []  # list of (char_start, char_end) into content
            search_start = 0
            pattern = re.compile(r'\(symbol\s+\(lib_id\s+"')
            while True:
                m = pattern.search(content, search_start)
                if not m:
                    break
                pos = m.start()
                # Skip blocks inside lib_symbols
                if lib_sym_pos >= 0 and lib_sym_pos <= pos <= lib_sym_end:
                    search_start = lib_sym_end + 1
                    continue
                end = find_matching_paren(content, pos)
                if end < 0:
                    search_start = pos + 1
                    continue
                block_text = content[pos : end + 1]
                if re.search(
                    r'\(property\s+"Reference"\s+"' + re.escape(reference) + r'"',
                    block_text,
                ):
                    blocks_to_delete.append((pos, end))
                search_start = end + 1

            if not blocks_to_delete:
                return {
                    "success": False,
                    "message": f"Component '{reference}' not found in schematic (note: this tool removes schematic symbols, use delete_component for PCB footprints)",
                }

            # Delete from back to front to preserve character offsets
            for b_start, b_end in sorted(blocks_to_delete, reverse=True):
                # Include any leading newline/whitespace before the block
                trim_start = b_start
                while trim_start > 0 and content[trim_start - 1] in (" ", "\t"):
                    trim_start -= 1
                if trim_start > 0 and content[trim_start - 1] == "\n":
                    trim_start -= 1
                content = content[:trim_start] + content[b_end + 1:]

            with open(sch_file, "w", encoding="utf-8") as f:
                f.write(content)

            deleted_count = len(blocks_to_delete)
            logger.info(
                f"Deleted {deleted_count} instance(s) of {reference} from {sch_file.name}"
            )
            return {
                "success": True,
                "reference": reference,
                "deleted_count": deleted_count,
                "schematic": str(sch_file),
            }

        except Exception as e:
            logger.error(f"Error deleting schematic component: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_edit_schematic_component(self, params):
        """Update properties of a placed symbol in a schematic (footprint, value, reference).
        Uses text-based in-place editing – preserves position, UUID and all other fields.
        """
        logger.info("Editing schematic component")
        try:
            from pathlib import Path
            import re

            schematic_path = params.get("schematicPath")
            reference = params.get("reference")
            new_footprint = params.get("footprint")
            new_value = params.get("value")
            new_reference = params.get("newReference")
            field_positions = params.get(
                "fieldPositions"
            )  # dict: {"Reference": {"x": 1, "y": 2, "angle": 0}}

            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}
            if not reference:
                return {"success": False, "message": "reference is required"}
            if not any(
                [
                    new_footprint is not None,
                    new_value is not None,
                    new_reference is not None,
                    field_positions is not None,
                ]
            ):
                return {
                    "success": False,
                    "message": "At least one of footprint, value, newReference, or fieldPositions must be provided",
                }

            sch_file = Path(schematic_path)
            if not sch_file.exists():
                return {
                    "success": False,
                    "message": f"Schematic not found: {schematic_path}",
                }

            with open(sch_file, "r", encoding="utf-8") as f:
                content = f.read()

            def find_matching_paren(s, start):
                """Find the position of the closing paren matching the opening paren at start."""
                depth = 0
                i = start
                while i < len(s):
                    if s[i] == "(":
                        depth += 1
                    elif s[i] == ")":
                        depth -= 1
                        if depth == 0:
                            return i
                    i += 1
                return -1

            # Skip lib_symbols section
            lib_sym_pos = content.find("(lib_symbols")
            lib_sym_end = (
                find_matching_paren(content, lib_sym_pos) if lib_sym_pos >= 0 else -1
            )

            # Find placed symbol blocks that match the reference
            # Search for (symbol (lib_id "...") ... (property "Reference" "<ref>" ...) ...)
            block_start = block_end = None
            search_start = 0
            pattern = re.compile(r'\(symbol\s+\(lib_id\s+"')
            while True:
                m = pattern.search(content, search_start)
                if not m:
                    break
                pos = m.start()
                # Skip if inside lib_symbols section
                if lib_sym_pos >= 0 and lib_sym_pos <= pos <= lib_sym_end:
                    search_start = lib_sym_end + 1
                    continue
                end = find_matching_paren(content, pos)
                if end < 0:
                    search_start = pos + 1
                    continue
                block_text = content[pos : end + 1]
                if re.search(
                    r'\(property\s+"Reference"\s+"' + re.escape(reference) + r'"',
                    block_text,
                ):
                    block_start, block_end = pos, end
                    break
                search_start = end + 1

            if block_start is None:
                return {
                    "success": False,
                    "message": f"Component '{reference}' not found in schematic",
                }

            # Apply property replacements within the found block
            block_text = content[block_start : block_end + 1]
            if new_footprint is not None:
                block_text = re.sub(
                    r'(\(property\s+"Footprint"\s+)"[^"]*"',
                    rf'\1"{new_footprint}"',
                    block_text,
                )
            if new_value is not None:
                block_text = re.sub(
                    r'(\(property\s+"Value"\s+)"[^"]*"', rf'\1"{new_value}"', block_text
                )
            if new_reference is not None:
                block_text = re.sub(
                    r'(\(property\s+"Reference"\s+)"[^"]*"',
                    rf'\1"{new_reference}"',
                    block_text,
                )
                # Also update instances...reference so KiCad UI shows the new designator
                block_text = re.sub(
                    r'(\(reference\s+)"[^"]*"',
                    rf'\1"{new_reference}"',
                    block_text,
                )
            if field_positions is not None:
                for field_name, pos in field_positions.items():
                    x = pos.get("x", 0)
                    y = pos.get("y", 0)
                    angle = pos.get("angle", 0)
                    block_text = re.sub(
                        r'(\(property\s+"'
                        + re.escape(field_name)
                        + r'"\s+"[^"]*"\s+)\(at\s+[\d\.\-]+\s+[\d\.\-]+\s+[\d\.\-]+\s*\)',
                        rf"\1(at {x} {y} {angle})",
                        block_text,
                    )

            content = content[:block_start] + block_text + content[block_end + 1 :]

            with open(sch_file, "w", encoding="utf-8") as f:
                f.write(content)

            changes = {
                k: v
                for k, v in {
                    "footprint": new_footprint,
                    "value": new_value,
                    "reference": new_reference,
                }.items()
                if v is not None
            }
            if field_positions is not None:
                changes["fieldPositions"] = field_positions
            logger.info(f"Edited schematic component {reference}: {changes}")
            return {"success": True, "reference": reference, "updated": changes}

        except Exception as e:
            logger.error(f"Error editing schematic component: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_batch_edit_schematic_components(self, params):
        """Edit multiple components in a schematic in a single call.

        Accepts: {schematicPath, components: {ref: {footprint?, value?, newReference?, fieldPositions?}}}
        Applies each edit sequentially using _handle_edit_schematic_component.
        """
        logger.info("Batch editing schematic components")
        schematic_path = params.get("schematicPath")
        components = params.get("components")

        if not schematic_path:
            return {"success": False, "message": "schematicPath is required"}
        if not components or not isinstance(components, dict):
            return {"success": False, "message": "components must be a dict {reference: {footprint?, value?, newReference?}}"}

        updated = {}
        errors = []

        for reference, props in components.items():
            sub_params = {"schematicPath": schematic_path, "reference": reference, **props}
            result = self._handle_edit_schematic_component(sub_params)
            if result.get("success"):
                updated[reference] = result.get("updated", {})
            else:
                errors.append({"reference": reference, "error": result.get("message", "Unknown error")})

        return {
            "success": len(errors) == 0,
            "updated_count": len(updated),
            "error_count": len(errors),
            "updated": updated,
            "errors": errors,
        }

    def _handle_get_schematic_component(self, params):
        """Return full component info: position, all field values, properties, and pin→net assignments."""
        logger.info("Getting schematic component info")
        try:
            import re
            from pathlib import Path
            from commands.pin_locator import PinLocator
            from commands.connection_schematic import ConnectionManager as CM

            schematic_path = params.get("schematicPath")
            reference = params.get("reference")

            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}
            if not reference:
                return {"success": False, "message": "reference is required"}

            sch_file = Path(schematic_path)
            if not sch_file.exists():
                return {
                    "success": False,
                    "message": f"Schematic not found: {schematic_path}",
                }

            with open(sch_file, "r", encoding="utf-8") as f:
                content = f.read()

            # Use shared helper to find the placed symbol block
            block_text, block_start, block_end = KiCADInterface._find_placed_symbol_block(
                content, reference
            )

            if block_text is None:
                return {
                    "success": False,
                    "message": f"Component '{reference}' not found in schematic",
                }

            # Extract component position: first (at x y angle) in the symbol header line
            comp_at = re.search(
                r'\(symbol\s+\(lib_id\s+"[^"]*"\s*\)\s+\(at\s+([\d\.\-]+)\s+([\d\.\-]+)\s+([\d\.\-]+)\s*\)',
                block_text,
            )
            if comp_at:
                comp_pos = {
                    "x": float(comp_at.group(1)),
                    "y": float(comp_at.group(2)),
                    "angle": float(comp_at.group(3)),
                }
            else:
                comp_pos = None

            # Extract all properties with their at positions (for backward compat: keep fields)
            prop_pattern = re.compile(
                r'\(property\s+"([^"]*)"\s+"([^"]*)"\s+\(at\s+([\d\.\-]+)\s+([\d\.\-]+)\s+([\d\.\-]+)\s*\)'
            )
            fields = {}
            for m in prop_pattern.finditer(block_text):
                name, value, x, y, angle = (
                    m.group(1),
                    m.group(2),
                    m.group(3),
                    m.group(4),
                    m.group(5),
                )
                fields[name] = {
                    "value": value,
                    "x": float(x),
                    "y": float(y),
                    "angle": float(angle),
                }

            # All properties as flat name→value dict (excludes ki_* internal props)
            properties = KiCADInterface._extract_component_properties(block_text)

            # ── Pin→net assignments ───────────────────────────────────────────
            pins = []
            try:
                schematic = SchematicManager.load_schematic(schematic_path)
                netmap = CM.build_full_netmap(schematic, schematic_path)

                locator = PinLocator()

                # Get lib_id from block_text
                lib_id_m = re.search(r'\(lib_id\s+"([^"]+)"', block_text)
                lib_id = lib_id_m.group(1) if lib_id_m else None

                pins_def = locator.get_symbol_pins(sch_file, lib_id) if lib_id else {}
                all_pins = locator.get_all_symbol_pins(sch_file, reference)

                def _pin_sort_key(pn):
                    return int(pn) if pn.isdigit() else pn

                for pin_num in sorted(all_pins.keys(), key=_pin_sort_key):
                    pin_data = pins_def.get(str(pin_num), {})
                    net = netmap.get((reference, str(pin_num)), "unconnected")
                    coords = all_pins[pin_num]
                    pins.append({
                        "pinNumber": pin_num,
                        "pinName": pin_data.get("name", pin_num),
                        "pinType": pin_data.get("type", "unknown"),
                        "connectedNet": net,
                        "position": {"x": coords[0], "y": coords[1]},
                    })
            except Exception as pin_err:
                logger.warning(f"Could not build pin→net assignments: {pin_err}")

            return {
                "success": True,
                "reference": reference,
                "position": comp_pos,
                "fields": fields,
                "properties": properties,
                "pins": pins,
            }

        except Exception as e:
            logger.error(f"Error getting schematic component: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_add_schematic_wire(self, params):
        """Add a wire to a schematic using WireManager"""
        logger.info("Adding wire to schematic")
        try:
            from pathlib import Path
            from commands.wire_manager import WireManager

            schematic_path = params.get("schematicPath")
            start_point = params.get("startPoint")
            end_point = params.get("endPoint")
            properties = params.get("properties", {})

            if not schematic_path:
                return {"success": False, "message": "Schematic path is required"}
            if not start_point or not end_point:
                return {
                    "success": False,
                    "message": "Start and end points are required",
                }

            # Extract wire properties
            stroke_width = properties.get("stroke_width", 0)
            stroke_type = properties.get("stroke_type", "default")

            # Use WireManager for S-expression manipulation
            success = WireManager.add_wire(
                Path(schematic_path),
                start_point,
                end_point,
                stroke_width=stroke_width,
                stroke_type=stroke_type,
            )

            if success:
                return {"success": True, "message": "Wire added successfully"}
            else:
                return {"success": False, "message": "Failed to add wire"}
        except Exception as e:
            logger.error(f"Error adding wire to schematic: {str(e)}")
            import traceback

            logger.error(traceback.format_exc())
            return {
                "success": False,
                "message": str(e),
                "errorDetails": traceback.format_exc(),
            }

    def _handle_list_schematic_libraries(self, params):
        """List available symbol libraries"""
        logger.info("Listing schematic libraries")
        try:
            search_paths = params.get("searchPaths")

            libraries = LibraryManager.list_available_libraries(search_paths)
            return {"success": True, "libraries": libraries}
        except Exception as e:
            logger.error(f"Error listing schematic libraries: {str(e)}")
            return {"success": False, "message": str(e)}

    # ------------------------------------------------------------------ #
    #  Footprint handlers                                                  #
    # ------------------------------------------------------------------ #

    def _handle_create_footprint(self, params):
        """Create a new .kicad_mod footprint file in a .pretty library."""
        logger.info(
            f"create_footprint: {params.get('name')} in {params.get('libraryPath')}"
        )
        try:
            creator = FootprintCreator()
            return creator.create_footprint(
                library_path=params.get("libraryPath", ""),
                name=params.get("name", ""),
                description=params.get("description", ""),
                tags=params.get("tags", ""),
                pads=params.get("pads", []),
                courtyard=params.get("courtyard"),
                silkscreen=params.get("silkscreen"),
                fab_layer=params.get("fabLayer"),
                ref_position=params.get("refPosition"),
                value_position=params.get("valuePosition"),
                overwrite=params.get("overwrite", False),
            )
        except Exception as e:
            logger.error(f"create_footprint error: {e}")
            return {"success": False, "error": str(e)}

    def _handle_edit_footprint_pad(self, params):
        """Edit an existing pad in a .kicad_mod file."""
        logger.info(
            f"edit_footprint_pad: pad {params.get('padNumber')} in {params.get('footprintPath')}"
        )
        try:
            creator = FootprintCreator()
            return creator.edit_footprint_pad(
                footprint_path=params.get("footprintPath", ""),
                pad_number=str(params.get("padNumber", "1")),
                size=params.get("size"),
                at=params.get("at"),
                drill=params.get("drill"),
                shape=params.get("shape"),
            )
        except Exception as e:
            logger.error(f"edit_footprint_pad error: {e}")
            return {"success": False, "error": str(e)}

    def _handle_list_footprint_libraries(self, params):
        """List .pretty footprint libraries and their contents."""
        logger.info("list_footprint_libraries")
        try:
            creator = FootprintCreator()
            return creator.list_footprint_libraries(
                search_paths=params.get("searchPaths")
            )
        except Exception as e:
            logger.error(f"list_footprint_libraries error: {e}")
            return {"success": False, "error": str(e)}

    def _handle_register_footprint_library(self, params):
        """Register a .pretty library in KiCAD's fp-lib-table."""
        logger.info(f"register_footprint_library: {params.get('libraryPath')}")
        try:
            creator = FootprintCreator()
            return creator.register_footprint_library(
                library_path=params.get("libraryPath", ""),
                library_name=params.get("libraryName"),
                description=params.get("description", ""),
                scope=params.get("scope", "project"),
                project_path=params.get("projectPath"),
            )
        except Exception as e:
            logger.error(f"register_footprint_library error: {e}")
            return {"success": False, "error": str(e)}

    # ------------------------------------------------------------------ #
    #  Symbol creator handlers                                             #
    # ------------------------------------------------------------------ #

    def _handle_create_symbol(self, params):
        """Create a new symbol in a .kicad_sym library."""
        logger.info(
            f"create_symbol: {params.get('name')} in {params.get('libraryPath')}"
        )
        try:
            creator = SymbolCreator()
            return creator.create_symbol(
                library_path=params.get("libraryPath", ""),
                name=params.get("name", ""),
                reference_prefix=params.get("referencePrefix", "U"),
                description=params.get("description", ""),
                keywords=params.get("keywords", ""),
                datasheet=params.get("datasheet", "~"),
                footprint=params.get("footprint", ""),
                in_bom=params.get("inBom", True),
                on_board=params.get("onBoard", True),
                pins=params.get("pins", []),
                rectangles=params.get("rectangles", []),
                polylines=params.get("polylines", []),
                overwrite=params.get("overwrite", False),
            )
        except Exception as e:
            logger.error(f"create_symbol error: {e}")
            return {"success": False, "error": str(e)}

    def _handle_delete_symbol(self, params):
        """Delete a symbol from a .kicad_sym library."""
        logger.info(
            f"delete_symbol: {params.get('name')} from {params.get('libraryPath')}"
        )
        try:
            creator = SymbolCreator()
            return creator.delete_symbol(
                library_path=params.get("libraryPath", ""),
                name=params.get("name", ""),
            )
        except Exception as e:
            logger.error(f"delete_symbol error: {e}")
            return {"success": False, "error": str(e)}

    def _handle_list_symbols_in_library(self, params):
        """List all symbols in a .kicad_sym file."""
        logger.info(f"list_symbols_in_library: {params.get('libraryPath')}")
        try:
            creator = SymbolCreator()
            return creator.list_symbols(
                library_path=params.get("libraryPath", ""),
            )
        except Exception as e:
            logger.error(f"list_symbols_in_library error: {e}")
            return {"success": False, "error": str(e)}

    def _handle_register_symbol_library(self, params):
        """Register a .kicad_sym library in KiCAD's sym-lib-table."""
        logger.info(f"register_symbol_library: {params.get('libraryPath')}")
        try:
            creator = SymbolCreator()
            return creator.register_symbol_library(
                library_path=params.get("libraryPath", ""),
                library_name=params.get("libraryName"),
                description=params.get("description", ""),
                scope=params.get("scope", "project"),
                project_path=params.get("projectPath"),
            )
        except Exception as e:
            logger.error(f"register_symbol_library error: {e}")
            return {"success": False, "error": str(e)}

    def _handle_export_schematic_pdf(self, params):
        """Export schematic to PDF"""
        logger.info("Exporting schematic to PDF")
        try:
            schematic_path = params.get("schematicPath")
            output_path = params.get("outputPath")

            if not schematic_path:
                return {"success": False, "message": "Schematic path is required"}
            if not output_path:
                return {"success": False, "message": "Output path is required"}

            if not os.path.exists(schematic_path):
                return {
                    "success": False,
                    "message": f"Schematic not found: {schematic_path}",
                }

            import subprocess

            cmd = [
                "kicad-cli",
                "sch",
                "export",
                "pdf",
                "--output",
                output_path,
                schematic_path,
            ]

            if params.get("blackAndWhite"):
                cmd.insert(-1, "--black-and-white")

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

            if result.returncode == 0:
                return {"success": True, "file": {"path": output_path}}
            else:
                return {
                    "success": False,
                    "message": f"kicad-cli failed: {result.stderr}",
                }

        except FileNotFoundError:
            return {"success": False, "message": "kicad-cli not found in PATH"}
        except Exception as e:
            logger.error(f"Error exporting schematic to PDF: {str(e)}")
            return {"success": False, "message": str(e)}

    def _handle_add_schematic_connection(self, params):
        """Add a pin-to-pin connection in schematic with automatic pin discovery and routing"""
        logger.info("Adding pin-to-pin connection in schematic")
        try:
            from pathlib import Path

            schematic_path = params.get("schematicPath")
            source_ref = params.get("sourceRef")
            source_pin = params.get("sourcePin")
            target_ref = params.get("targetRef")
            target_pin = params.get("targetPin")
            routing = params.get(
                "routing", "direct"
            )  # 'direct', 'orthogonal_h', 'orthogonal_v'

            if not all(
                [schematic_path, source_ref, source_pin, target_ref, target_pin]
            ):
                return {"success": False, "message": "Missing required parameters"}

            # Use ConnectionManager with new PinLocator and WireManager integration
            success = ConnectionManager.add_connection(
                Path(schematic_path),
                source_ref,
                source_pin,
                target_ref,
                target_pin,
                routing=routing,
            )

            if success:
                return {
                    "success": True,
                    "message": f"Connected {source_ref}/{source_pin} to {target_ref}/{target_pin} (routing: {routing})",
                }
            else:
                return {"success": False, "message": "Failed to add connection"}
        except Exception as e:
            logger.error(f"Error adding schematic connection: {str(e)}")
            import traceback

            logger.error(traceback.format_exc())
            return {
                "success": False,
                "message": str(e),
                "errorDetails": traceback.format_exc(),
            }

    def _handle_add_schematic_net_label(self, params):
        """Add a net label to schematic using WireManager"""
        logger.info("Adding net label to schematic")
        try:
            from pathlib import Path
            from commands.wire_manager import WireManager

            schematic_path = params.get("schematicPath")
            net_name = params.get("netName")
            position = params.get("position")
            label_type = params.get(
                "labelType", "label"
            )  # 'label', 'global_label', 'hierarchical_label'
            # Support both 'angle' (new) and 'orientation' (legacy) parameter names
            orientation = params.get("angle", params.get("orientation", 0))  # 0, 90, 180, 270
            # justify=None means auto-derive from angle in WireManager
            justify = params.get("justify", None)

            if not all([schematic_path, net_name, position]):
                return {"success": False, "message": "Missing required parameters"}

            # Use WireManager for S-expression manipulation
            success = WireManager.add_label(
                Path(schematic_path),
                net_name,
                position,
                label_type=label_type,
                orientation=orientation,
                justify=justify,
            )

            if success:
                return {
                    "success": True,
                    "message": f"Added net label '{net_name}' at {position}",
                }
            else:
                return {"success": False, "message": "Failed to add net label"}
        except Exception as e:
            logger.error(f"Error adding net label: {str(e)}")
            import traceback

            logger.error(traceback.format_exc())
            return {
                "success": False,
                "message": str(e),
                "errorDetails": traceback.format_exc(),
            }

    def _handle_set_schematic_property_position(self, params):
        """Move a symbol's Reference or Value property field to a new coordinate."""
        import re
        logger.info("Setting schematic property position")
        try:
            from pathlib import Path

            schematic_path = params.get("schematicPath")
            reference = params.get("reference")
            property_name = params.get("property")
            x = params.get("x")
            y = params.get("y")
            angle = params.get("angle", 0)
            visible = params.get("visible", True)

            if not all([schematic_path, reference, property_name, x is not None, y is not None]):
                return {"success": False, "message": "Missing required parameters: schematicPath, reference, property, x, y"}
            if property_name not in ("Reference", "Value"):
                return {"success": False, "message": "property must be 'Reference' or 'Value'"}

            sch_path = Path(schematic_path)
            if not sch_path.exists():
                return {"success": False, "message": f"Schematic not found: {schematic_path}"}

            with open(sch_path, "r", encoding="utf-8") as f:
                content = f.read()

            block_text, block_start, block_end = KiCADInterface._find_placed_symbol_block(content, reference)
            if block_text is None:
                return {"success": False, "message": f"Component '{reference}' not found in schematic"}

            # Record old position for reporting
            old_pos = KiCADInterface._extract_property_position(block_text, property_name)

            # Replace (at X Y ANGLE) inside the target property
            prop_pat = re.compile(
                r'(\(property\s+"' + re.escape(property_name) + r'"\s+"[^"]*"\s+)\(at\s+[-\d.]+\s+[-\d.]+\s+[-\d.]+\)'
            )
            new_at = f"(at {x} {y} {angle})"
            new_block, n_subs = prop_pat.subn(r'\g<1>' + new_at, block_text)
            if n_subs == 0:
                return {"success": False, "message": f"Property '{property_name}' not found in {reference}"}

            # Handle visibility: find property sub-expression and add/remove (hide yes)
            prop_sub_m = re.search(r'\(property\s+"' + re.escape(property_name) + r'"', new_block)
            if prop_sub_m:
                ps = prop_sub_m.start()
                depth = 0
                i = ps
                while i < len(new_block):
                    if new_block[i] == '(':
                        depth += 1
                    elif new_block[i] == ')':
                        depth -= 1
                        if depth == 0:
                            pe = i
                            break
                    i += 1
                prop_sub = new_block[ps:pe + 1]
                is_hidden = '(hide yes)' in prop_sub or '(hide)' in prop_sub
                if not visible and not is_hidden:
                    # Find (effects ...) and insert (hide yes) before its closing paren
                    eff_m = re.search(r'\(effects', prop_sub)
                    if eff_m:
                        eff_start = eff_m.start()
                        edepth = 0
                        ei = eff_start
                        while ei < len(prop_sub):
                            if prop_sub[ei] == '(':
                                edepth += 1
                            elif prop_sub[ei] == ')':
                                edepth -= 1
                                if edepth == 0:
                                    eff_end = ei
                                    break
                            ei += 1
                        new_eff = prop_sub[eff_start:eff_end] + " (hide yes))"
                        prop_sub = prop_sub[:eff_start] + new_eff + prop_sub[eff_end + 1:]
                elif visible and is_hidden:
                    prop_sub = prop_sub.replace(' (hide yes)', '').replace('(hide yes) ', '').replace('(hide yes)', '')
                    prop_sub = prop_sub.replace(' (hide)', '').replace('(hide) ', '').replace('(hide)', '')
                new_block = new_block[:ps] + prop_sub + new_block[pe + 1:]

            new_content = content[:block_start] + new_block + content[block_end + 1:]
            with open(sch_path, "w", encoding="utf-8") as f:
                f.write(new_content)

            old_str = f"({old_pos['x']}, {old_pos['y']}, {old_pos['angle']}°)" if old_pos else "unknown"
            return {
                "success": True,
                "message": f"Moved {reference}.{property_name} from {old_str} to ({x}, {y}, {angle}°)",
            }
        except Exception as e:
            logger.error(f"Error setting property position: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_batch_set_schematic_property_positions(self, params):
        """Batch-move Reference/Value property fields for multiple components in one file read/write."""
        import re
        logger.info("Batch setting schematic property positions")
        try:
            from pathlib import Path

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
            applied = []
            failed = []

            for upd in updates:
                reference = upd.get("reference")
                property_name = upd.get("property")
                x = upd.get("x")
                y = upd.get("y")
                angle = upd.get("angle", 0)
                visible = upd.get("visible", True)

                if not reference or not property_name or x is None or y is None:
                    failed.append({"reference": reference, "property": property_name,
                                   "reason": "Missing required fields: reference, property, x, y"})
                    continue
                if property_name not in ("Reference", "Value"):
                    failed.append({"reference": reference, "property": property_name,
                                   "reason": "property must be 'Reference' or 'Value'"})
                    continue

                block_text, block_start, block_end = KiCADInterface._find_placed_symbol_block(content, reference)
                if block_text is None:
                    failed.append({"reference": reference, "property": property_name,
                                   "reason": f"Component '{reference}' not found in schematic"})
                    continue

                prop_pat = re.compile(
                    r'(\(property\s+"' + re.escape(property_name) + r'"\s+"[^"]*"\s+)'
                    r'\(at\s+[-\d.]+\s+[-\d.]+\s+[-\d.]+\)'
                )
                new_block, n_subs = prop_pat.subn(r'\g<1>' + f"(at {x} {y} {angle})", block_text)
                if n_subs == 0:
                    failed.append({"reference": reference, "property": property_name,
                                   "reason": f"Property '{property_name}' not found in {reference} block"})
                    continue

                # Handle visibility
                prop_sub_m = re.search(r'\(property\s+"' + re.escape(property_name) + r'"', new_block)
                if prop_sub_m:
                    ps = prop_sub_m.start()
                    depth, i, pe = 0, ps, len(new_block) - 1
                    while i < len(new_block):
                        if new_block[i] == '(':
                            depth += 1
                        elif new_block[i] == ')':
                            depth -= 1
                            if depth == 0:
                                pe = i
                                break
                        i += 1
                    prop_sub = new_block[ps:pe + 1]
                    is_hidden = '(hide yes)' in prop_sub or '(hide)' in prop_sub
                    if not visible and not is_hidden:
                        eff_m = re.search(r'\(effects', prop_sub)
                        if eff_m:
                            eff_start = eff_m.start()
                            edepth, ei, eff_end = 0, eff_start, len(prop_sub) - 1
                            while ei < len(prop_sub):
                                if prop_sub[ei] == '(':
                                    edepth += 1
                                elif prop_sub[ei] == ')':
                                    edepth -= 1
                                    if edepth == 0:
                                        eff_end = ei
                                        break
                                ei += 1
                            new_eff = prop_sub[eff_start:eff_end] + " (hide yes))"
                            prop_sub = prop_sub[:eff_start] + new_eff + prop_sub[eff_end + 1:]
                    elif visible and is_hidden:
                        prop_sub = prop_sub.replace(' (hide yes)', '').replace('(hide yes) ', '').replace('(hide yes)', '')
                        prop_sub = prop_sub.replace(' (hide)', '').replace('(hide) ', '').replace('(hide)', '')
                    new_block = new_block[:ps] + prop_sub + new_block[pe + 1:]

                content = content[:block_start] + new_block + content[block_end + 1:]
                applied.append({"reference": reference, "property": property_name,
                                 "x": x, "y": y, "angle": angle, "visible": visible})

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

    def _handle_add_no_connect(self, params):
        """Add a no-connect flag to mark an intentionally unconnected pin"""
        logger.info("Adding no-connect flag to schematic")
        try:
            from pathlib import Path
            from commands.wire_manager import WireManager

            schematic_path = params.get("schematicPath")
            position = params.get("position")
            component_ref = params.get("componentRef")
            pin_name = params.get("pinName")

            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}

            # If componentRef+pinName provided, auto-resolve position via PinLocator
            if component_ref and pin_name and not position:
                try:
                    from commands.pin_locator import PinLocator
                    locator = PinLocator()
                    pin_loc = locator.get_pin_location(Path(schematic_path), component_ref, str(pin_name))
                    if not pin_loc:
                        return {
                            "success": False,
                            "message": f"Could not find pin {pin_name} on {component_ref}",
                        }
                    position = pin_loc
                except Exception as e:
                    return {"success": False, "message": f"Pin lookup failed: {e}"}

            if not position:
                return {"success": False, "message": "Provide either 'position' [x, y] or 'componentRef' + 'pinName'"}

            success = WireManager.add_no_connect(Path(schematic_path), position)

            if success:
                pin_desc = f"{component_ref}/{pin_name}" if component_ref else f"({position[0]}, {position[1]})"
                return {
                    "success": True,
                    "message": f"Added no-connect marker for {pin_desc}",
                    "position": {"x": position[0], "y": position[1]},
                }
            else:
                return {"success": False, "message": "Failed to add no-connect flag"}
        except Exception as e:
            logger.error(f"Error adding no-connect: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return {
                "success": False,
                "message": str(e),
                "errorDetails": traceback.format_exc(),
            }

    def _handle_batch_add_no_connects(self, params):
        """Add no-connect flags to multiple pins in a single call."""
        logger.info("Batch adding no-connect flags")
        try:
            from pathlib import Path
            from commands.wire_manager import WireManager
            from commands.pin_locator import PinLocator

            schematic_path = params.get("schematicPath")
            pins = params.get("pins", [])

            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}
            if not pins:
                return {"success": False, "message": "pins list is required and must be non-empty"}

            sch_path = Path(schematic_path)
            locator = PinLocator()
            placed = []
            failed = []

            for entry in pins:
                comp_ref = entry.get("componentRef")
                pin_name = entry.get("pinName")
                if not comp_ref or pin_name is None:
                    failed.append({"entry": entry, "reason": "componentRef and pinName are required"})
                    continue
                try:
                    pin_loc = locator.get_pin_location(sch_path, comp_ref, str(pin_name))
                    if not pin_loc:
                        # Single-pin fallback
                        all_pins = locator.get_all_symbol_pins(sch_path, comp_ref) or {}
                        if len(all_pins) == 1:
                            coords = next(iter(all_pins.values()))
                            pin_loc = coords
                        else:
                            avail = sorted(all_pins.keys()) if all_pins else []
                            failed.append({"componentRef": comp_ref, "pinName": str(pin_name),
                                           "reason": f"Pin not found; available: {avail}"})
                            continue
                    ok = WireManager.add_no_connect(sch_path, pin_loc)
                    if ok:
                        placed.append({
                            "componentRef": comp_ref,
                            "pinName": str(pin_name),
                            "position": {"x": pin_loc[0], "y": pin_loc[1]},
                        })
                    else:
                        failed.append({"componentRef": comp_ref, "pinName": str(pin_name),
                                       "reason": "add_no_connect returned False"})
                except Exception as pin_err:
                    failed.append({"componentRef": comp_ref, "pinName": str(pin_name),
                                   "reason": str(pin_err)})

            return {
                "success": len(failed) == 0,
                "message": f"Placed {len(placed)} no-connect marker(s), {len(failed)} failed",
                "placed": placed,
                "failed": failed,
            }
        except Exception as e:
            logger.error(f"Error in batch_add_no_connects: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_save_schematic(self, params):
        """Save schematic - confirms the schematic file exists (schematic changes are written immediately by each tool)"""
        logger.info("Save schematic requested")
        try:
            schematic_path = params.get("schematicPath")
            if not schematic_path:
                return {"success": False, "message": "Missing required parameter: schematicPath"}

            import os
            if not os.path.exists(schematic_path):
                return {"success": False, "message": f"Schematic file not found: {schematic_path}"}

            # Schematic tools write changes directly to disk (no in-memory state)
            # This tool confirms the file is present and returns its size as proof
            size = os.path.getsize(schematic_path)
            return {
                "success": True,
                "message": f"Schematic is saved at {schematic_path}",
                "file_path": schematic_path,
                "file_size_bytes": size,
                "note": "Schematic tools write changes directly to disk. No separate save step is required."
            }
        except Exception as e:
            logger.error(f"Error in save_schematic: {str(e)}")
            return {"success": False, "message": str(e)}

    def _handle_connect_to_net(self, params):
        """Connect a component pin to a named net using wire stub and label"""
        logger.info("Connecting component pin to net")
        try:
            from pathlib import Path

            schematic_path = params.get("schematicPath")
            component_ref = params.get("reference") or params.get("componentRef")
            pin_name = params.get("pinNumber") or params.get("pinName")
            net_name = params.get("netName")

            if not all([schematic_path, component_ref, pin_name, net_name]):
                return {"success": False, "message": "Missing required parameters: schematicPath, reference, pinNumber, netName"}

            # Use ConnectionManager with new WireManager integration
            label_pos = ConnectionManager.connect_to_net(
                Path(schematic_path), component_ref, pin_name, net_name
            )

            if label_pos is not None:
                return {
                    "success": True,
                    "message": f"Connected {component_ref}/{pin_name} to net '{net_name}'",
                    "label_position": label_pos,
                }
            else:
                return {"success": False, "message": "Failed to connect to net"}
        except Exception as e:
            logger.error(f"Error connecting to net: {str(e)}")
            import traceback

            logger.error(traceback.format_exc())
            return {
                "success": False,
                "message": str(e),
                "errorDetails": traceback.format_exc(),
            }

    def _handle_connect_passthrough(self, params):
        """Connect all pins of source connector to matching pins of target connector"""
        logger.info("Connecting passthrough between two connectors")
        try:
            from pathlib import Path

            schematic_path = params.get("schematicPath")
            source_ref = params.get("sourceRef")
            target_ref = params.get("targetRef")
            net_prefix = params.get("netPrefix", "PIN")
            pin_offset = int(params.get("pinOffset", 0))

            if not all([schematic_path, source_ref, target_ref]):
                return {
                    "success": False,
                    "message": "Missing required parameters: schematicPath, sourceRef, targetRef",
                }

            result = ConnectionManager.connect_passthrough(
                Path(schematic_path), source_ref, target_ref, net_prefix, pin_offset
            )

            n_ok = len(result["connected"])
            n_fail = len(result["failed"])
            return {
                "success": n_fail == 0,
                "message": f"Passthrough complete: {n_ok} connected, {n_fail} failed",
                "connected": result["connected"],
                "failed": result["failed"],
            }
        except Exception as e:
            logger.error(f"Error in connect_passthrough: {str(e)}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    @staticmethod
    def _find_facing_label(sch_path, net_name: str, position, orientation: int, proximity_mm: float = 14.0):
        """
        Scan the schematic for an existing label with *net_name* that:
          - is within *proximity_mm* of *position*
          - has an orientation 180° opposite to *orientation* (i.e. the two labels face each other)

        Returns [lx, ly] of the existing label if found, else None.
        Used to detect when two components on the same net have adjacent facing pins —
        in that case, a single wire between them is cleaner than two overlapping labels.
        """
        import re as _re
        import math as _math
        try:
            content = sch_path.read_text(encoding="utf-8")
            pat = _re.compile(r'\(label\s+"([^"]+)"\s+\(at\s+([-\d.]+)\s+([-\d.]+)\s+([\d.]+)\)')
            px, py = float(position[0]), float(position[1])
            orient_norm = int(round(orientation)) % 360
            facing = (orient_norm + 180) % 360
            for m in pat.finditer(content):
                lname = m.group(1)
                if lname != net_name:
                    continue
                lx, ly, la = float(m.group(2)), float(m.group(3)), float(m.group(4))
                if _math.hypot(lx - px, ly - py) > proximity_mm:
                    continue
                if int(round(la)) % 360 == facing:
                    return [lx, ly]
        except Exception:
            pass
        return None

    def _handle_place_net_label_at_pin(self, params):
        """Place a net label at the exact endpoint of a component pin (no wire stub)"""
        logger.info("Placing net label at pin")
        try:
            from pathlib import Path
            from commands.pin_locator import PinLocator
            from commands.wire_manager import WireManager

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
                # For single-pin components (PWR_FLAG, GND, +3V3, etc.) the pin name
                # is often non-obvious (e.g. "~" for PWR_FLAG).  Fall back to whichever
                # pin exists when the component has exactly one pin.
                all_pins = locator.get_all_symbol_pins(sch_path, reference) or {}
                if len(all_pins) == 1:
                    only_pin_num = next(iter(all_pins))
                    coords = all_pins[only_pin_num]
                    position = coords
                    pin_number = only_pin_num
                    logger.info(
                        f"Single-pin fallback: {reference} has one pin ({only_pin_num}), using it"
                    )
                else:
                    return {
                        "success": False,
                        "message": f"Could not find pin '{pin_number}' on {reference}. "
                                   f"Available pins: {sorted(all_pins.keys()) if all_pins else 'none found'}",
                    }

            raw_angle = locator.get_pin_angle(sch_path, reference, str(pin_number)) or 0
            # Normalize to nearest cardinal angle
            cardinal = round(raw_angle / 90) * 90 % 360
            # Map pin angle to label orientation: label text should extend outward
            angle_map = {0: 180, 90: 270, 180: 0, 270: 90}
            orientation = angle_map.get(cardinal, 0)

            # If an existing label with the same net name is nearby and facing this one,
            # add a wire to it instead of placing a duplicate — prevents overlapping labels
            # between adjacent components on the same net (e.g. D1-VBUS ↔ F1-VBUS).
            existing_pos = KiCADInterface._find_facing_label(sch_path, net_name, position, orientation)
            if existing_pos:
                wire_ok = WireManager.add_wire(sch_path, list(position), existing_pos)
                return {
                    "success": wire_ok,
                    "reference": reference,
                    "pinNumber": pin_number,
                    "netName": net_name,
                    "position": {"x": position[0], "y": position[1]},
                    "labelOrientation": orientation,
                    "note": f"Wired to existing '{net_name}' label at ({existing_pos[0]},{existing_pos[1]}) instead of placing duplicate",
                }

            success = WireManager.add_label(
                sch_path, net_name, position, label_type="label", orientation=orientation
            )

            if success:
                return {
                    "success": True,
                    "reference": reference,
                    "pinNumber": pin_number,
                    "netName": net_name,
                    "position": {"x": position[0], "y": position[1]},
                    "labelOrientation": orientation,
                }
            else:
                return {"success": False, "message": "Failed to place net label"}

        except Exception as e:
            logger.error(f"Error placing net label at pin: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e), "errorDetails": traceback.format_exc()}

    def _handle_batch_connect(self, params):
        """Place net labels on multiple pins in a single call to avoid per-pin round-trips."""
        logger.info("Batch connect: placing net labels on multiple pins")
        try:
            from pathlib import Path
            from commands.pin_locator import PinLocator
            from commands.wire_manager import WireManager

            schematic_path = params.get("schematicPath")
            connections = params.get("connections")  # {ref: {pin: netName}}
            replace = bool(params.get("replace", False))

            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}
            if not connections or not isinstance(connections, dict):
                return {"success": False, "message": "connections must be a dict {ref: {pin: netName}}"}

            locator = PinLocator()
            sch_path = Path(schematic_path)

            # Eagerly verify the schematic is parseable before the pin loop.
            # If skip fails here, ALL pins will silently return "not found" — which is
            # misleading.  A clear parse error is more actionable.
            try:
                from skip import Schematic as _Sch
                _Sch(str(sch_path))
            except Exception as parse_err:
                return {
                    "success": False,
                    "message": (
                        f"ERROR: Failed to load schematic at {schematic_path}: {parse_err}. "
                        "All pin operations aborted. Run validate_schematic to check for "
                        "syntax errors (parenthesis balance) in the file."
                    ),
                }

            placed = []
            failed = []
            # Track already-placed label positions to deduplicate pins that share
            # the same schematic coordinate (e.g. USB-C dual-role pins like A4B9/B4A9).
            # Key: (rounded_x, rounded_y), Value: net_name already placed there.
            placed_positions: dict = {}

            for ref, pin_map in connections.items():
                if not isinstance(pin_map, dict):
                    failed.append({"ref": ref, "reason": "pin_map must be a dict {pin: netName}"})
                    continue
                for pin_id, net_name in pin_map.items():
                    try:
                        resolved_pin = str(pin_id)
                        position = locator.get_pin_location(sch_path, ref, resolved_pin)
                        if not position:
                            # Single-pin fallback for PWR_FLAG, GND, +3V3, etc.
                            all_pins = locator.get_all_symbol_pins(sch_path, ref) or {}
                            if len(all_pins) == 1:
                                resolved_pin = next(iter(all_pins))
                                coords = all_pins[resolved_pin]
                                position = coords
                                logger.info(
                                    f"batch_connect single-pin fallback: {ref} pin {resolved_pin}"
                                )
                            else:
                                avail = sorted(all_pins.keys()) if all_pins else []
                                failed.append({
                                    "ref": ref,
                                    "pin": resolved_pin,
                                    "reason": f"pin not found; available: {avail}",
                                })
                                continue

                        # Deduplicate: if two pins of the same component (or different
                        # components) resolve to the exact same coordinate for the same
                        # net, skip placing a second label there.
                        pos_key = (round(float(position[0]), 2), round(float(position[1]), 2))
                        if pos_key in placed_positions and placed_positions[pos_key] == net_name:
                            placed.append({
                                "ref": ref,
                                "pin": str(pin_id),
                                "net": net_name,
                                "position": {"x": position[0], "y": position[1]},
                                "note": "deduped: label already placed at this coordinate for this net",
                            })
                            continue

                        raw_angle = locator.get_pin_angle(sch_path, ref, resolved_pin) or 0
                        cardinal = round(raw_angle / 90) * 90 % 360
                        angle_map = {0: 180, 90: 270, 180: 0, 270: 90}
                        orientation = angle_map.get(cardinal, 0)

                        # If a facing label with the same net name is nearby, wire to it
                        # rather than placing a duplicate — avoids overlapping labels between
                        # adjacent components on the same net (e.g. bus segments).
                        existing_pos = KiCADInterface._find_facing_label(
                            sch_path, net_name, position, orientation
                        )
                        if existing_pos:
                            ok = WireManager.add_wire(sch_path, list(position), existing_pos)
                            if ok:
                                placed.append({
                                    "ref": ref,
                                    "pin": str(pin_id),
                                    "net": net_name,
                                    "position": {"x": position[0], "y": position[1]},
                                    "note": f"wired to existing label at ({existing_pos[0]},{existing_pos[1]})",
                                })
                                placed_positions[pos_key] = net_name
                            else:
                                failed.append({"ref": ref, "pin": str(pin_id), "net": net_name, "reason": "wire-to-existing-label failed"})
                            continue

                        # replace=True: delete any existing label at this pin tip
                        # before placing the new one, so wrong-net labels are cleared.
                        if replace:
                            WireManager.delete_label(sch_path, net_name, list(position), tolerance=0.5)
                            # Also delete any label with a different net at the same position
                            try:
                                import sexpdata as _sd
                                from sexpdata import Symbol as _Sym
                                with open(sch_path, "r", encoding="utf-8") as _rf:
                                    _rd = _sd.loads(_rf.read())
                                changed = False
                                new_rd = []
                                for _item in _rd:
                                    if (isinstance(_item, list) and len(_item) > 0
                                            and _item[0] == _Sym("label")):
                                        _at = next(
                                            (p for p in _item[1:] if isinstance(p, list)
                                             and len(p) >= 3 and p[0] == _Sym("at")),
                                            None,
                                        )
                                        if _at:
                                            _lx, _ly = float(_at[1]), float(_at[2])
                                            if abs(_lx - position[0]) < 0.5 and abs(_ly - position[1]) < 0.5:
                                                changed = True
                                                continue  # drop this label
                                    new_rd.append(_item)
                                if changed:
                                    with open(sch_path, "w", encoding="utf-8") as _wf:
                                        _wf.write(_sd.dumps(new_rd))
                            except Exception as _re:
                                logger.warning(f"replace cleanup failed: {_re}")

                        ok = WireManager.add_label(
                            sch_path, net_name, position, label_type="label", orientation=orientation
                        )
                        if ok:
                            placed.append({
                                "ref": ref,
                                "pin": str(pin_id),
                                "net": net_name,
                                "position": {"x": position[0], "y": position[1]},
                            })
                            placed_positions[pos_key] = net_name
                        else:
                            failed.append({"ref": ref, "pin": str(pin_id), "net": net_name, "reason": "add_label failed"})
                    except Exception as pin_err:
                        failed.append({"ref": ref, "pin": str(pin_id), "reason": str(pin_err)})

            # PWR_FLAG gap detection: warn for power nets that have no PWR_FLAG
            power_nets_without_pwr_flag = []
            try:
                _POWER_KEYWORDS = {"VCC", "VDD", "VIN", "VBUS", "VBAT", "GND", "AGND", "DGND",
                                   "PGND", "+5V", "+3V3", "+12V", "+3.3V", "+5.0V", "PWR", "POWER", "AVCC"}
                _placed_nets = {p["net"] for p in placed}
                _power_nets = {n for n in _placed_nets
                               if any(kw in n.upper() for kw in _POWER_KEYWORDS)}
                if _power_nets:
                    _pwr_flag_nets = set()
                    try:
                        from skip import Schematic as _Sch
                        _sch_obj = _Sch(str(sch_path))
                        _pwr_flag_refs = [
                            sym.property.Reference.value
                            for sym in getattr(_sch_obj, "symbol", [])
                            if "PWR_FLAG" in (sym.lib_id.value if hasattr(sym, "lib_id") else "")
                            and hasattr(sym.property, "Reference")
                        ]
                        if _pwr_flag_refs:
                            _TOL = 0.5
                            for _pref in _pwr_flag_refs:
                                _ppin = locator.get_pin_location(sch_path, _pref, "1")
                                if not _ppin:
                                    _all = locator.get_all_symbol_pins(sch_path, _pref) or {}
                                    if _all:
                                        _ppin = next(iter(_all.values()))
                                if _ppin:
                                    for _pl in placed:
                                        if (abs(_pl["position"]["x"] - _ppin[0]) < _TOL and
                                                abs(_pl["position"]["y"] - _ppin[1]) < _TOL):
                                            _pwr_flag_nets.add(_pl["net"])
                    except Exception:
                        pass
                    power_nets_without_pwr_flag = sorted(_power_nets - _pwr_flag_nets)
            except Exception:
                pass

            result = {
                "success": len(failed) == 0,
                "message": f"Placed {len(placed)} label(s), {len(failed)} failed",
                "placed": placed,
                "failed": failed,
            }
            if power_nets_without_pwr_flag:
                result["warnings"] = [
                    f"Power nets without PWR_FLAG: {', '.join(power_nets_without_pwr_flag)}. "
                    "Add a PWR_FLAG component to each of these nets to suppress ERC power-pin errors."
                ]
            return result

        except Exception as e:
            logger.error(f"Error in batch_connect: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e), "errorDetails": traceback.format_exc()}

    def _handle_batch_add_and_connect(self, params):
        """Place multiple components and connect their pins in a single call."""
        logger.info("Batch add-and-connect: placing components and wiring nets")
        try:
            schematic_path = params.get("schematicPath")
            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}

            raw_components = params.get("components", [])
            if not raw_components:
                return {"success": False, "message": "components list is required and must be non-empty"}

            # Separate the nets field from the placement params so batch_add_components
            # receives a clean component list (it doesn't know about "nets").
            components_for_add = []
            nets_per_ref: dict = {}
            for comp in raw_components:
                comp_copy = {k: v for k, v in comp.items() if k != "nets"}
                components_for_add.append(comp_copy)
                nets = comp.get("nets") or {}
                if nets:
                    nets_per_ref[comp.get("reference", "")] = nets

            # Step 1: place all components
            add_params = {k: v for k, v in params.items() if k != "components"}
            add_params["components"] = components_for_add
            add_result = self._handle_batch_add_components(add_params)

            # Step 2: connect pins using the resolved pin locations
            connect_result = {"placed": [], "failed": [], "message": "no nets specified"}
            if nets_per_ref:
                connect_result = self._handle_batch_connect({
                    "schematicPath": schematic_path,
                    "connections": nets_per_ref,
                })

            added = add_result.get("added", [])
            add_errors = add_result.get("errors", [])
            conn_placed = connect_result.get("placed", [])
            conn_failed = connect_result.get("failed", [])

            return {
                "success": add_result.get("added_count", 0) > 0,
                "message": (
                    f"Placed {add_result.get('added_count', 0)} component(s)"
                    f"{' (' + str(len(add_errors)) + ' failed)' if add_errors else ''}, "
                    f"connected {len(conn_placed)} pin(s)"
                    f"{' (' + str(len(conn_failed)) + ' failed)' if conn_failed else ''}"
                ),
                "added_count": add_result.get("added_count", 0),
                "added": added,
                "connected_count": len(conn_placed),
                "connected": conn_placed,
                "placement_bbox": add_result.get("placement_bbox"),
                "errors": add_errors,
                "failed_connections": conn_failed,
                "warnings": connect_result.get("warnings", []),
            }

        except Exception as e:
            logger.error(f"Error in batch_add_and_connect: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e), "errorDetails": traceback.format_exc()}

    def _handle_list_unconnected_pins(self, params):
        """List pins with no net connection and no no-connect marker"""
        logger.info("Listing unconnected pins")
        try:
            from pathlib import Path
            from commands.pin_locator import PinLocator

            schematic_path = params.get("schematicPath")
            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}

            sch_path = Path(schematic_path)
            schematic = SchematicManager.load_schematic(schematic_path)
            if not schematic:
                return {"success": False, "message": "Failed to load schematic"}

            # Build set of connected (ref, pin_num) from netlist
            netlist = ConnectionManager.generate_netlist(schematic, sch_path)
            connected_pins = set()
            for net in netlist.get("nets", []):
                for conn in net.get("connections", []):
                    connected_pins.add((conn.get("component"), str(conn.get("pin"))))

            # Build set of no-connect positions
            no_connect_positions = set()
            if hasattr(schematic, "no_connect"):
                for nc in schematic.no_connect:
                    if hasattr(nc, "at") and hasattr(nc.at, "value"):
                        pos = nc.at.value
                        no_connect_positions.add((round(float(pos[0]), 2), round(float(pos[1]), 2)))

            locator = PinLocator()
            unconnected = []

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
                    unconnected.append({
                        "reference": ref,
                        "pinNumber": str(pin_num),
                        "pinName": pin_info.get("name", str(pin_num)),
                        "pinType": pin_info.get("type", "unknown"),
                        "position": {"x": coords[0], "y": coords[1]},
                    })

            return {"success": True, "unconnected": unconnected, "count": len(unconnected)}

        except Exception as e:
            logger.error(f"Error listing unconnected pins: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e), "errorDetails": traceback.format_exc()}

    def _handle_search_schematic_symbols(self, params):
        """Search for symbol names across KiCAD symbol libraries"""
        logger.info("Searching schematic symbols")
        try:
            import re
            from pathlib import Path
            from commands.dynamic_symbol_loader import DynamicSymbolLoader

            query = params.get("query", "").strip()
            max_results = min(int(params.get("maxResults", 20)), 100)
            schematic_path = params.get("schematicPath")

            if not query:
                return {"success": False, "message": "query is required"}

            # Build project library map: nickname -> resolved path
            # These take precedence over (and shadow) global libraries with the same nickname.
            project_libs: dict = {}  # nickname -> Path
            project_path = None
            if schematic_path:
                project_path = Path(schematic_path).parent
                loader_proj = DynamicSymbolLoader(project_path=project_path)
                sym_lib_table = project_path / "sym-lib-table"
                if sym_lib_table.exists():
                    try:
                        with open(sym_lib_table, "r", encoding="utf-8") as f:
                            table_content = f.read()
                        for m in re.finditer(
                            r'\(lib\s+\(name\s+"?([^"\)\s]+)"?\)\s*\(type\s+[^)]+\)\s*\(uri\s+"?([^"\)\s]+)"?',
                            table_content,
                            re.IGNORECASE,
                        ):
                            nickname = m.group(1)
                            uri = m.group(2)
                            resolved = loader_proj._resolve_sym_uri(uri)
                            if resolved:
                                p = Path(resolved)
                                if p.exists():
                                    project_libs[nickname] = p
                    except Exception as e:
                        logger.warning(f"Could not parse project sym-lib-table: {e}")

            loader = DynamicSymbolLoader(project_path=project_path)
            lib_dirs = loader.find_kicad_symbol_libraries()

            results = []
            query_lower = query.lower()
            sub_symbol_re = re.compile(r'.+_\d+_\d+$')

            def _search_lib_file(lib_file: Path, lib_name: str, shadowed_by: str = None):
                """Search a single .kicad_sym file and append matching symbols to results."""
                try:
                    content = lib_file.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    return
                symbol_names = re.findall(r'\(symbol\s+"([^"]+)"', content)
                for sym_name in symbol_names:
                    if len(results) >= max_results:
                        return
                    if sub_symbol_re.match(sym_name):
                        continue
                    if query_lower in sym_name.lower() or query_lower in lib_name.lower():
                        entry: dict = {
                            "library": lib_name,
                            "symbol": sym_name,
                            "fullName": f"{lib_name}:{sym_name}",
                        }
                        if shadowed_by:
                            entry["warning"] = (
                                f"Global library '{lib_name}' is shadowed by the project-local "
                                f"library with the same nickname. Use results from the project "
                                f"library instead, or check the project sym-lib-table."
                            )
                            entry["shadowed"] = True
                        results.append(entry)

            # 1. Search project-local libraries first (highest priority)
            for nickname, lib_file in project_libs.items():
                if len(results) >= max_results:
                    break
                _search_lib_file(lib_file, nickname)

            # 2. Search global libraries, skipping any whose nickname is shadowed by project libs
            for lib_dir in lib_dirs:
                if len(results) >= max_results:
                    break
                for lib_file in sorted(lib_dir.glob("*.kicad_sym")):
                    if len(results) >= max_results:
                        break
                    lib_name = lib_file.stem
                    if lib_name in project_libs:
                        # This global library is fully shadowed; skip silently
                        continue
                    _search_lib_file(lib_file, lib_name)

            return {"success": True, "results": results, "count": len(results)}

        except Exception as e:
            logger.error(f"Error searching schematic symbols: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e), "errorDetails": traceback.format_exc()}

    def _handle_list_symbol_pins(self, params):
        """List pin names and numbers for a symbol directly from its library (no schematic needed)"""
        logger.info("Listing symbol pins from library")
        try:
            from commands.dynamic_symbol_loader import DynamicSymbolLoader
            from pathlib import Path

            symbol_spec = params.get("symbol", "")
            schematic_path = params.get("schematicPath")

            if not symbol_spec or ":" not in symbol_spec:
                return {"success": False, "message": "symbol must be 'Library:SymbolName'"}

            library_name, symbol_name = symbol_spec.split(":", 1)

            project_path = None
            if schematic_path:
                project_path = Path(schematic_path).parent

            loader = DynamicSymbolLoader(project_path=project_path)
            try:
                pins = loader.list_symbol_pins(library_name, symbol_name)
            except ValueError as e:
                suggestions = getattr(e, "suggestions", [])
                return {
                    "success": False,
                    "message": str(e),
                    "suggestions": suggestions,
                }

            return {
                "success": True,
                "symbol": symbol_spec,
                "pin_count": len(pins),
                "pins": pins,
            }

        except Exception as e:
            logger.error(f"Error listing symbol pins: {str(e)}")
            return {"success": False, "message": str(e)}

    def _handle_batch_list_symbol_pins(self, params):
        """List pin names, numbers, and types for multiple symbols in a single call."""
        logger.info("Batch listing symbol pins")
        try:
            from commands.dynamic_symbol_loader import DynamicSymbolLoader
            from pathlib import Path

            symbols = params.get("symbols", [])
            schematic_path = params.get("schematicPath")
            compact = bool(params.get("compact", False))

            if not symbols:
                return {"success": False, "message": "symbols list is required"}

            # Standard 2-pin symmetric passives that qualify for compact mode
            COMPACT_SYMBOLS = {
                "Device:R", "Device:R_Small", "Device:R_US",
                "Device:C", "Device:C_Small", "Device:C_Polarized", "Device:C_Polarized_Small",
                "Device:L", "Device:L_Small",
                "Device:LED", "Device:D", "Device:D_Zener", "Device:D_Schottky",
                "Device:Ferrite_Bead",
            }

            project_path = None
            if schematic_path:
                project_path = Path(schematic_path).parent

            loader = DynamicSymbolLoader(project_path=project_path)
            results = {}
            errors = {}

            for symbol_spec in symbols:
                if ":" not in symbol_spec:
                    errors[symbol_spec] = "symbol must be 'Library:SymbolName'"
                    continue
                library_name, symbol_name = symbol_spec.split(":", 1)
                try:
                    pins = loader.list_symbol_pins(library_name, symbol_name)
                    # Compute body_bbox from pin positions in symbol-local coords (Y up, per lib convention).
                    # Expand pin envelope by 1.27mm (50mil) on each side — same padding batch_add_components uses.
                    pin_coords = [(p["x"], p["y"]) for p in pins if "x" in p]
                    body_bbox = None
                    if pin_coords:
                        _pad = 1.27
                        _xs = [c[0] for c in pin_coords]
                        _ys = [c[1] for c in pin_coords]
                        body_bbox = {
                            "x_min": round(min(_xs) - _pad, 4),
                            "y_min": round(min(_ys) - _pad, 4),
                            "x_max": round(max(_xs) + _pad, 4),
                            "y_max": round(max(_ys) + _pad, 4),
                            "width": round(max(_xs) - min(_xs) + 2 * _pad, 4),
                            "height": round(max(_ys) - min(_ys) + 2 * _pad, 4),
                        }
                    # Compact mode: omit per-pin detail for standard symmetric 2-pin passives
                    is_symmetric_2pin = (
                        len(pins) == 2 and
                        (symbol_spec in COMPACT_SYMBOLS or
                         (len(set(p.get("type", "") for p in pins)) == 1 and
                          all(p.get("type", "") == "passive" for p in pins)))
                    )
                    if compact and is_symmetric_2pin:
                        results[symbol_spec] = {
                            "pin_count": len(pins),
                            "body_bbox": body_bbox,
                            "is_symmetric": True,
                            "compact": True,
                            "note": "Pin detail omitted (compact mode, symmetric 2-pin passive). Set compact=false to see individual pin coords.",
                        }
                    else:
                        results[symbol_spec] = {"pins": pins, "pin_count": len(pins), "body_bbox": body_bbox}
                except ValueError as e:
                    suggestions = getattr(e, "suggestions", [])
                    errors[symbol_spec] = {"message": str(e), "suggestions": suggestions}

            return {
                "success": len(errors) == 0,
                "symbols": results,
                "errors": errors if errors else None,
            }

        except Exception as e:
            logger.error(f"Error in batch_list_symbol_pins: {str(e)}")
            return {"success": False, "message": str(e)}

    @staticmethod
    def _get_sheet_usable_area(schematic_path):
        """Return (left, top, right, bottom) usable area boundaries in mm for the schematic's paper size."""
        # KiCad border frame is approximately 12.7mm from each edge
        paper_dims = {
            "A4": (297.0, 210.0),
            "A3": (420.0, 297.0),
            "A2": (594.0, 420.0),
            "A1": (841.0, 594.0),
            "A0": (1189.0, 841.0),
            "A": (279.4, 215.9),   # US Letter
            "B": (431.8, 279.4),   # US Tabloid
            "C": (558.8, 431.8),
            "D": (863.6, 558.8),
            "E": (1117.6, 863.6),
        }
        border = 12.7
        width, height = 297.0, 210.0  # default A4
        try:
            import re
            with open(schematic_path, "r", encoding="utf-8") as f:
                content = f.read(4096)  # Only need the header
            m = re.search(r'\(paper\s+"([^"]+)"', content)
            if m:
                paper = m.group(1).strip()
                if paper in paper_dims:
                    width, height = paper_dims[paper]
        except Exception:
            pass
        return (border, border, width - border, height - border)

    def _handle_get_schematic_pin_locations(self, params):
        """Return exact pin endpoint coordinates for one or more schematic components"""
        logger.info("Getting schematic pin locations")
        try:
            from pathlib import Path
            from commands.pin_locator import PinLocator

            schematic_path = params.get("schematicPath")
            # Support both single 'reference' and batch 'references' list
            references_param = params.get("references")
            single_ref = params.get("reference")
            if references_param:
                references = list(references_param)
            elif single_ref:
                references = [single_ref]
            else:
                return {
                    "success": False,
                    "message": "Missing required parameters: schematicPath and reference or references",
                }

            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}

            locator = PinLocator()
            sch_path = Path(schematic_path)
            components_result = {}

            # Sheet boundaries for near_boundary detection
            left_b, top_b, right_b, bottom_b = KiCADInterface._get_sheet_usable_area(schematic_path)
            near_threshold = 20.0
            worst_case_label_mm = 15.0  # 10 chars × ~1.5mm/char

            for reference in references:
                all_pins = locator.get_all_symbol_pins(sch_path, reference)
                if not all_pins:
                    components_result[reference] = {}
                    continue

                lib_id = locator._get_lib_id(sch_path, reference) if hasattr(locator, "_get_lib_id") else None
                pins_def = locator.get_symbol_pins(sch_path, lib_id) if lib_id else {}

                pins_out = {}
                for pin_num, coords in all_pins.items():
                    px, py = coords[0], coords[1]
                    entry = {"x": px, "y": py}
                    if pin_num in pins_def:
                        entry["name"] = pins_def[pin_num].get("name", pin_num)
                    # Near-boundary detection: check left and top boundaries
                    near_left = px - left_b < near_threshold
                    near_top = py - top_b < near_threshold
                    if near_left or near_top:
                        entry["near_boundary"] = True
                        if near_left:
                            # Leftward label (angle=180) extends left from pin; needs pin_x - label_len >= left_b
                            min_pin_x = left_b + worst_case_label_mm
                            entry["suggested_component_x_offset"] = round(max(0.0, min_pin_x - px), 2)
                    else:
                        entry["near_boundary"] = False
                    pins_out[pin_num] = entry
                components_result[reference] = pins_out

            # For backwards compatibility: if single ref was requested, also populate 'pins'
            if single_ref and not references_param:
                pins = components_result.get(single_ref, {})
                if not pins:
                    available_refs = []
                    try:
                        from skip import Schematic as SkipSchematic
                        sch = SkipSchematic(schematic_path)
                        available_refs = [
                            s.property.Reference.value
                            for s in sch.symbol
                            if hasattr(s.property, "Reference")
                            and not s.property.Reference.value.startswith("_TEMPLATE")
                        ]
                    except Exception:
                        pass
                    msg = f"No pins found for {single_ref} — check reference and schematic path"
                    if available_refs:
                        msg += f". Available references: {', '.join(sorted(set(available_refs)))}"
                    return {"success": False, "message": msg}
                return {"success": True, "reference": single_ref, "pins": pins, "components": components_result}

            return {"success": True, "components": components_result}

        except Exception as e:
            logger.error(f"Error getting pin locations: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_get_schematic_view(self, params):
        """Get a rasterised image of the schematic (SVG export → PNG conversion).

        Always renders on a white background so the image is immediately readable.
        """
        logger.info("Getting schematic view")
        import subprocess
        import tempfile
        import base64
        import re as _re

        # Target pixels-per-mm for auto-sizing.  10 px/mm ≈ 254 DPI on a standard
        # schematic — sharp enough to read labels without being excessively large.
        _PX_PER_MM = 10

        def _inject_white_background(svg_text):
            """Insert a white <rect> covering the full viewBox as the first drawn element.
            Returns (modified_svg_text, viewbox_width_mm, viewbox_height_mm)."""
            vb_w = vb_h = None
            m = _re.search(r'viewBox="([^"]+)"', svg_text)
            if m:
                parts = m.group(1).split()
                try:
                    vb_w, vb_h = float(parts[2]), float(parts[3])
                    rect = f'<rect x="0" y="0" width="{vb_w}" height="{vb_h}" fill="white"/>'
                    svg_text = _re.sub(r'(<(?:g|path|text|circle|rect|line|polyline|polygon)[^>]*>)', rect + r'\1', svg_text, count=1)
                except (IndexError, ValueError):
                    pass
            return svg_text, vb_w, vb_h

        def _crop_svg_to_content(svg_text, schematic_path_str, margin_mm=10.0):
            """Rewrite the SVG viewBox/width/height to tightly fit schematic content.

            Derives the content bounding box from component body_bboxes, component
            positions, and label positions — which are reliable and exclude the
            page-border frame drawn by KiCAD.  Falls back to the original SVG if
            data cannot be obtained.
            Returns (modified_svg, new_w_mm, new_h_mm) or the original string on failure.
            """
            xs, ys = [], []
            try:
                comp_result = self._handle_list_schematic_components({"schematicPath": schematic_path_str})
                for comp in comp_result.get("components", []):
                    ref = comp.get("reference", "")
                    if ref.startswith("#") or ref.startswith("_"):
                        continue
                    bb = comp.get("body_bbox")
                    if bb:
                        xs += [bb["x_min"], bb["x_max"]]
                        ys += [bb["y_min"], bb["y_max"]]
                    else:
                        px, py = comp["position"]["x"], comp["position"]["y"]
                        xs.append(px); ys.append(py)
                    # Include field text positions
                    for fkey in ("ref_field", "value_field"):
                        f = comp.get(fkey, {})
                        if f.get("x") is not None:
                            xs.append(f["x"]); ys.append(f["y"])

                lbl_result = self._handle_list_schematic_labels({"schematicPath": schematic_path_str})
                for lbl in lbl_result.get("labels", []):
                    pos = lbl.get("position", {})
                    if pos.get("x") is not None:
                        xs.append(pos["x"]); ys.append(pos["y"])
            except Exception:
                pass

            if not xs or not ys:
                return svg_text

            x_min = min(xs) - margin_mm
            y_min = min(ys) - margin_mm
            new_w = round(max(xs) - min(xs) + 2 * margin_mm, 4)
            new_h = round(max(ys) - min(ys) + 2 * margin_mm, 4)

            svg_text = _re.sub(r'viewBox="[^"]+"', f'viewBox="{x_min:.4f} {y_min:.4f} {new_w:.4f} {new_h:.4f}"', svg_text, count=1)
            svg_text = _re.sub(r'(<svg[^>]*\s)width="[^"]+"', rf'\1width="{new_w:.4f}mm"', svg_text, count=1)
            svg_text = _re.sub(r'(<svg[^>]*\s)height="[^"]+"', rf'\1height="{new_h:.4f}mm"', svg_text, count=1)
            svg_text = _re.sub(
                r'<rect x="[^"]*" y="[^"]*" width="[^"]*" height="[^"]*" fill="white"/>',
                f'<rect x="{x_min:.4f}" y="{y_min:.4f}" width="{new_w:.4f}" height="{new_h:.4f}" fill="white"/>',
                svg_text, count=1,
            )
            return svg_text, new_w, new_h

        try:
            schematic_path = params.get("schematicPath")
            if not schematic_path or not os.path.exists(schematic_path):
                return {
                    "success": False,
                    "message": f"Schematic not found: {schematic_path}",
                }

            fmt = params.get("format", "png")
            # width/height are optional — if omitted, auto-sized from the SVG viewBox
            explicit_width = params.get("width")
            explicit_height = params.get("height")
            # crop=True by default: trim the A4/letter page whitespace down to content
            crop = params.get("crop", True)

            # Step 1: Export schematic to SVG via kicad-cli (transparent background)
            with tempfile.TemporaryDirectory() as tmpdir:
                cmd = [
                    "kicad-cli",
                    "sch",
                    "export",
                    "svg",
                    "--output",
                    tmpdir,
                    "--no-background-color",
                    schematic_path,
                ]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

                if result.returncode != 0:
                    return {
                        "success": False,
                        "message": f"kicad-cli SVG export failed: {result.stderr}",
                    }

                import glob
                svg_files = glob.glob(os.path.join(tmpdir, "*.svg"))
                if not svg_files:
                    return {
                        "success": False,
                        "message": "No SVG file produced by kicad-cli",
                    }
                svg_path = svg_files[0]

                with open(svg_path, "r", encoding="utf-8") as f:
                    svg_data = f.read()

                # Inject white background so the SVG is readable (transparent → black in cairosvg)
                svg_data_white, vb_w, vb_h = _inject_white_background(svg_data)

                # Crop SVG viewBox to content bounds (trims A4/letter page whitespace)
                if crop:
                    try:
                        result_crop = _crop_svg_to_content(svg_data_white, schematic_path)
                        if isinstance(result_crop, tuple):
                            svg_data_white, vb_w, vb_h = result_crop
                    except Exception as crop_svg_err:
                        logger.warning(f"SVG crop failed: {crop_svg_err}")

                if fmt == "svg":
                    return {"success": True, "imageData": svg_data_white, "format": "svg"}

                # Step 2: Convert SVG to PNG using cairosvg
                try:
                    from cairosvg import svg2png
                except ImportError:
                    return {
                        "success": True,
                        "imageData": svg_data_white,
                        "format": "svg",
                        "message": "cairosvg not installed — returning SVG instead of PNG. Install with: pip install cairosvg",
                    }

                # Auto-size: scale so 1 mm = _PX_PER_MM pixels, preserving aspect ratio.
                # Explicit width/height override this.
                if explicit_width or explicit_height:
                    width = int(explicit_width) if explicit_width else None
                    height = int(explicit_height) if explicit_height else None
                elif vb_w and vb_h:
                    width = int(round(vb_w * _PX_PER_MM))
                    height = int(round(vb_h * _PX_PER_MM))
                else:
                    width, height = 2400, 1800  # safe fallback

                png_data = svg2png(
                    bytestring=svg_data_white.encode("utf-8"),
                    output_width=width,
                    output_height=height,
                )

                # Crop to component bounding box if requested
                if crop:
                    try:
                        from PIL import Image, ImageChops
                        import io as _io
                        img = Image.open(_io.BytesIO(png_data)).convert("RGB")
                        bg = Image.new("RGB", img.size, (255, 255, 255))
                        diff = ImageChops.difference(img, bg)
                        bbox = diff.getbbox()
                        if bbox:
                            margin_px = max(20, int(min(img.width, img.height) * 0.04))
                            left = max(0, bbox[0] - margin_px)
                            top = max(0, bbox[1] - margin_px)
                            right = min(img.width, bbox[2] + margin_px)
                            bottom = min(img.height, bbox[3] + margin_px)
                            img = img.crop((left, top, right, bottom))
                        buf = _io.BytesIO()
                        img.save(buf, format="PNG")
                        png_data = buf.getvalue()
                    except ImportError:
                        logger.info("Pillow not installed — returning uncropped image (pip install Pillow to enable crop)")
                    except Exception as crop_err:
                        logger.warning(f"Crop failed: {crop_err}")

                return {
                    "success": True,
                    "imageData": base64.b64encode(png_data).decode("utf-8"),
                    "format": "png",
                    "width": width,
                    "height": height,
                }

        except FileNotFoundError:
            return {"success": False, "message": "kicad-cli not found in PATH"}
        except Exception as e:
            logger.error(f"Error getting schematic view: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_list_schematic_components(self, params):
        """List all components in a schematic"""
        logger.info("Listing schematic components")
        try:
            from pathlib import Path
            from commands.pin_locator import PinLocator

            schematic_path = params.get("schematicPath")
            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}

            sch_file = Path(schematic_path)
            if not sch_file.exists():
                return {
                    "success": False,
                    "message": f"Schematic not found: {schematic_path}",
                }

            schematic = SchematicManager.load_schematic(schematic_path)
            if not schematic:
                return {"success": False, "message": "Failed to load schematic"}

            # Read raw content once for property extraction
            with open(sch_file, "r", encoding="utf-8") as f:
                raw_content = f.read()

            # Optional filters
            filter_params = params.get("filter", {})
            lib_id_filter = filter_params.get("libId", "")
            ref_prefix_filter = filter_params.get("referencePrefix", "")

            locator = PinLocator()
            components = []

            for symbol in schematic.symbol:
                if not hasattr(symbol.property, "Reference"):
                    continue
                ref = symbol.property.Reference.value
                # Skip template symbols
                if ref.startswith("_TEMPLATE"):
                    continue

                lib_id = symbol.lib_id.value if hasattr(symbol, "lib_id") else ""

                # Apply filters
                if lib_id_filter and lib_id_filter not in lib_id:
                    continue
                if ref_prefix_filter and not ref.startswith(ref_prefix_filter):
                    continue

                value = (
                    symbol.property.Value.value
                    if hasattr(symbol.property, "Value")
                    else ""
                )
                footprint = (
                    symbol.property.Footprint.value
                    if hasattr(symbol.property, "Footprint")
                    else ""
                )
                position = symbol.at.value if hasattr(symbol, "at") else [0, 0, 0]
                uuid_val = symbol.uuid.value if hasattr(symbol, "uuid") else ""

                comp = {
                    "reference": ref,
                    "libId": lib_id,
                    "value": value,
                    "footprint": footprint,
                    "position": {"x": float(position[0]), "y": float(position[1])},
                    "rotation": float(position[2]) if len(position) > 2 else 0,
                    "uuid": str(uuid_val),
                }

                # Extract all KiCad properties (MPN, Description, Manufacturer, etc.)
                # and Reference/Value field positions
                try:
                    block_text, _, _ = KiCADInterface._find_placed_symbol_block(
                        raw_content, ref
                    )
                    if block_text:
                        comp["properties"] = KiCADInterface._extract_component_properties(
                            block_text
                        )
                        ref_pos = KiCADInterface._extract_property_position(block_text, "Reference")
                        if ref_pos:
                            ref_pos["visible"] = KiCADInterface._extract_property_visible(block_text, "Reference")
                            comp["ref_field"] = ref_pos
                        val_pos = KiCADInterface._extract_property_position(block_text, "Value")
                        if val_pos:
                            val_pos["visible"] = KiCADInterface._extract_property_visible(block_text, "Value")
                            comp["value_field"] = val_pos
                except Exception:
                    pass

                # Get pins if available
                try:
                    all_pins = locator.get_all_symbol_pins(sch_file, ref)
                    if all_pins:
                        pins_def = locator.get_symbol_pins(sch_file, lib_id) or {}
                        pin_list = []
                        for pin_num, coords in all_pins.items():
                            pin_info = {
                                "number": pin_num,
                                "position": {"x": coords[0], "y": coords[1]},
                            }
                            if pin_num in pins_def:
                                pin_info["name"] = pins_def[pin_num].get(
                                    "name", pin_num
                                )
                            pin_list.append(pin_info)
                        comp["pins"] = pin_list
                        if pin_list:
                            xs = [p["position"]["x"] for p in pin_list]
                            ys = [p["position"]["y"] for p in pin_list]
                            comp["bounds"] = {"minX": min(xs), "maxX": max(xs), "minY": min(ys), "maxY": max(ys)}
                            pad = 1.27
                            comp["body_bbox"] = {
                                "x_min": min(xs) - pad, "y_min": min(ys) - pad,
                                "x_max": max(xs) + pad, "y_max": max(ys) + pad,
                            }
                except Exception:
                    pass  # Pin lookup is best-effort

                components.append(comp)

            return {"success": True, "components": components, "count": len(components)}

        except Exception as e:
            logger.error(f"Error listing schematic components: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_check_schematic_layout(self, params):
        """Analyze a schematic for layout violations: out-of-bounds, overlaps, misplaced text."""
        logger.info("Checking schematic layout")
        try:
            from pathlib import Path

            schematic_path = params.get("schematicPath")
            autofix = params.get("autofix", False)
            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}

            sch_file = Path(schematic_path)
            if not sch_file.exists():
                return {"success": False, "message": f"Schematic not found: {schematic_path}"}

            # Get sheet usable area
            left_b, top_b, right_b, bottom_b = KiCADInterface._get_sheet_usable_area(schematic_path)

            # Load components (re-use list handler logic)
            comp_result = self._handle_list_schematic_components({"schematicPath": schematic_path})
            if not comp_result.get("success"):
                return comp_result
            components = comp_result.get("components", [])

            # Load labels for out-of-bounds label check
            labels_result = self._handle_list_schematic_labels({"schematicPath": schematic_path})
            labels = labels_result.get("labels", []) if labels_result.get("success") else []

            violations = []
            chars_per_mm = 1.5  # approximate mm per character
            worst_case_chars = 10

            def bbox_overlaps(a, b, margin=0.0):
                return (a["x_min"] - margin < b["x_max"] and a["x_max"] + margin > b["x_min"] and
                        a["y_min"] - margin < b["y_max"] and a["y_max"] + margin > b["y_min"])

            def point_in_bbox(px, py, bbox):
                return bbox["x_min"] <= px <= bbox["x_max"] and bbox["y_min"] <= py <= bbox["y_max"]

            # Build index of body_bbox per component
            comp_bboxes = {}
            for c in components:
                if "body_bbox" in c:
                    comp_bboxes[c["reference"]] = c["body_bbox"]
                else:
                    # Fall back to position ± small pad
                    cx, cy = c["position"]["x"], c["position"]["y"]
                    comp_bboxes[c["reference"]] = {"x_min": cx - 2.54, "y_min": cy - 2.54, "x_max": cx + 2.54, "y_max": cy + 2.54}

            # 1. Out-of-bounds components
            for c in components:
                bb = comp_bboxes.get(c["reference"])
                if bb:
                    if bb["x_min"] < left_b or bb["x_max"] > right_b or bb["y_min"] < top_b or bb["y_max"] > bottom_b:
                        violations.append({
                            "type": "out_of_bounds_component",
                            "affected_refs": [c["reference"]],
                            "position": c["position"],
                            "description": f"{c['reference']} body bbox [{bb['x_min']:.1f},{bb['y_min']:.1f},{bb['x_max']:.1f},{bb['y_max']:.1f}] extends outside sheet usable area [{left_b},{top_b},{right_b},{bottom_b}]",
                        })

            # 2. Out-of-bounds labels (estimate text endpoint based on angle and length)
            for lbl in labels:
                if lbl.get("type") not in ("net", "global"):
                    continue
                name = lbl.get("name", "")
                lx = lbl["position"]["x"]
                ly = lbl["position"]["y"]
                angle = lbl.get("angle", 0)
                text_len = len(name) * chars_per_mm
                import math
                rad = math.radians(angle)
                end_x = lx + text_len * math.cos(rad)
                end_y = ly + text_len * math.sin(rad)
                out = (
                    min(lx, end_x) < left_b or max(lx, end_x) > right_b or
                    min(ly, end_y) < top_b or max(ly, end_y) > bottom_b
                )
                if out:
                    violations.append({
                        "type": "out_of_bounds_label",
                        "affected_refs": [name],
                        "position": lbl["position"],
                        "description": f"Label '{name}' at ({lx:.1f},{ly:.1f}) angle={angle} estimated endpoint ({end_x:.1f},{end_y:.1f}) extends outside sheet boundary",
                    })

            # 3. Overlapping component bodies (within 2mm)
            ref_list = list(comp_bboxes.keys())
            for i in range(len(ref_list)):
                for j in range(i + 1, len(ref_list)):
                    ra, rb = ref_list[i], ref_list[j]
                    if bbox_overlaps(comp_bboxes[ra], comp_bboxes[rb], margin=2.0):
                        violations.append({
                            "type": "overlapping_components",
                            "affected_refs": [ra, rb],
                            "position": None,
                            "description": f"{ra} and {rb} body bounding boxes overlap or are within 2mm of each other",
                        })

            # 4. Ref/Val text inside parent component body.
            # For all components, use the actual body_bbox (derived from pin extents).
            # The suggested_fix mirrors the auto_position_fields logic: perpendicular to pin
            # axis for 2-pin components; above/below body extent for multi-pin components.
            for c in components:
                parent_bb = comp_bboxes.get(c["reference"])
                if not parent_bb:
                    continue
                cx_c = c["position"]["x"]
                cy_c = c["position"]["y"]
                _OFF = 2.54
                _num_pins_c = len(c.get("pins", []))
                # Determine suggested fix direction: same logic as auto_position_fields.
                # 2-pin: check pin axis via bbox aspect ratio; multi-pin: above/below.
                _bb_width = parent_bb["x_max"] - parent_bb["x_min"]
                _bb_height = parent_bb["y_max"] - parent_bb["y_min"]
                _vertical_axis = _bb_height > _bb_width  # True → pins top/bottom → labels left/right
                for field_key, label in [("ref_field", "Reference"), ("value_field", "Value")]:
                    field = c.get(field_key)
                    if field and point_in_bbox(field["x"], field["y"], parent_bb):
                        if _num_pins_c == 2 and _vertical_axis:
                            # Vertical pin axis → labels left/right at angle=0
                            _fix_x = round(cx_c - _OFF, 4) if label == "Reference" else round(cx_c + _OFF, 4)
                            _fix_y = cy_c
                            _fix_angle = 0
                        elif _num_pins_c == 2 and not _vertical_axis:
                            # Horizontal pin axis → labels above/below at angle=0
                            _fix_x = cx_c
                            _fix_y = round(cy_c - _OFF, 4) if label == "Reference" else round(cy_c + _OFF, 4)
                            _fix_angle = 0
                        else:
                            # Multi-pin: above topmost / below bottommost
                            _fix_x = cx_c
                            _fix_y = round(parent_bb["y_min"] - _OFF, 4) if label == "Reference" else round(parent_bb["y_max"] + _OFF, 4)
                            _fix_angle = 0
                        violations.append({
                            "type": "text_inside_parent_body",
                            "affected_refs": [c["reference"]],
                            "position": {"x": field["x"], "y": field["y"]},
                            "description": f"{c['reference']} {label} text at ({field['x']},{field['y']}) is inside its own body bbox",
                            "suggested_fix": {"reference": c["reference"], "property": label,
                                              "x": _fix_x, "y": _fix_y, "angle": _fix_angle},
                        })

            # 5. Ref/Val text overlapping another component's body
            for c in components:
                for field_key, label in [("ref_field", "Reference"), ("value_field", "Value")]:
                    field = c.get(field_key)
                    if not field:
                        continue
                    for other_ref, other_bb in comp_bboxes.items():
                        if other_ref == c["reference"]:
                            continue
                        if point_in_bbox(field["x"], field["y"], other_bb):
                            violations.append({
                                "type": "text_overlaps_other_body",
                                "affected_refs": [c["reference"], other_ref],
                                "position": {"x": field["x"], "y": field["y"]},
                                "description": f"{c['reference']} {label} text at ({field['x']},{field['y']}) overlaps body of {other_ref}",
                            })

            # 6. Field text bounding-box overlap between different components.
            # Estimate text bbox: width ≈ num_chars × 0.75mm (at 1.27mm font), height = 1.5mm.
            # Only checks Reference and Value fields (hidden fields are excluded).
            # Uses a simple axis-aligned bbox — text angle is ignored for speed.
            CHAR_WIDTH_MM = 0.75  # approx glyph advance for 1.27mm KiCAD font
            TEXT_HEIGHT_MM = 1.5  # generous height including descenders
            FIELD_OVERLAP_MARGIN = 0.5  # mm gap still triggers a warning

            def field_text_bbox(fx, fy, text):
                half_w = max(len(str(text)) * CHAR_WIDTH_MM / 2.0, 1.0)
                half_h = TEXT_HEIGHT_MM / 2.0
                return {
                    "x_min": fx - half_w,
                    "x_max": fx + half_w,
                    "y_min": fy - half_h,
                    "y_max": fy + half_h,
                }

            # Build flat list of (ref, field_label, text_value, x, y) for visible fields
            all_fields = []
            for c in components:
                for field_key, label in [("ref_field", "Reference"), ("value_field", "Value")]:
                    field = c.get(field_key)
                    if not field:
                        continue
                    if field.get("visible") is False:
                        continue
                    text_val = c["reference"] if label == "Reference" else c.get("value", "")
                    all_fields.append((c["reference"], label, text_val, field["x"], field["y"]))

            for i in range(len(all_fields)):
                ref_a, lbl_a, txt_a, fx_a, fy_a = all_fields[i]
                bb_a = field_text_bbox(fx_a, fy_a, txt_a)
                for j in range(i + 1, len(all_fields)):
                    ref_b, lbl_b, txt_b, fx_b, fy_b = all_fields[j]
                    bb_b = field_text_bbox(fx_b, fy_b, txt_b)
                    if bbox_overlaps(bb_a, bb_b, margin=FIELD_OVERLAP_MARGIN):
                        # Suggest moving field_a away from field_b by 2.54mm
                        import math as _math
                        _dx = fx_a - fx_b
                        _dy = fy_a - fy_b
                        _dist = _math.sqrt(_dx * _dx + _dy * _dy) or 1.0
                        _sep = 3.0  # mm to separate them
                        _fix_x_a = round(fx_a + _sep * _dx / _dist, 4)
                        _fix_y_a = round(fy_a + _sep * _dy / _dist, 4)
                        violations.append({
                            "type": "field_text_overlap",
                            "affected_refs": [ref_a, ref_b],
                            "position": {"x": (fx_a + fx_b) / 2, "y": (fy_a + fy_b) / 2},
                            "description": (
                                f"{ref_a}.{lbl_a} text at ({fx_a},{fy_a}) overlaps "
                                f"{ref_b}.{lbl_b} text at ({fx_b},{fy_b})"
                            ),
                            "suggested_fix": {"reference": ref_a, "property": lbl_a,
                                              "x": _fix_x_a, "y": _fix_y_a, "angle": 0},
                        })

            # 7. Net label proximity / overlap.
            # Estimate the text bounding box for each net/global label based on its
            # position, text length, and angle.  Flag pairs whose text boxes overlap
            # or are within LABEL_GAP_MM of each other — these render as illegible
            # clutter (e.g. two "VBUS" labels facing each other on adjacent pin tips).
            LABEL_CHAR_WIDTH = 1.27   # mm per character at KiCad default 1.27mm font
            LABEL_HALF_HEIGHT = 0.7   # half the label text height (generous)
            LABEL_GAP_MM = 0.5        # minimum required gap between label text boxes

            def label_text_bbox(lx, ly, name, angle):
                tw = max(len(name), 1) * LABEL_CHAR_WIDTH
                hh = LABEL_HALF_HEIGHT
                a = int(round(angle)) % 360
                if a == 0:    # text extends right
                    return {"x_min": lx,      "y_min": ly - hh, "x_max": lx + tw,  "y_max": ly + hh}
                if a == 180:  # text extends left
                    return {"x_min": lx - tw, "y_min": ly - hh, "x_max": lx,       "y_max": ly + hh}
                if a == 90:   # text extends upward (smaller y)
                    return {"x_min": lx - hh, "y_min": ly - tw, "x_max": lx + hh,  "y_max": ly}
                if a == 270:  # text extends downward (larger y)
                    return {"x_min": lx - hh, "y_min": ly,      "x_max": lx + hh,  "y_max": ly + tw}
                # Arbitrary angle: use a square approximation
                import math
                rad = math.radians(angle)
                ex = lx + tw * math.cos(rad)
                ey = ly + tw * math.sin(rad)
                return {
                    "x_min": min(lx, ex) - hh, "y_min": min(ly, ey) - hh,
                    "x_max": max(lx, ex) + hh, "y_max": max(ly, ey) + hh,
                }

            net_labels_for_check = [l for l in labels if l.get("type") in ("net", "global")]
            label_bb_list = [
                (lbl, label_text_bbox(
                    lbl["position"]["x"], lbl["position"]["y"],
                    lbl.get("name", ""), lbl.get("angle", 0)))
                for lbl in net_labels_for_check
            ]
            for i in range(len(label_bb_list)):
                lbl_a, bb_a = label_bb_list[i]
                for j in range(i + 1, len(label_bb_list)):
                    lbl_b, bb_b = label_bb_list[j]
                    if bbox_overlaps(bb_a, bb_b, margin=LABEL_GAP_MM):
                        same_net = lbl_a.get("name") == lbl_b.get("name")
                        # For exact-coordinate duplicates (same net, within 0.3mm):
                        # suggest deleting one of the labels.
                        _dist = ((lbl_a["position"]["x"] - lbl_b["position"]["x"]) ** 2 +
                                 (lbl_a["position"]["y"] - lbl_b["position"]["y"]) ** 2) ** 0.5
                        is_duplicate = same_net and _dist < 0.3

                        violation: dict = {
                            "type": "label_overlap",
                            "affected_refs": [lbl_a.get("name"), lbl_b.get("name")],
                            "position": {
                                "x": (lbl_a["position"]["x"] + lbl_b["position"]["x"]) / 2,
                                "y": (lbl_a["position"]["y"] + lbl_b["position"]["y"]) / 2,
                            },
                            "description": (
                                f"Label '{lbl_a['name']}' at "
                                f"({lbl_a['position']['x']},{lbl_a['position']['y']}) "
                                f"angle={lbl_a.get('angle',0)} overlaps or is too close to "
                                f"label '{lbl_b['name']}' at "
                                f"({lbl_b['position']['x']},{lbl_b['position']['y']}) "
                                f"angle={lbl_b.get('angle',0)} — "
                                + ("exact duplicate label: delete one using delete_schematic_net_label"
                                   if is_duplicate else
                                   "move the components further apart or use a shared net label")
                            ),
                        }
                        if is_duplicate:
                            # Suggest deleting the second label (lbl_b)
                            violation["suggested_delete_label"] = {
                                "net": lbl_b.get("name"),
                                "position": lbl_b["position"],
                                "angle": lbl_b.get("angle", 0),
                                "action": "delete_schematic_net_label",
                            }
                        violations.append(violation)

            # 8. Stray wire detection.
            # Parse all wire segments from the schematic; collect every endpoint.
            # A wire endpoint is "dangling" if no other wire endpoint, pin tip, net
            # label, junction, or no_connect marker sits within tolerance of it.
            # An isolated wire (both endpoints dangling) is reported as stray_wire.
            try:
                import sexpdata as _swd
                from sexpdata import Symbol as _SwSym
                with open(schematic_path, "r", encoding="utf-8") as _wf:
                    _sch_sexp = _swd.loads(_wf.read())

                _WIRE_TOL = 0.3  # mm — snap-grid tolerance

                # Collect wire endpoints: list of (x, y) tuples
                wire_segments = []  # [(x1,y1,x2,y2), ...]
                wire_endpoints = []
                for _item in _sch_sexp:
                    if not (isinstance(_item, list) and len(_item) > 0
                            and _item[0] == _SwSym("wire")):
                        continue
                    _pts = next(
                        (p for p in _item if isinstance(p, list) and len(p) > 0
                         and p[0] == _SwSym("pts")), None
                    )
                    if not _pts:
                        continue
                    xy_items = [p for p in _pts if isinstance(p, list) and len(p) >= 3
                                and p[0] == _SwSym("xy")]
                    if len(xy_items) >= 2:
                        x1, y1 = float(xy_items[0][1]), float(xy_items[0][2])
                        x2, y2 = float(xy_items[1][1]), float(xy_items[1][2])
                        wire_segments.append((x1, y1, x2, y2))
                        wire_endpoints.append((x1, y1))
                        wire_endpoints.append((x2, y2))

                if wire_segments:
                    # Build connected-point set: all pin tips + label positions + junctions
                    connected_pts: set = set()

                    # Pin tips for all placed components
                    try:
                        from commands.pin_locator import PinLocator as _SPL
                        _sl = _SPL()
                        for _sc in schematic.symbol:
                            if not hasattr(_sc.property, "Reference"):
                                continue
                            _sref = _sc.property.Reference.value
                            if _sref.startswith("_TEMPLATE") or _sref.startswith("#"):
                                continue
                            _spins = _sl.get_all_symbol_pins(sch_path, _sref) or {}
                            for _sp in _spins.values():
                                _spx = float(_sp[0]) if isinstance(_sp, (list, tuple)) else float(_sp["x"])
                                _spy = float(_sp[1]) if isinstance(_sp, (list, tuple)) else float(_sp["y"])
                                connected_pts.add((round(_spx, 2), round(_spy, 2)))
                    except Exception as _pe:
                        logger.warning(f"Stray wire: pin collection failed: {_pe}")

                    # Label positions
                    for _lbl in labels:
                        connected_pts.add((
                            round(_lbl["position"]["x"], 2),
                            round(_lbl["position"]["y"], 2),
                        ))

                    # Junctions
                    for _item in _sch_sexp:
                        if (isinstance(_item, list) and len(_item) > 0
                                and _item[0] == _SwSym("junction")):
                            _at = next(
                                (p for p in _item if isinstance(p, list) and len(p) >= 3
                                 and p[0] == _SwSym("at")), None
                            )
                            if _at:
                                connected_pts.add((round(float(_at[1]), 2), round(float(_at[2]), 2)))

                    # All other wire endpoints are also valid connection points
                    all_wire_pt_keys = {(round(x, 2), round(y, 2)) for x, y in wire_endpoints}

                    def _is_connected(ex, ey):
                        """True if (ex, ey) has any connection other than just being a wire endpoint."""
                        ex_r, ey_r = round(ex, 2), round(ey, 2)
                        # Check against pins and labels
                        for cx, cy in connected_pts:
                            if abs(ex_r - cx) <= _WIRE_TOL and abs(ey_r - cy) <= _WIRE_TOL:
                                return True
                        # Count how many wire endpoints share this coordinate
                        count = sum(
                            1 for (wx, wy) in wire_endpoints
                            if abs(round(wx, 2) - ex_r) <= _WIRE_TOL
                            and abs(round(wy, 2) - ey_r) <= _WIRE_TOL
                        )
                        # Connected if 2+ wire endpoints share this point (T/cross junction)
                        return count >= 2

                    for x1, y1, x2, y2 in wire_segments:
                        d1 = _is_connected(x1, y1)
                        d2 = _is_connected(x2, y2)
                        if not d1 and not d2:
                            violations.append({
                                "type": "stray_wire",
                                "affected_refs": [],
                                "position": {"x": (x1 + x2) / 2, "y": (y1 + y2) / 2},
                                "description": (
                                    f"Isolated wire from ({x1:.2f},{y1:.2f}) to ({x2:.2f},{y2:.2f}) "
                                    "has no connection at either endpoint — likely a leftover from a deleted component. "
                                    "Delete it with delete_schematic_wire."
                                ),
                            })
                        elif not d1:
                            violations.append({
                                "type": "stray_wire",
                                "affected_refs": [],
                                "position": {"x": x1, "y": y1},
                                "description": (
                                    f"Wire endpoint at ({x1:.2f},{y1:.2f}) has no connection "
                                    "(no pin, label, junction, or other wire). "
                                    "Delete the wire or extend it to connect to a pin."
                                ),
                            })
                        elif not d2:
                            violations.append({
                                "type": "stray_wire",
                                "affected_refs": [],
                                "position": {"x": x2, "y": y2},
                                "description": (
                                    f"Wire endpoint at ({x2:.2f},{y2:.2f}) has no connection "
                                    "(no pin, label, junction, or other wire). "
                                    "Delete the wire or extend it to connect to a pin."
                                ),
                            })
            except Exception as _we:
                logger.warning(f"Stray wire check failed: {_we}")

            autofix_applied = []
            autofix_failed = []
            if autofix:
                fixable = [v["suggested_fix"] for v in violations if "suggested_fix" in v]
                if fixable:
                    fix_result = self._handle_batch_set_schematic_property_positions({
                        "schematicPath": schematic_path,
                        "updates": fixable,
                    })
                    autofix_applied = fix_result.get("applied", [])
                    autofix_failed = fix_result.get("failed", [])
                    # Remove violations whose fix was applied
                    applied_keys = {(a["reference"], a["property"]) for a in autofix_applied}
                    violations = [
                        v for v in violations
                        if "suggested_fix" not in v or
                        (v["suggested_fix"]["reference"], v["suggested_fix"]["property"]) not in applied_keys
                    ]

            result = {
                "success": True,
                "violations": violations,
                "violation_count": len(violations),
                "sheet_usable_area": {"left": left_b, "top": top_b, "right": right_b, "bottom": bottom_b},
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

    def _handle_autoplace_schematic_fields(self, params):
        """Re-position Reference and Value fields so they sit outside the component body
        AND outside any net labels hanging off its pins.

        Algorithm for each component:
        1. Compute the 'extended body bbox' = body_bbox union the bboxes of all net labels
           whose connection point (at) is within 0.5 mm of a pin tip.
        2. For 2-pin components: use pin-axis direction (same heuristic as batch_add_components).
           For multi-pin: prefer above/below; if that collides with another component's
           extended bbox, try left/right.
        3. Field centres are placed at extended_bbox_edge + CLEARANCE, snapped to the 50-mil grid.
        """
        logger.info("Auto-placing schematic fields")
        try:
            from pathlib import Path
            from commands.pin_locator import PinLocator

            _GRID = 1.27  # 50-mil KiCad schematic grid (mm)
            def _snap(val: float) -> float:
                return round(round(val / _GRID) * _GRID, 4)

            schematic_path = params.get("schematicPath")
            references_filter = params.get("references")  # optional list of refs to limit scope
            clearance = float(params.get("clearance", _GRID))  # mm gap between ext bbox edge and field text; default one grid unit

            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}

            sch_path = Path(schematic_path)
            if not sch_path.exists():
                return {"success": False, "message": f"Schematic not found: {schematic_path}"}

            # --- helpers ---
            CHARS_PER_MM = 1.5      # conservative label extent per character
            TEXT_HEIGHT = 1.27      # mm — KiCad default font height

            def _label_bbox(lx, ly, angle, name):
                """Estimate the bounding box of a net label's text."""
                length = max(len(name), 1) * CHARS_PER_MM
                # Add a small stub/chevron allowance (≈ 1 mm)
                length += 1.0
                half_h = TEXT_HEIGHT / 2.0
                a = round(angle / 90) * 90 % 360
                if a == 0:    # extends right
                    return {"x_min": lx, "y_min": ly - half_h, "x_max": lx + length, "y_max": ly + half_h}
                elif a == 90:  # extends up (smaller Y)
                    return {"x_min": lx - half_h, "y_min": ly - length, "x_max": lx + half_h, "y_max": ly}
                elif a == 180: # extends left
                    return {"x_min": lx - length, "y_min": ly - half_h, "x_max": lx, "y_max": ly + half_h}
                else:          # 270 — extends down (larger Y)
                    return {"x_min": lx - half_h, "y_min": ly, "x_max": lx + half_h, "y_max": ly + length}

            def _union(bb, other):
                return {
                    "x_min": min(bb["x_min"], other["x_min"]),
                    "y_min": min(bb["y_min"], other["y_min"]),
                    "x_max": max(bb["x_max"], other["x_max"]),
                    "y_max": max(bb["y_max"], other["y_max"]),
                }

            def _overlaps(bb_a, bb_b, margin=0.0):
                return (bb_a["x_min"] - margin < bb_b["x_max"] and
                        bb_a["x_max"] + margin > bb_b["x_min"] and
                        bb_a["y_min"] - margin < bb_b["y_max"] and
                        bb_a["y_max"] + margin > bb_b["y_min"])

            def _field_bbox(fx, fy, text):
                half_w = max(len(str(text)), 1) * 0.75 / 2.0
                half_h = TEXT_HEIGHT / 2.0
                return {"x_min": fx - half_w, "y_min": fy - half_h,
                        "x_max": fx + half_w, "y_max": fy + half_h}

            # --- load data ---
            comp_result = self._handle_list_schematic_components({"schematicPath": schematic_path})
            if not comp_result.get("success"):
                return comp_result
            components = comp_result.get("components", [])
            if references_filter:
                components = [c for c in components if c["reference"] in references_filter]

            labels_result = self._handle_list_schematic_labels({"schematicPath": schematic_path})
            all_labels = labels_result.get("labels", []) if labels_result.get("success") else []
            # Only consider net and global labels (not power symbols)
            net_labels = [l for l in all_labels if l.get("type") in ("net", "global")]

            locator = PinLocator()

            # --- build extended bboxes ---
            comp_ext_bboxes = {}   # ref -> extended bbox (body + label extents)
            comp_body_bboxes = {}  # ref -> body bbox only (for collision avoidance)
            comp_pin_map = {}      # ref -> {pin_num: [x, y]}

            for comp in components:
                ref = comp["reference"]
                cx = comp["position"]["x"]
                cy = comp["position"]["y"]
                body_bb = comp.get("body_bbox") or {
                    "x_min": cx - 2.54, "y_min": cy - 2.54,
                    "x_max": cx + 2.54, "y_max": cy + 2.54
                }
                comp_body_bboxes[ref] = body_bb
                ext_bb = dict(body_bb)

                # Get pin positions (from cached list result if available, else locator)
                pin_list = comp.get("pins", [])
                all_pins = {}
                if pin_list:
                    for p in pin_list:
                        pnum = str(p.get("number", p.get("name", "")))
                        px = p.get("x", p.get("position", {}).get("x", cx))
                        py = p.get("y", p.get("position", {}).get("y", cy))
                        all_pins[pnum] = [float(px), float(py)]
                else:
                    all_pins = locator.get_all_symbol_pins(sch_path, ref) or {}

                comp_pin_map[ref] = all_pins

                # Expand ext_bb with each net label that sits at one of this component's pins
                for lbl in net_labels:
                    lx = lbl["position"]["x"]
                    ly = lbl["position"]["y"]
                    langle = lbl.get("angle", 0)
                    lname = lbl.get("name", "")
                    for pin_coords in all_pins.values():
                        px = pin_coords[0] if isinstance(pin_coords, (list, tuple)) else pin_coords["x"]
                        py = pin_coords[1] if isinstance(pin_coords, (list, tuple)) else pin_coords["y"]
                        if abs(lx - px) < 0.6 and abs(ly - py) < 0.6:
                            lb = _label_bbox(lx, ly, langle, lname)
                            ext_bb = _union(ext_bb, lb)
                            break

                comp_ext_bboxes[ref] = ext_bb

            # --- compute field positions ---
            updates = []
            # Track bboxes of fields already committed, so later components avoid them.
            placed_field_bboxes = []

            def _has_collision(ref_bb, val_bb, exclude_ref):
                """Return True if ref_bb or val_bb overlaps any other component extended
                bbox (body + attached labels) or any already-placed field."""
                for other_ref, other_ext in comp_ext_bboxes.items():
                    if other_ref == exclude_ref:
                        continue
                    if _overlaps(ref_bb, other_ext, 0.3) or _overlaps(val_bb, other_ext, 0.3):
                        return True
                for fb in placed_field_bboxes:
                    if _overlaps(ref_bb, fb, 0.2) or _overlaps(val_bb, fb, 0.2):
                        return True
                return False

            for comp in components:
                ref = comp["reference"]
                lib_id = comp.get("libId", "")
                # Skip internal power net symbols (hidden by design)
                if ref.startswith("#") or ref.startswith("_TEMPLATE"):
                    continue

                cx = comp["position"]["x"]
                cy = comp["position"]["y"]
                val_text = comp.get("value", ref)

                # Determine effective bounding box and pin count.
                # Power symbols have no net labels and tiny bodies — use body_bb directly.
                # Regular components use the pre-computed ext_bb (body + adjacent label extents).
                is_power = lib_id.startswith("kicad_power:") or lib_id.startswith("power:")
                if is_power:
                    pwr_body = comp.get("body_bbox") or {
                        "x_min": cx - 1.27, "y_min": cy - 1.27,
                        "x_max": cx + 1.27, "y_max": cy + 1.27
                    }
                    ext_bb = dict(pwr_body)
                    num_pins = 0  # no pin axis to consider; default to above/below
                else:
                    ext_bb = comp_ext_bboxes[ref]
                    all_pins = comp_pin_map[ref]
                    num_pins = len(all_pins)

                # Determine priority order of sides to try.
                # Both ref and val are placed on the SAME side, stacked (like KiCAD's built-in).
                # 2-pin components: prefer the axis perpendicular to the pin axis so fields
                # don't overlap the wires.  Multi-pin / power: prefer above/below.
                if num_pins == 2:
                    coords = list(all_pins.values())
                    p1x = float(coords[0][0]) if isinstance(coords[0], (list, tuple)) else float(coords[0]["x"])
                    p1y = float(coords[0][1]) if isinstance(coords[0], (list, tuple)) else float(coords[0]["y"])
                    p2x = float(coords[1][0]) if isinstance(coords[1], (list, tuple)) else float(coords[1]["x"])
                    p2y = float(coords[1][1]) if isinstance(coords[1], (list, tuple)) else float(coords[1]["y"])
                    if abs(p1y - p2y) > abs(p1x - p2x):
                        # Vertical pin axis → prefer right/left (fields beside the component)
                        sides = ["right", "left", "above", "below"]
                    else:
                        # Horizontal pin axis → prefer above/below
                        sides = ["above", "below", "right", "left"]
                else:
                    sides = ["above", "below", "right", "left"]

                # Place both fields on the same side, stacked.
                # For above/below: both centered at cx, ref closer to body, val further out.
                # For right/left: both at same x offset, stacked around cy (ref above, val below).
                def _try_side(side):
                    half_ref_h = TEXT_HEIGHT / 2.0
                    half_ref_w = max(len(ref), 1) * 0.75 / 2.0
                    half_val_w = max(len(str(val_text)), 1) * 0.75 / 2.0
                    # center-to-center distance between stacked fields
                    stack = TEXT_HEIGHT

                    if side == "above":
                        ref_x = cx
                        ref_y = _snap(ext_bb["y_min"] - half_ref_h - clearance)
                        val_x = cx
                        val_y = ref_y - stack      # exactly one stack-unit above ref
                    elif side == "below":
                        ref_x = cx
                        ref_y = _snap(ext_bb["y_max"] + half_ref_h + clearance)
                        val_x = cx
                        val_y = ref_y + stack      # exactly one stack-unit below ref
                    elif side == "right":
                        x0 = ext_bb["x_max"] + clearance
                        ref_x = _snap(x0 + half_ref_w)
                        ref_y = _snap(cy)          # snap to grid at component centre
                        val_x = _snap(x0 + half_val_w)
                        val_y = ref_y + stack      # exactly one stack-unit below (both on grid)
                    else:  # left
                        x0 = ext_bb["x_min"] - clearance
                        ref_x = _snap(x0 - half_ref_w)
                        ref_y = _snap(cy)
                        val_x = _snap(x0 - half_val_w)
                        val_y = ref_y + stack
                    return ref_x, ref_y, val_x, val_y

                # Try sides in priority order; take the first collision-free one.
                ref_x = ref_y = val_x = val_y = ref_bb = val_bb = None
                for side in sides:
                    rx, ry, vx, vy = _try_side(side)
                    rb = _field_bbox(rx, ry, ref)
                    vb = _field_bbox(vx, vy, val_text)
                    if not _has_collision(rb, vb, ref):
                        ref_x, ref_y, val_x, val_y = rx, ry, vx, vy
                        ref_bb, val_bb = rb, vb
                        break
                if ref_x is None:
                    # Fall back to preferred side even with collision
                    ref_x, ref_y, val_x, val_y = _try_side(sides[0])
                    ref_bb = _field_bbox(ref_x, ref_y, ref)
                    val_bb = _field_bbox(val_x, val_y, val_text)

                # Commit these positions — future components will avoid them.
                placed_field_bboxes.append(ref_bb)
                placed_field_bboxes.append(val_bb)

                updates.append({"reference": ref, "property": "Reference", "x": ref_x, "y": ref_y, "angle": 0})
                updates.append({"reference": ref, "property": "Value",     "x": val_x, "y": val_y, "angle": 0})

            if not updates:
                return {"success": True, "message": "No components to update.", "updated_count": 0}

            batch_result = self._handle_batch_set_schematic_property_positions({
                "schematicPath": schematic_path,
                "updates": updates,
            })

            applied = batch_result.get("applied_count", 0)
            failed = batch_result.get("failed_count", 0)
            return {
                "success": batch_result.get("success", False),
                "message": f"Auto-placed fields for {applied // 2} component(s) ({applied} fields updated{', ' + str(failed) + ' failed' if failed else ''}).",
                "updated_count": applied,
                "failed_count": failed,
                "failed": batch_result.get("failed", []),
            }

        except Exception as e:
            logger.error(f"Error in autoplace_schematic_fields: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_list_schematic_nets(self, params):
        """List all nets in a schematic with their connections"""
        logger.info("Listing schematic nets")
        try:
            from pathlib import Path
            from commands.pin_locator import PinLocator

            schematic_path = params.get("schematicPath")
            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}

            schematic = SchematicManager.load_schematic(schematic_path)
            if not schematic:
                return {"success": False, "message": "Failed to load schematic"}

            sch_path = Path(schematic_path)
            locator = PinLocator()

            # Get all net names from labels and global labels
            net_names = set()
            if hasattr(schematic, "label"):
                for label in schematic.label:
                    if hasattr(label, "value"):
                        net_names.add(label.value)
            if hasattr(schematic, "global_label"):
                for label in schematic.global_label:
                    if hasattr(label, "value"):
                        net_names.add(label.value)

            nets = []
            for net_name in sorted(net_names):
                connections = ConnectionManager.get_net_connections(
                    schematic, net_name, sch_path
                )
                # Enrich each connection with pin name and type
                for conn in connections:
                    try:
                        meta = locator.get_pin_metadata(
                            sch_path, conn["component"], str(conn["pin"])
                        )
                        conn["pinName"] = meta.get("name", str(conn["pin"]))
                        conn["pinType"] = meta.get("type", "unknown")
                    except Exception:
                        conn["pinName"] = str(conn["pin"])
                        conn["pinType"] = "unknown"
                nets.append(
                    {
                        "name": net_name,
                        "connections": connections,
                    }
                )

            return {"success": True, "nets": nets, "count": len(nets)}

        except Exception as e:
            logger.error(f"Error listing schematic nets: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_find_single_pin_nets(self, params):
        """Return all nets that have exactly one connected pin (dangling connections)."""
        logger.info("Finding single-pin nets")
        try:
            from pathlib import Path
            from commands.pin_locator import PinLocator

            schematic_path = params.get("schematicPath")
            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}

            sch_path = Path(schematic_path)
            if not sch_path.exists():
                return {"success": False, "message": f"Schematic not found: {schematic_path}"}

            schematic = SchematicManager.load_schematic(schematic_path)
            if not schematic:
                return {"success": False, "message": "Failed to load schematic"}

            net_names = set()
            for label in getattr(schematic, "label", []):
                if hasattr(label, "value"):
                    net_names.add(label.value)
            for label in getattr(schematic, "global_label", []):
                if hasattr(label, "value"):
                    net_names.add(label.value)

            locator = PinLocator()
            single_pin_nets = []
            for net_name in sorted(net_names):
                connections = ConnectionManager.get_net_connections(
                    schematic, net_name, sch_path
                )
                if len(connections) == 1:
                    conn = connections[0]
                    try:
                        meta = locator.get_pin_metadata(
                            sch_path, conn["component"], str(conn["pin"])
                        )
                        pin_name = meta.get("name", str(conn["pin"]))
                    except Exception:
                        pin_name = str(conn["pin"])
                    single_pin_nets.append({
                        "netName": net_name,
                        "component": conn["component"],
                        "pinNumber": str(conn["pin"]),
                        "pinName": pin_name,
                    })

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

    def _handle_classify_nets(self, params):
        """Classify all nets by type and return driver/load pin counts."""
        logger.info("Classifying nets")
        try:
            import re
            from pathlib import Path
            from commands.pin_locator import PinLocator
            from commands.connection_schematic import ConnectionManager as CM

            schematic_path = params.get("schematicPath")
            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}

            sch_path = Path(schematic_path)
            if not sch_path.exists():
                return {"success": False, "message": f"Schematic not found: {schematic_path}"}

            schematic = SchematicManager.load_schematic(schematic_path)
            if not schematic:
                return {"success": False, "message": "Failed to load schematic"}

            # Build full netmap and invert to net_name -> [(ref, pin_num)]
            netmap = CM.build_full_netmap(schematic, schematic_path)
            nets_to_conns = {}
            for (ref, pin_num), net_name in netmap.items():
                nets_to_conns.setdefault(net_name, []).append((ref, pin_num))

            # Also collect nets that may have labels but no matched pins
            all_net_names = set()
            for label in getattr(schematic, "label", []):
                if hasattr(label, "value"):
                    all_net_names.add(label.value)
            for label in getattr(schematic, "global_label", []):
                if hasattr(label, "value"):
                    all_net_names.add(label.value)
            # Add any nets found via netmap
            all_net_names.update(nets_to_conns.keys())

            locator = PinLocator()
            _DRIVER_TYPES = {"output", "power_out", "tri_state", "open_collector", "open_emitter"}
            _LOAD_TYPES = {"input", "passive", "power_in", "no_connect"}

            classified = []
            for net_name in sorted(all_net_names):
                conns = nets_to_conns.get(net_name, [])
                fanout = len(conns)
                driver_count = 0
                load_count = 0
                has_pwr_symbol = False

                for ref, pin_num in conns:
                    if ref.startswith("#PWR") or ref.startswith("#FLG"):
                        has_pwr_symbol = True
                        continue
                    try:
                        meta = locator.get_pin_metadata(sch_path, ref, pin_num)
                        ptype = meta.get("type", "")
                        if ptype in _DRIVER_TYPES:
                            driver_count += 1
                        elif ptype in _LOAD_TYPES:
                            load_count += 1
                    except Exception:
                        pass

                # Classify (priority order: ground > power_rail > clock > diff_pair > signal)
                net_upper = net_name.upper()
                if re.match(r'^(A?D?P?S?GND|EARTH|AGND|DGND|PGND|SGND)', net_upper):
                    net_type = "ground"
                elif (
                    has_pwr_symbol
                    or re.match(
                        r'^(\+?[\d]+V[\d]*[A-Z0-9_]*|VCC|VDD|VIN|VBAT|VREF|AVCC|DVCC|PVCC|3V3|5V|1V8|3\.3V|5\.0V)',
                        net_upper,
                    )
                ):
                    net_type = "power_rail"
                elif re.search(r'(CLK|SCK|MCLK|XTAL|OSC)', net_upper):
                    net_type = "clock"
                elif (net_name.endswith("_P") or net_name.endswith("_N")) and (
                    net_name[:-2] + "_N" in all_net_names
                    or net_name[:-2] + "_P" in all_net_names
                ):
                    net_type = "differential_pair"
                elif (net_name.endswith("+") or net_name.endswith("-")) and (
                    net_name[:-1] + "-" in all_net_names
                    or net_name[:-1] + "+" in all_net_names
                ):
                    net_type = "differential_pair"
                else:
                    net_type = "signal"

                classified.append({
                    "netName": net_name,
                    "type": net_type,
                    "fanout": fanout,
                    "driverCount": driver_count,
                    "loadCount": load_count,
                })

            return {"success": True, "nets": classified, "count": len(classified)}

        except Exception as e:
            logger.error(f"Error classifying nets: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_get_net_graph(self, params):
        """Return a compact component-to-component adjacency graph via named nets."""
        logger.info("Building net graph")
        try:
            import re
            from pathlib import Path
            from commands.pin_locator import PinLocator

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

            net_names = set()
            for label in getattr(schematic, "label", []):
                if hasattr(label, "value"):
                    net_names.add(label.value)
            for label in getattr(schematic, "global_label", []):
                if hasattr(label, "value"):
                    net_names.add(label.value)

            locator = PinLocator()
            _DRIVER_TYPES = {"output", "power_out", "tri_state", "open_collector", "open_emitter"}

            def _is_power_or_ground(name):
                n = name.upper()
                return bool(
                    re.match(r'^(A?D?P?S?GND|EARTH|AGND|DGND|PGND|SGND)', n)
                    or re.match(
                        r'^(\+?[\d]+V[\d]*[A-Z0-9_]*|VCC|VDD|VIN|VBAT|VREF|AVCC|DVCC|PVCC|3V3|5V|1V8)',
                        n,
                    )
                )

            lines = []
            for net_name in sorted(net_names):
                connections = ConnectionManager.get_net_connections(
                    schematic, net_name, sch_path
                )

                # Filter out power symbols (#PWR, #FLG)
                real_conns = [c for c in connections if not c["component"].startswith("#")]

                if skip_power and _is_power_or_ground(net_name) and len(real_conns) < 3:
                    continue

                if len(real_conns) < 2:
                    continue  # Nothing to show for isolated or single-pin nets

                # Enrich with pin names and types
                enriched = []
                for conn in real_conns:
                    try:
                        meta = locator.get_pin_metadata(
                            sch_path, conn["component"], str(conn["pin"])
                        )
                        enriched.append((
                            conn["component"],
                            meta.get("name", str(conn["pin"])),
                            meta.get("type", ""),
                        ))
                    except Exception:
                        enriched.append((conn["component"], str(conn["pin"]), ""))

                drivers = [
                    (ref, pin) for ref, pin, ptype in enriched if ptype in _DRIVER_TYPES
                ]
                non_drivers = [
                    (ref, pin) for ref, pin, ptype in enriched if ptype not in _DRIVER_TYPES
                ]

                if drivers:
                    src_ref, src_pin = drivers[0]
                    dests = ", ".join(f"{r}({p})" for r, p in non_drivers)
                    if len(drivers) > 1:
                        extra_drivers = ", ".join(f"{r}({p})" for r, p in drivers[1:])
                        dests = (extra_drivers + ", " + dests).strip(", ")
                    lines.append(f"{src_ref}({src_pin}) --[{net_name}]--> {dests}")
                else:
                    all_nodes = ", ".join(f"{r}({p})" for r, p, _ in enriched)
                    lines.append(f"[{net_name}]: {all_nodes}")

            graph_text = "\n".join(lines)
            return {"success": True, "graph": graph_text, "netCount": len(lines)}

        except Exception as e:
            logger.error(f"Error building net graph: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_get_schematic_summary(self, params):
        """Return a compact, LLM-optimised text summary of the entire schematic."""
        logger.info("Getting schematic summary")
        try:
            import re
            from pathlib import Path
            from commands.pin_locator import PinLocator
            from commands.connection_schematic import ConnectionManager as CM

            schematic_path = params.get("schematicPath")
            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}

            sch_path = Path(schematic_path)
            if not sch_path.exists():
                return {"success": False, "message": f"Schematic not found: {schematic_path}"}

            schematic = SchematicManager.load_schematic(schematic_path)
            if not schematic:
                return {"success": False, "message": "Failed to load schematic"}

            with open(sch_path, "r", encoding="utf-8") as f:
                raw_content = f.read()

            locator = PinLocator()

            # ── Components table ──────────────────────────────────────────────
            rows = []
            for symbol in schematic.symbol:
                if not hasattr(symbol.property, "Reference"):
                    continue
                ref = symbol.property.Reference.value
                if ref.startswith("_TEMPLATE") or ref.startswith("#"):
                    continue
                lib_id = symbol.lib_id.value if hasattr(symbol, "lib_id") else ""
                if lib_id.lower().startswith("power:"):
                    continue  # Skip pure power symbols from component table

                value = (
                    symbol.property.Value.value
                    if hasattr(symbol.property, "Value") else ""
                )
                footprint = (
                    symbol.property.Footprint.value
                    if hasattr(symbol.property, "Footprint") else ""
                )
                # Abbreviate footprint to just the last component
                fp_short = footprint.split(":")[-1] if footprint else "-"

                props = {}
                try:
                    block_text, _, _ = KiCADInterface._find_placed_symbol_block(
                        raw_content, ref
                    )
                    if block_text:
                        props = KiCADInterface._extract_component_properties(block_text)
                except Exception:
                    pass

                rows.append({
                    "ref": ref,
                    "value": value or "-",
                    "mpn": props.get("MPN", "-"),
                    "description": props.get("Description", "-"),
                    "footprint": fp_short,
                })

            # Sort by reference prefix then number
            def _ref_sort_key(r):
                m = re.match(r'^([A-Za-z_]+)(\d+)', r["ref"])
                return (m.group(1), int(m.group(2))) if m else (r["ref"], 0)

            rows.sort(key=_ref_sort_key)

            # ── Net adjacency list ────────────────────────────────────────────
            netmap = CM.build_full_netmap(schematic, schematic_path)
            nets_to_conns = {}
            for (ref, pin_num), net_name in netmap.items():
                nets_to_conns.setdefault(net_name, []).append((ref, pin_num))

            # Classification helper (same heuristics as classify_nets)
            all_net_names = set(nets_to_conns.keys())
            for label in getattr(schematic, "label", []):
                if hasattr(label, "value"):
                    all_net_names.add(label.value)
            for label in getattr(schematic, "global_label", []):
                if hasattr(label, "value"):
                    all_net_names.add(label.value)

            def _classify(net_name, conns):
                n = net_name.upper()
                has_pwr = any(
                    r.startswith("#PWR") or r.startswith("#FLG") for r, _ in conns
                )
                if re.match(r'^(A?D?P?S?GND|EARTH|AGND|DGND|PGND|SGND)', n):
                    return "ground"
                if has_pwr or re.match(
                    r'^(\+?[\d]+V[\d]*[A-Z0-9_]*|VCC|VDD|VIN|VBAT|VREF|AVCC|DVCC|PVCC|3V3|5V|1V8)',
                    n,
                ):
                    return "power_rail"
                if re.search(r'(CLK|SCK|MCLK|XTAL|OSC)', n):
                    return "clock"
                if (net_name.endswith("_P") or net_name.endswith("_N")) and (
                    net_name[:-2] + "_N" in all_net_names
                    or net_name[:-2] + "_P" in all_net_names
                ):
                    return "differential_pair"
                if (net_name.endswith("+") or net_name.endswith("-")) and (
                    net_name[:-1] + "-" in all_net_names
                    or net_name[:-1] + "+" in all_net_names
                ):
                    return "differential_pair"
                return "signal"

            # ── Format text output ────────────────────────────────────────────
            out = []

            # Component table
            out.append(f"=== COMPONENTS ({len(rows)}) ===")
            out.append(
                f"{'REF':<8} {'VALUE':<14} {'MPN':<22} {'DESCRIPTION':<26} FOOTPRINT"
            )
            out.append("-" * 90)
            for r in rows:
                out.append(
                    f"{r['ref']:<8} {r['value']:<14} {r['mpn']:<22} {r['description']:<26} {r['footprint']}"
                )

            # Net adjacency list
            out.append("")
            out.append(f"=== NETS ({len(all_net_names)}) ===")
            out.append(f"{'TYPE':<16} {'NAME':<22} CONNECTIONS")
            out.append("-" * 90)

            for net_name in sorted(all_net_names):
                conns = nets_to_conns.get(net_name, [])
                net_type = _classify(net_name, conns)

                conn_strs = []
                for ref, pin_num in sorted(conns):
                    if ref.startswith("#"):
                        continue
                    try:
                        meta = locator.get_pin_metadata(sch_path, ref, pin_num)
                        pin_label = meta.get("name", pin_num)
                    except Exception:
                        pin_label = pin_num
                    conn_strs.append(f"{ref}/{pin_label}")

                conn_str = ", ".join(conn_strs)
                if len(conn_str) > 64:
                    conn_str = conn_str[:61] + "..."

                out.append(f"{net_type:<16} {net_name:<22} {conn_str}")

            summary_text = "\n".join(out)
            return {"success": True, "summary": summary_text}

        except Exception as e:
            logger.error(f"Error getting schematic summary: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_list_schematic_wires(self, params):
        """List all wires in a schematic"""
        logger.info("Listing schematic wires")
        try:
            schematic_path = params.get("schematicPath")
            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}

            schematic = SchematicManager.load_schematic(schematic_path)
            if not schematic:
                return {"success": False, "message": "Failed to load schematic"}

            wires = []
            if hasattr(schematic, "wire"):
                for wire in schematic.wire:
                    if hasattr(wire, "pts") and hasattr(wire.pts, "xy"):
                        points = []
                        for point in wire.pts.xy:
                            if hasattr(point, "value"):
                                points.append(
                                    {
                                        "x": float(point.value[0]),
                                        "y": float(point.value[1]),
                                    }
                                )

                        if len(points) >= 2:
                            wires.append(
                                {
                                    "start": points[0],
                                    "end": points[-1],
                                }
                            )

            return {"success": True, "wires": wires, "count": len(wires)}

        except Exception as e:
            logger.error(f"Error listing schematic wires: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_list_schematic_labels(self, params):
        """List all net labels and power flags in a schematic"""
        logger.info("Listing schematic labels")
        try:
            schematic_path = params.get("schematicPath")
            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}
            filter_params = params.get("filter") or {}
            filter_net_name = filter_params.get("netName")
            filter_comp_ref = filter_params.get("componentRef")
            filter_bbox = filter_params.get("boundingBox")  # {x_min,y_min,x_max,y_max}

            schematic = SchematicManager.load_schematic(schematic_path)
            if not schematic:
                return {"success": False, "message": "Failed to load schematic"}

            labels = []

            # Regular labels
            if hasattr(schematic, "label"):
                for label in schematic.label:
                    if hasattr(label, "value"):
                        pos = (
                            label.at.value
                            if hasattr(label, "at") and hasattr(label.at, "value")
                            else [0, 0]
                        )
                        labels.append(
                            {
                                "name": label.value,
                                "type": "net",
                                "position": {"x": float(pos[0]), "y": float(pos[1])},
                                "angle": float(pos[2]) if len(pos) > 2 else 0,
                            }
                        )

            # Global labels
            if hasattr(schematic, "global_label"):
                for label in schematic.global_label:
                    if hasattr(label, "value"):
                        pos = (
                            label.at.value
                            if hasattr(label, "at") and hasattr(label.at, "value")
                            else [0, 0]
                        )
                        labels.append(
                            {
                                "name": label.value,
                                "type": "global",
                                "position": {"x": float(pos[0]), "y": float(pos[1])},
                                "angle": float(pos[2]) if len(pos) > 2 else 0,
                            }
                        )

            # Power symbols (components with power flag)
            # Note: [power] entries are PWR_FLAG component instances, not net labels.
            if hasattr(schematic, "symbol"):
                for symbol in schematic.symbol:
                    if not hasattr(symbol.property, "Reference"):
                        continue
                    ref = symbol.property.Reference.value
                    if ref.startswith("_TEMPLATE"):
                        continue
                    if not ref.startswith("#PWR"):
                        continue
                    value = (
                        symbol.property.Value.value
                        if hasattr(symbol.property, "Value")
                        else ref
                    )
                    pos = symbol.at.value if hasattr(symbol, "at") else [0, 0, 0]
                    labels.append(
                        {
                            "name": value,
                            "type": "power",
                            "position": {"x": float(pos[0]), "y": float(pos[1])},
                        }
                    )

            # No-connect markers — kicad-skip does not expose these, so parse with sexpdata
            try:
                import sexpdata as _sexpdata
                from sexpdata import Symbol as _Sym
                with open(schematic_path, "r", encoding="utf-8") as _f:
                    _sch_data = _sexpdata.loads(_f.read())
                for _item in _sch_data:
                    if not (isinstance(_item, list) and len(_item) > 0 and _item[0] == _Sym("no_connect")):
                        continue
                    _at = next(
                        (p for p in _item if isinstance(p, list) and len(p) >= 3 and p[0] == _Sym("at")),
                        None,
                    )
                    if _at:
                        labels.append({
                            "name": "no_connect",
                            "type": "no_connect",
                            "position": {"x": float(_at[1]), "y": float(_at[2])},
                        })
            except Exception as _e:
                logger.warning(f"Could not parse no_connect markers: {_e}")

            # Apply filters
            if filter_net_name:
                labels = [l for l in labels if l.get("name") == filter_net_name]

            if filter_bbox:
                x_min = float(filter_bbox.get("x_min", float("-inf")))
                y_min = float(filter_bbox.get("y_min", float("-inf")))
                x_max = float(filter_bbox.get("x_max", float("inf")))
                y_max = float(filter_bbox.get("y_max", float("inf")))
                labels = [
                    l for l in labels
                    if x_min <= l["position"]["x"] <= x_max
                    and y_min <= l["position"]["y"] <= y_max
                ]

            if filter_comp_ref:
                # Keep only labels near the pin tips of the specified component
                try:
                    from pathlib import Path as _Path2
                    from commands.pin_locator import PinLocator as _PL2
                    _loc2 = _PL2()
                    _comp_pins = _loc2.get_all_symbol_pins(_Path2(schematic_path), filter_comp_ref) or {}
                    _pin_tips = [
                        (float(v[0]) if isinstance(v, (list, tuple)) else float(v["x"]),
                         float(v[1]) if isinstance(v, (list, tuple)) else float(v["y"]))
                        for v in _comp_pins.values()
                    ]
                    _LABEL_TOL = 1.0  # mm — generous to catch slightly-offset labels
                    def _near_any_pin(lbl):
                        lx, ly = lbl["position"]["x"], lbl["position"]["y"]
                        return any(
                            abs(lx - px) < _LABEL_TOL and abs(ly - py) < _LABEL_TOL
                            for px, py in _pin_tips
                        )
                    labels = [l for l in labels if _near_any_pin(l)]
                except Exception as _fe:
                    logger.warning(f"componentRef filter failed: {_fe}")

            return {"success": True, "labels": labels, "count": len(labels)}

        except Exception as e:
            logger.error(f"Error listing schematic labels: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_move_schematic_component(self, params):
        """Move a schematic component to a new position, dragging net labels, Reference, and Value fields along."""
        logger.info("Moving schematic component")
        try:
            from pathlib import Path
            from commands.dynamic_symbol_loader import _snap
            from commands.pin_locator import PinLocator

            schematic_path = params.get("schematicPath")
            reference = params.get("reference")
            position = params.get("position", {})
            new_x = position.get("x")
            new_y = position.get("y")

            if not schematic_path or not reference:
                return {
                    "success": False,
                    "message": "schematicPath and reference are required",
                }
            if new_x is None or new_y is None:
                return {
                    "success": False,
                    "message": "position with x and y is required",
                }

            sch_path = Path(schematic_path)
            locator = PinLocator()

            # Capture old pin tip positions BEFORE the move
            old_pins = locator.get_all_symbol_pins(sch_path, reference) or {}

            # Capture old Reference/Value field positions BEFORE the move.
            # These are absolute coordinates in the file — they do NOT move
            # automatically when the symbol body is repositioned.
            with open(sch_path, "r", encoding="utf-8") as _f:
                _raw = _f.read()
            _block_text, _, _ = KiCADInterface._find_placed_symbol_block(_raw, reference)
            old_ref_field = KiCADInterface._extract_property_position(_block_text, "Reference") if _block_text else None
            old_val_field = KiCADInterface._extract_property_position(_block_text, "Value") if _block_text else None

            schematic = SchematicManager.load_schematic(schematic_path)
            if not schematic:
                return {"success": False, "message": "Failed to load schematic"}

            # Find the symbol
            for symbol in schematic.symbol:
                if not hasattr(symbol.property, "Reference"):
                    continue
                if symbol.property.Reference.value == reference:
                    old_pos = list(symbol.at.value)
                    old_position = {"x": float(old_pos[0]), "y": float(old_pos[1])}

                    # Snap to 50mil grid so pins land on-grid
                    snapped_x = _snap(new_x)
                    snapped_y = _snap(new_y)

                    # Preserve rotation (third element)
                    rotation = float(old_pos[2]) if len(old_pos) > 2 else 0
                    symbol.at.value = [snapped_x, snapped_y, rotation]

                    # Compute movement delta
                    delta_x = snapped_x - old_position["x"]
                    delta_y = snapped_y - old_position["y"]

                    # Drag attached net labels: find any label whose position
                    # matches an old pin tip (within 0.2mm tolerance) and move it.
                    # Safety: only drag a label if its position does NOT also coincide
                    # with a pin tip of a different component — that would indicate the
                    # label belongs to the other component, not to the one being moved.
                    TOL = 0.2

                    # Build set of pin tips from all OTHER components so we can guard
                    # against accidentally dragging their labels.
                    other_pin_tips: set = set()
                    try:
                        for _other_sym in schematic.symbol:
                            if not hasattr(_other_sym.property, "Reference"):
                                continue
                            _other_ref = _other_sym.property.Reference.value
                            if _other_ref == reference:
                                continue  # skip the component being moved
                            _other_pins = locator.get_all_symbol_pins(sch_path, _other_ref) or {}
                            for _opc in _other_pins.values():
                                _opx = float(_opc[0]) if isinstance(_opc, (list, tuple)) else float(_opc["x"])
                                _opy = float(_opc[1]) if isinstance(_opc, (list, tuple)) else float(_opc["y"])
                                other_pin_tips.add((round(_opx, 2), round(_opy, 2)))
                    except Exception as _oe:
                        logger.warning(f"Could not build other-component pin set: {_oe}")

                    labels_moved = []
                    labels_skipped = []
                    for label_collection_name in ("label", "global_label"):
                        label_collection = getattr(schematic, label_collection_name, None)
                        if not label_collection:
                            continue
                        for lbl in label_collection:
                            if not (hasattr(lbl, "at") and hasattr(lbl.at, "value")):
                                continue
                            lpos = list(lbl.at.value)
                            lx, ly = float(lpos[0]), float(lpos[1])
                            for _pin_coords in old_pins.values():
                                px = float(_pin_coords[0]) if isinstance(_pin_coords, (list, tuple)) else float(_pin_coords["x"])
                                py = float(_pin_coords[1]) if isinstance(_pin_coords, (list, tuple)) else float(_pin_coords["y"])
                                if abs(lx - px) < TOL and abs(ly - py) < TOL:
                                    # Guard: skip if this position is also a pin tip of
                                    # another component — that label belongs to them.
                                    pos_key = (round(lx, 2), round(ly, 2))
                                    if pos_key in other_pin_tips:
                                        net_name = lbl.value if hasattr(lbl, "value") else "?"
                                        labels_skipped.append({
                                            "net": net_name,
                                            "position": {"x": lx, "y": ly},
                                            "reason": "coincides with another component's pin — not dragged",
                                        })
                                        break
                                    new_lx = round(lx + delta_x, 4)
                                    new_ly = round(ly + delta_y, 4)
                                    lpos[0] = new_lx
                                    lpos[1] = new_ly
                                    lbl.at.value = lpos
                                    net_name = lbl.value if hasattr(lbl, "value") else "?"
                                    labels_moved.append({
                                        "net": net_name,
                                        "from": {"x": lx, "y": ly},
                                        "to": {"x": new_lx, "y": new_ly},
                                    })
                                    break

                    SchematicManager.save_schematic(schematic, schematic_path)

                    # Shift Reference and Value property fields by the same delta.
                    # They store absolute coordinates and are NOT moved by the skip
                    # library when the symbol body is repositioned.
                    field_updates = []
                    if old_ref_field and (delta_x != 0 or delta_y != 0):
                        field_updates.append({
                            "reference": reference,
                            "property": "Reference",
                            "x": round(old_ref_field["x"] + delta_x, 4),
                            "y": round(old_ref_field["y"] + delta_y, 4),
                            "angle": old_ref_field.get("angle", 0),
                        })
                    if old_val_field and (delta_x != 0 or delta_y != 0):
                        field_updates.append({
                            "reference": reference,
                            "property": "Value",
                            "x": round(old_val_field["x"] + delta_x, 4),
                            "y": round(old_val_field["y"] + delta_y, 4),
                            "angle": old_val_field.get("angle", 0),
                        })
                    if field_updates:
                        self._handle_batch_set_schematic_property_positions({
                            "schematicPath": schematic_path,
                            "updates": field_updates,
                        })

                    return {
                        "success": True,
                        "oldPosition": old_position,
                        "newPosition": {"x": snapped_x, "y": snapped_y},
                        "labels_moved": labels_moved,
                        "labels_skipped": labels_skipped if labels_skipped else None,
                    }

            return {"success": False, "message": f"Component {reference} not found"}

        except Exception as e:
            logger.error(f"Error moving schematic component: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_rotate_schematic_component(self, params):
        """Rotate a schematic component"""
        logger.info("Rotating schematic component")
        try:
            schematic_path = params.get("schematicPath")
            reference = params.get("reference")
            angle = params.get("angle", 0)
            mirror = params.get("mirror")

            if not schematic_path or not reference:
                return {
                    "success": False,
                    "message": "schematicPath and reference are required",
                }

            schematic = SchematicManager.load_schematic(schematic_path)
            if not schematic:
                return {"success": False, "message": "Failed to load schematic"}

            for symbol in schematic.symbol:
                if not hasattr(symbol.property, "Reference"):
                    continue
                if symbol.property.Reference.value == reference:
                    pos = list(symbol.at.value)
                    pos[2] = angle if len(pos) > 2 else angle
                    while len(pos) < 3:
                        pos.append(0)
                    pos[2] = angle
                    symbol.at.value = pos

                    # Handle mirror if specified
                    if mirror:
                        if hasattr(symbol, "mirror"):
                            symbol.mirror.value = mirror
                        else:
                            logger.warning(
                                f"Mirror '{mirror}' requested for {reference}, "
                                f"but symbol does not have a 'mirror' attribute; "
                                f"mirror not applied"
                            )

                    SchematicManager.save_schematic(schematic, schematic_path)
                    return {"success": True, "reference": reference, "angle": angle}

            return {"success": False, "message": f"Component {reference} not found"}

        except Exception as e:
            logger.error(f"Error rotating schematic component: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_add_hierarchical_sheet(self, params):
        """Insert a hierarchical sheet reference block into a parent schematic."""
        logger.info("Adding hierarchical sheet")
        try:
            import uuid as _uuid
            import re as _re

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
            # Compute relative path from parent schematic's directory to the sub-sheet
            try:
                sub_abs = Path(subsheet_path).resolve()
                rel_path = sub_abs.relative_to(parent_file.parent.resolve())
                rel_str = str(rel_path).replace("\\", "/")
            except ValueError:
                # Not relative — use as-is
                rel_str = str(subsheet_path).replace("\\", "/")

            sheet_block_uuid = str(_uuid.uuid4())

            # Property label positions: name above top-left, file below bottom-left
            name_x = round(x + 2.54, 4)
            name_y = round(y - 1.27, 4)
            file_x = round(x + 2.54, 4)
            file_y = round(y + h + 1.27, 4)

            sheet_block = f"""  (sheet (at {x} {y}) (size {w} {h}) (fields_autoplaced yes)
    (stroke (width 0.0006) (type default))
    (fill (color 0 0 0 0.0000))
    (uuid "{sheet_block_uuid}")
    (property "Sheet name" "{sheet_name}" (at {name_x} {name_y} 0)
      (effects (font (size 1.27 1.27)) (justify left bottom))
    )
    (property "Sheet file" "{rel_str}" (at {file_x} {file_y} 0)
      (effects (font (size 1.27 1.27)) (justify left bottom))
    )
  )
"""

            with open(parent_file, "r", encoding="utf-8") as f:
                content = f.read()

            # Extract the parent schematic UUID for the sheet_instances path entry
            parent_uuid_match = _re.search(r'\(uuid\s+([0-9a-fA-F-]+)\)', content)
            parent_uuid = parent_uuid_match.group(1) if parent_uuid_match else ""

            # Determine the next available page number
            existing_pages = _re.findall(r'\(page\s+"(\d+)"\)', content)
            next_page = max((int(p) for p in existing_pages), default=0) + 1

            # Build path entry for sheet_instances
            instance_path = f'/{parent_uuid}/{sheet_block_uuid}' if parent_uuid else f'/{sheet_block_uuid}'
            path_entry = f'    (path "{instance_path}" (page "{next_page}"))\n'

            # Insert sheet block before (sheet_instances
            insert_marker = "(sheet_instances"
            insert_at = content.rfind(insert_marker)
            if insert_at == -1:
                return {"success": False, "message": "Could not find (sheet_instances in schematic"}

            content = content[:insert_at] + sheet_block + "  " + content[insert_at:]

            # Insert path entry inside (sheet_instances ... ) block
            # Find the closing ) of the sheet_instances block after the insertion
            si_start = content.rfind("(sheet_instances")
            si_close = content.find(")", si_start)
            # Walk to find the matching close paren
            depth = 0
            for i in range(si_start, len(content)):
                if content[i] == "(":
                    depth += 1
                elif content[i] == ")":
                    depth -= 1
                    if depth == 0:
                        si_close = i
                        break
            content = content[:si_close] + path_entry + "  " + content[si_close:]

            with open(parent_file, "w", encoding="utf-8") as f:
                f.write(content)

            # Fix sub-sheet component instances so the hierarchical path entry
            # is present for every component (required for ERC to resolve references
            # correctly when the parent schematic is open in KiCad GUI).
            self._fix_subsheet_instances(str(parent_file), content)

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

    def _handle_create_hierarchical_subsheet(self, params):
        """Create a new sub-sheet file and link it into a parent schematic in one call.

        Combines create_schematic (sub-sheet) + add_hierarchical_sheet in a single tool,
        eliminating the 3-step workflow when building hierarchical designs.
        """
        logger.info("Creating hierarchical subsheet")
        try:
            parent_path = params.get("parentSchematicPath")
            subsheet_path = params.get("subsheetPath")
            sheet_name = params.get("sheetName", "Sheet")
            position = params.get("position", {})
            size = params.get("size", {})
            metadata = params.get("metadata", {})

            if not parent_path or not subsheet_path:
                return {"success": False, "message": "parentSchematicPath and subsheetPath are required"}

            # Step 1: create the sub-sheet schematic file
            create_result = self._handle_create_schematic({
                "filename": subsheet_path,
                "metadata": metadata,
            })
            if not create_result.get("success"):
                return {"success": False, "message": f"Failed to create sub-sheet: {create_result.get('message')}"}

            # Step 2: link the sub-sheet into the parent schematic
            link_result = self._handle_add_hierarchical_sheet({
                "schematicPath": parent_path,
                "subsheetPath": subsheet_path,
                "sheetName": sheet_name,
                "position": position,
                "size": size,
            })
            if not link_result.get("success"):
                return {"success": False,
                        "message": f"Created sub-sheet but failed to link: {link_result.get('message')}",
                        "subsheet_created": create_result.get("file_path", subsheet_path)}

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

    def _fix_subsheet_instances(self, parent_path: str, parent_content: str) -> list:
        """Walk all (sheet ...) blocks in the parent schematic and ensure each component
        in the referenced sub-sheet has an instances entry for the sheet-block UUID.

        KiCAD 8 renders references from the instances block using the SHEET-BLOCK UUID
        (the uuid inside the (sheet ...) block in the parent), NOT the sub-sheet file UUID.
        This method adds the missing path entries so ERC shows correct references.

        Returns a list of sub-sheet paths that were modified.
        """
        import sexpdata as _sx
        from sexpdata import Symbol as _Sym
        import re as _re

        modified_sheets = []

        try:
            parent_file = Path(parent_path)
            parent_data = _sx.loads(parent_content)

            # Find all (sheet ...) blocks at the top level
            for item in parent_data:
                if not (isinstance(item, list) and len(item) > 0 and item[0] == _Sym("sheet")):
                    continue

                # Extract sheet-block UUID
                sheet_block_uuid = None
                for sub in item:
                    if isinstance(sub, list) and len(sub) >= 2 and sub[0] == _Sym("uuid"):
                        sheet_block_uuid = str(sub[1])
                        break

                # Extract Sheet file property
                sheet_file_rel = None
                for sub in item:
                    if not (isinstance(sub, list) and len(sub) >= 3 and sub[0] == _Sym("property")):
                        continue
                    if sub[1] == "Sheet file":
                        sheet_file_rel = str(sub[2])
                        break

                if not sheet_block_uuid or not sheet_file_rel:
                    continue

                # Resolve sub-sheet path relative to parent
                sub_sheet_path = parent_file.parent / sheet_file_rel
                if not sub_sheet_path.exists():
                    logger.warning(f"Sub-sheet not found: {sub_sheet_path}")
                    continue

                parent_uuid_match = _re.search(r'\(uuid\s+([0-9a-fA-F-]+)\)', parent_content)
                parent_uuid = parent_uuid_match.group(1) if parent_uuid_match else ""
                target_path = f"/{parent_uuid}/{sheet_block_uuid}" if parent_uuid else f"/{sheet_block_uuid}"

                # Read the sub-sheet
                with open(sub_sheet_path, "r", encoding="utf-8") as f:
                    sub_content = f.read()

                # Get project name from parent's .kicad_pro
                try:
                    from commands.dynamic_symbol_loader import _find_project_root
                    pro_files = list(_find_project_root(parent_file.parent).glob("*.kicad_pro"))
                    project_name = pro_files[0].stem if pro_files else parent_file.stem
                except Exception:
                    project_name = parent_file.stem

                # Patch each (instances ...) block using balance-counting so this works
                # for both single-line (MCP-generated) and multi-line (KiCad-saved) files.
                def _find_balanced_end(s: str, start: int) -> int:
                    depth = 0
                    for j in range(start, len(s)):
                        if s[j] == "(":
                            depth += 1
                        elif s[j] == ")":
                            depth -= 1
                            if depth == 0:
                                return j
                    return len(s) - 1

                result_parts = []
                pos = 0
                changed = False
                while True:
                    idx = sub_content.find("(instances", pos)
                    if idx == -1:
                        result_parts.append(sub_content[pos:])
                        break
                    result_parts.append(sub_content[pos:idx])
                    end = _find_balanced_end(sub_content, idx)
                    block = sub_content[idx : end + 1]

                    if target_path not in block:
                        existing = _re.search(
                            r'\(reference\s+"([^"]+)"\)\s*\(unit\s+(\d+)\)', block
                        )
                        if existing:
                            reference = existing.group(1)
                            unit = existing.group(2)
                            new_entry = f'(path "{target_path}" (reference "{reference}") (unit {unit}))'
                            # Find the (project ...) sub-block and insert the new path entry
                            # before its closing ')'. This works for both single-line
                            # (MCP-generated) and multi-line (KiCad-saved) files, because
                            # we use balanced-paren counting rather than assuming the block
                            # ends with exactly ")) ".
                            proj_start = block.find("(project ")
                            if proj_start != -1:
                                proj_end = _find_balanced_end(block, proj_start)
                                block = block[:proj_end] + " " + new_entry + block[proj_end:]
                                changed = True
                    result_parts.append(block)
                    pos = end + 1

                if changed:
                    with open(sub_sheet_path, "w", encoding="utf-8") as f:
                        f.write("".join(result_parts))
                    modified_sheets.append(str(sub_sheet_path))
                    logger.info(f"Fixed instances in {sub_sheet_path} for sheet-block {sheet_block_uuid}")

        except Exception as e:
            logger.error(f"Error fixing sub-sheet instances: {e}")
            import traceback
            logger.error(traceback.format_exc())

        return modified_sheets

    def _handle_annotate_schematic(self, params):
        """Annotate unannotated components in schematic (R? -> R1, R2, ...)"""
        logger.info("Annotating schematic")
        try:
            import re

            schematic_path = params.get("schematicPath")
            hierarchical = params.get("hierarchical", False)
            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}

            schematic = SchematicManager.load_schematic(schematic_path)
            if not schematic:
                return {"success": False, "message": "Failed to load schematic"}

            # Collect existing references by prefix
            existing_refs = {}  # prefix -> set of numbers
            unannotated = []  # (symbol, prefix)

            for symbol in schematic.symbol:
                if not hasattr(symbol.property, "Reference"):
                    continue
                ref = symbol.property.Reference.value
                if ref.startswith("_TEMPLATE"):
                    continue

                # Split reference into prefix and number
                match = re.match(r"^([A-Za-z_]+)(\d+)$", ref)
                if match:
                    prefix = match.group(1)
                    num = int(match.group(2))
                    if prefix not in existing_refs:
                        existing_refs[prefix] = set()
                    existing_refs[prefix].add(num)
                elif ref.endswith("?"):
                    prefix = ref[:-1]
                    unannotated.append((symbol, prefix))

            annotated = []
            if unannotated:
                for symbol, prefix in unannotated:
                    if prefix not in existing_refs:
                        existing_refs[prefix] = set()

                    # Find next available number
                    next_num = 1
                    while next_num in existing_refs[prefix]:
                        next_num += 1

                    old_ref = symbol.property.Reference.value
                    new_ref = f"{prefix}{next_num}"
                    # Update both property.Reference AND instances...reference so KiCad UI
                    # reads the correct designator (KiCad 8+ authoritative source is instances).
                    if hasattr(symbol, 'setAllReferences'):
                        symbol.setAllReferences(new_ref)
                    else:
                        symbol.property.Reference.value = new_ref
                    existing_refs[prefix].add(next_num)

                    uuid_val = str(symbol.uuid.value) if hasattr(symbol, "uuid") else ""
                    annotated.append(
                        {
                            "uuid": uuid_val,
                            "oldReference": old_ref,
                            "newReference": new_ref,
                        }
                    )

                SchematicManager.save_schematic(schematic, schematic_path)

            result: dict = {"success": True, "annotated": annotated}
            if not annotated:
                result["message"] = "All components already annotated"

            # Always fix hierarchical instance paths — both for sub-sheets owned by
            # this schematic AND for any parent schematic that references this file.
            # This handles the common case where annotate is called on a sub-sheet
            # (not the parent), which would otherwise leave instances with only the
            # standalone path, causing '?' references in the parent-context ERC.
            with open(schematic_path, "r", encoding="utf-8") as _f:
                final_content = _f.read()

            # Fix sub-sheets owned by this schematic
            modified = self._fix_subsheet_instances(schematic_path, final_content)

            # Fix instances if this schematic is itself a sub-sheet of another
            sch_name = Path(schematic_path).name
            parent_dir = Path(schematic_path).parent
            for candidate in parent_dir.glob("*.kicad_sch"):
                if candidate.resolve() == Path(schematic_path).resolve():
                    continue
                try:
                    candidate_content = candidate.read_text(encoding="utf-8")
                    if sch_name in candidate_content:
                        extra = self._fix_subsheet_instances(str(candidate), candidate_content)
                        modified = modified + extra
                except Exception:
                    pass

            if modified:
                result["subSheetsFixed"] = modified

            return result

        except Exception as e:
            logger.error(f"Error annotating schematic: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_delete_schematic_wire(self, params):
        """Delete a wire from the schematic matching start/end points"""
        logger.info("Deleting schematic wire")
        try:
            schematic_path = params.get("schematicPath")
            start = params.get("start", {})
            end = params.get("end", {})

            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}

            from pathlib import Path
            from commands.wire_manager import WireManager

            start_point = [start.get("x", 0), start.get("y", 0)]
            end_point = [end.get("x", 0), end.get("y", 0)]

            deleted = WireManager.delete_wire(
                Path(schematic_path), start_point, end_point
            )
            if deleted:
                return {"success": True}
            else:
                return {"success": False, "message": "No matching wire found"}

        except Exception as e:
            logger.error(f"Error deleting schematic wire: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_delete_schematic_net_label(self, params):
        """Delete a net label (or labels) from the schematic"""
        logger.info("Deleting schematic net label")
        try:
            schematic_path = params.get("schematicPath")
            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}

            from pathlib import Path
            from commands.wire_manager import WireManager

            sch_path = Path(schematic_path)

            # Mode 1: deleteAll — remove every net label in the schematic
            if params.get("deleteAll"):
                count = WireManager.delete_all_labels(sch_path)
                return {"success": True, "deleted": count}

            # Mode 2: positions array — batch delete by (netName, optional position)
            positions_list = params.get("positions")
            if positions_list is not None:
                result = WireManager.delete_labels_batch(sch_path, positions_list)
                return {
                    "success": True,
                    "deleted": result["deleted"],
                    "notFound": result["notFound"],
                }

            # Mode 3: componentRef + pinName — resolve pin tip via PinLocator
            comp_ref = params.get("componentRef")
            pin_name = params.get("pinName")
            tolerance_mm = float(params.get("tolerance_mm", 0.5))
            if comp_ref and pin_name:
                from commands.pin_locator import PinLocator as _PL
                _loc = _PL()
                _pin_pos = _loc.get_pin_location(sch_path, comp_ref, str(pin_name))
                if not _pin_pos:
                    # Fallback: single-pin component
                    _all = _loc.get_all_symbol_pins(sch_path, comp_ref) or {}
                    if len(_all) == 1:
                        _pin_pos = next(iter(_all.values()))
                if not _pin_pos:
                    return {
                        "success": False,
                        "message": f"Could not locate pin '{pin_name}' on {comp_ref}",
                    }
                # Delete whatever label sits at this pin tip (any net name)
                try:
                    import sexpdata as _sd2
                    from sexpdata import Symbol as _Sym2
                    with open(sch_path, "r", encoding="utf-8") as _rf2:
                        _rd2 = _sd2.loads(_rf2.read())
                    deleted_count = 0
                    new_rd2 = []
                    for _item2 in _rd2:
                        if (isinstance(_item2, list) and len(_item2) > 0
                                and _item2[0] == _Sym2("label")):
                            _at2 = next(
                                (p for p in _item2[1:] if isinstance(p, list)
                                 and len(p) >= 3 and p[0] == _Sym2("at")),
                                None,
                            )
                            if _at2:
                                _lx2, _ly2 = float(_at2[1]), float(_at2[2])
                                if (abs(_lx2 - float(_pin_pos[0])) < tolerance_mm
                                        and abs(_ly2 - float(_pin_pos[1])) < tolerance_mm):
                                    deleted_count += 1
                                    continue
                        new_rd2.append(_item2)
                    if deleted_count:
                        with open(sch_path, "w", encoding="utf-8") as _wf2:
                            _wf2.write(_sd2.dumps(new_rd2))
                        return {"success": True, "deleted": deleted_count}
                    else:
                        return {
                            "success": False,
                            "message": f"No label found at pin '{pin_name}' of {comp_ref} (pos={_pin_pos})",
                        }
                except Exception as _ce:
                    return {"success": False, "message": f"componentRef delete failed: {_ce}"}

            # Mode 4: single netName (original behaviour)
            net_name = params.get("netName")
            position = params.get("position")
            if not net_name:
                return {
                    "success": False,
                    "message": "Provide netName, componentRef+pinName, deleteAll, or positions",
                }

            pos_list = None
            if position:
                pos_list = [position.get("x", 0), position.get("y", 0)]

            deleted = WireManager.delete_label(sch_path, net_name, pos_list, tolerance=tolerance_mm)
            if deleted:
                return {"success": True}
            else:
                return {"success": False, "message": f"Label '{net_name}' not found"}

        except Exception as e:
            logger.error(f"Error deleting schematic net label: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_export_schematic_svg(self, params):
        """Export schematic to SVG using kicad-cli"""
        logger.info("Exporting schematic SVG")
        import subprocess
        import glob
        import shutil

        try:
            schematic_path = params.get("schematicPath")
            output_path = params.get("outputPath")

            if not schematic_path or not output_path:
                return {
                    "success": False,
                    "message": "schematicPath and outputPath are required",
                }

            if not os.path.exists(schematic_path):
                return {
                    "success": False,
                    "message": f"Schematic not found: {schematic_path}",
                }

            # kicad-cli's --output flag for SVG export expects a directory, not a file path.
            # The output file is auto-named based on the schematic name.
            output_dir = os.path.dirname(output_path)
            if not output_dir:
                output_dir = "."

            os.makedirs(output_dir, exist_ok=True)

            cmd = [
                "kicad-cli",
                "sch",
                "export",
                "svg",
                "--no-background-color",
                schematic_path,
                "-o",
                output_dir,
            ]

            if params.get("blackAndWhite"):
                cmd.append("--black-and-white")

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

            if result.returncode != 0:
                return {
                    "success": False,
                    "message": f"kicad-cli failed: {result.stderr}",
                }

            # kicad-cli names the file after the schematic, so find the generated SVG
            svg_files = glob.glob(os.path.join(output_dir, "*.svg"))
            if not svg_files:
                return {
                    "success": False,
                    "message": "No SVG file produced by kicad-cli",
                }

            generated_svg = svg_files[0]

            # Move/rename to the user-specified output path if it differs
            if os.path.abspath(generated_svg) != os.path.abspath(output_path):
                shutil.move(generated_svg, output_path)

            return {"success": True, "file": {"path": output_path}}

        except FileNotFoundError:
            return {"success": False, "message": "kicad-cli not found in PATH"}
        except Exception as e:
            logger.error(f"Error exporting schematic SVG: {e}")
            return {"success": False, "message": str(e)}

    def _handle_get_net_connections(self, params):
        """Get all connections for a named net"""
        logger.info("Getting net connections")
        try:
            schematic_path = params.get("schematicPath")
            net_name = params.get("netName")

            if not all([schematic_path, net_name]):
                return {"success": False, "message": "Missing required parameters"}

            schematic = SchematicManager.load_schematic(schematic_path)
            if not schematic:
                return {"success": False, "message": "Failed to load schematic"}

            connections = ConnectionManager.get_net_connections(schematic, net_name)
            return {"success": True, "connections": connections}
        except Exception as e:
            logger.error(f"Error getting net connections: {str(e)}")
            return {"success": False, "message": str(e)}

    @staticmethod
    def _resolve_sym_lib_table_for_erc(schematic_path: str):
        """
        Temporarily write a resolved sym-lib-table with ${KIPRJMOD} substituted by
        the absolute project directory so kicad-cli can open project-local libraries.

        Returns a cleanup callable (call after kicad-cli finishes), or None if no
        resolution was needed.
        """
        import shutil
        from pathlib import Path

        project_dir = Path(schematic_path).parent
        sym_lib_table = project_dir / "sym-lib-table"

        if not sym_lib_table.exists():
            return None

        with open(sym_lib_table, "r", encoding="utf-8") as f:
            content = f.read()

        if "${KIPRJMOD}" not in content:
            return None

        project_abs = str(project_dir.resolve())
        resolved = content.replace("${KIPRJMOD}", project_abs)

        backup_path = sym_lib_table.with_suffix(".erc-backup")
        shutil.copy2(sym_lib_table, backup_path)
        try:
            with open(sym_lib_table, "w", encoding="utf-8") as f:
                f.write(resolved)
            logger.info(f"Wrote resolved sym-lib-table for ERC (KIPRJMOD={project_abs})")
        except Exception as e:
            logger.warning(f"Could not write resolved sym-lib-table: {e}")
            if backup_path.exists():
                backup_path.unlink()
            return None

        def cleanup():
            try:
                if backup_path.exists():
                    shutil.copy2(backup_path, sym_lib_table)
                    backup_path.unlink()
            except Exception as ex:
                logger.warning(f"Could not restore sym-lib-table backup: {ex}")

        return cleanup

    def _handle_validate_schematic(self, params):
        """Check parenthesis balance and basic structure of a .kicad_sch file without fully loading it."""
        logger.info("Validating schematic syntax")
        try:
            from pathlib import Path

            schematic_path = params.get("schematicPath")
            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}

            sch_file = Path(schematic_path)
            if not sch_file.exists():
                return {"success": False, "message": f"File not found: {schematic_path}"}

            with open(sch_file, "r", encoding="utf-8") as f:
                content = f.read()

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

    def _handle_run_erc(self, params):
        """Run Electrical Rules Check on a schematic via kicad-cli"""
        logger.info("Running ERC on schematic")
        import subprocess
        import tempfile
        import os

        try:
            schematic_path = params.get("schematicPath")
            hierarchical = params.get("hierarchical", False)

            if not schematic_path or not os.path.exists(schematic_path):
                return {
                    "success": False,
                    "message": "Schematic file not found",
                    "errorDetails": f"Path does not exist: {schematic_path}",
                }

            # Hierarchical mode: run ERC on every .kicad_sch in the project directory
            if hierarchical:
                from pathlib import Path as _Path
                _proj_dir = _Path(schematic_path).parent
                _sch_files = sorted(_proj_dir.glob("*.kicad_sch"))
                _all_violations_by_sheet = {}
                _all_notes = []
                _total_violations = 0
                _total_actionable = 0
                _total_benign = 0
                _severity_counts = {"error": 0, "warning": 0, "info": 0}
                for _sch_file in _sch_files:
                    _sheet_result = self._handle_run_erc({
                        "schematicPath": str(_sch_file),
                        "hierarchical": False,
                    })
                    _fname = _sch_file.name
                    if _sheet_result.get("success"):
                        _sheet_violations = _sheet_result.get("violations", [])
                        for _v in _sheet_violations:
                            _v["sheet"] = _fname
                        _all_violations_by_sheet[_fname] = _sheet_violations
                        _total_violations += len(_sheet_violations)
                        _s = _sheet_result.get("summary", {})
                        _total_actionable += _s.get("actionable", 0)
                        _total_benign += _s.get("benign", 0)
                        for _sev, _cnt in _s.get("by_severity", {}).items():
                            _severity_counts[_sev] = _severity_counts.get(_sev, 0) + _cnt
                        for _note in _sheet_result.get("notes", []):
                            if _note not in _all_notes:
                                _all_notes.append(_note)
                    else:
                        _all_violations_by_sheet[_fname] = [{"error": _sheet_result.get("message")}]
                _all_violations_flat = [
                    v for vs in _all_violations_by_sheet.values() for v in vs
                ]
                return {
                    "success": True,
                    "message": f"Hierarchical ERC complete: {_total_violations} violation(s) across {len(_sch_files)} sheet(s)",
                    "coordinate_units": "mm",
                    "notes": _all_notes,
                    "sheets_checked": [f.name for f in _sch_files],
                    "violations_by_sheet": _all_violations_by_sheet,
                    "violations": _all_violations_flat,
                    "summary": {
                        "total": _total_violations,
                        "actionable": _total_actionable,
                        "benign": _total_benign,
                        "by_severity": _severity_counts,
                    },
                }

            kicad_cli = self.design_rule_commands._find_kicad_cli()
            if not kicad_cli:
                return {
                    "success": False,
                    "message": "kicad-cli not found",
                    "errorDetails": "Install KiCAD 8.0+ or add kicad-cli to PATH.",
                }

            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=False
            ) as tmp:
                json_output = tmp.name

            # Pre-resolve ${KIPRJMOD} in the project sym-lib-table so kicad-cli
            # can open project-local libraries that use relative paths.
            erc_cleanup = self._resolve_sym_lib_table_for_erc(schematic_path)

            # kicad-cli determines the project by finding a .kicad_pro file with
            # the same basename as the input schematic. Sub-sheets don't have their
            # own .kicad_pro, so kicad-cli falls back to the global library tables
            # (which may resolve to wrong paths) and produces spurious warnings.
            # Fix: temporarily symlink the parent .kicad_pro using the sub-sheet's
            # basename so kicad-cli loads the correct project library tables.
            from pathlib import Path
            sch_path_obj = Path(schematic_path)
            project_dir = sch_path_obj.parent
            expected_pro = sch_path_obj.with_suffix(".kicad_pro")
            tmp_pro_symlink = None
            if not expected_pro.exists():
                existing_pros = list(project_dir.glob("*.kicad_pro"))
                if existing_pros:
                    tmp_pro_symlink = expected_pro
                    try:
                        tmp_pro_symlink.symlink_to(existing_pros[0].name)
                        logger.info(
                            f"Created temporary project symlink {tmp_pro_symlink.name} -> {existing_pros[0].name}"
                        )
                    except Exception as _sym_err:
                        logger.warning(f"Could not create project symlink: {_sym_err}")
                        tmp_pro_symlink = None

            try:
                cmd = [
                    kicad_cli,
                    "sch",
                    "erc",
                    "--format",
                    "json",
                    "--output",
                    json_output,
                    schematic_path,
                ]
                logger.info(f"Running ERC command: {' '.join(cmd)}")

                result = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=120
                )

                if result.returncode != 0:
                    logger.error(f"ERC command failed: {result.stderr}")
                    return {
                        "success": False,
                        "message": "ERC command failed",
                        "errorDetails": result.stderr,
                    }

                with open(json_output, "r", encoding="utf-8") as f:
                    erc_data = json.load(f)

                violations = []
                severity_counts = {"error": 0, "warning": 0, "info": 0}

                # BUG-3 fix: only suppress lib_symbol_issues for truly unresolvable
                # global libraries. footprint_link_issues ("footprint library" /
                # "footprint not found") are actionable and must NOT be filtered.
                BENIGN_PATTERNS = [
                    "symbol not found in global library",
                    "not found in global",
                ]
                BENIGN_TYPES: set = set()

                def _is_benign_violation(v):
                    if v.get("type", "") in BENIGN_TYPES:
                        return True
                    desc = v.get("message", "").lower()
                    return any(pat in desc for pat in BENIGN_PATTERNS)

                all_violations = []
                sheets_checked = []
                for sheet in erc_data.get("sheets", []):
                    all_violations.extend(sheet.get("violations", []))
                    fname = sheet.get("filename") or sheet.get("source") or ""
                    if fname:
                        sheets_checked.append(os.path.basename(fname))

                for v in all_violations:
                    vseverity = v.get("severity", "error")
                    items = v.get("items", [])
                    loc = {}
                    items_detail = []
                    for item in items:
                        item_info = {}
                        if "pos" in item:
                            # kicad-cli ERC JSON outputs positions in 1/100 mm
                            # (KiCad internal schematic units). Multiply by 100
                            # to convert to mm.
                            item_info["pos"] = {
                                "x": item["pos"].get("x", 0) * 100,
                                "y": item["pos"].get("y", 0) * 100,
                            }
                        if "description" in item:
                            item_info["description"] = item["description"]
                        if "uuid" in item:
                            item_info["uuid"] = item["uuid"]
                        items_detail.append(item_info)
                    if items_detail and "pos" in items_detail[0]:
                        loc = items_detail[0]["pos"]
                    violation_dict = {
                        "type": v.get("type", "unknown"),
                        "severity": vseverity,
                        "message": v.get("description", ""),
                        "items": items_detail,
                        "location": loc,
                    }
                    violation_dict["benign"] = _is_benign_violation(violation_dict)
                    violations.append(violation_dict)
                    if vseverity in severity_counts:
                        severity_counts[vseverity] += 1

                notes = [
                    "All coordinates are in millimeters (mm).",
                    "ERC reads the saved file on disk. If the schematic is open in KiCad UI with unsaved changes, reload it in KiCad to sync before comparing results.",
                ]
                if any(v["type"] == "lib_symbol_issues" for v in violations):
                    notes.append(
                        "lib_symbol_issues can be false-positives if project .kicad_sym "
                        "files contain ; lines with (, ), or [ characters. KiCAD's "
                        "s-expression parser treats ; lines as data, not comments — "
                        "such lines corrupt the parse tree. Remove ; lines from the "
                        "affected library files to resolve."
                    )

                # Build PWR_FLAG suggestions for pin_not_driven violations.
                # Each undriven power pin needs a PWR_FLAG placed at its coordinate
                # on the same net.  The ERC violation items contain the pin position.
                pwr_flag_suggestions = []
                try:
                    _seen_pwr_nets: set = set()
                    for v in violations:
                        if v.get("type") != "pin_not_driven":
                            continue
                        msg = v.get("message", "")
                        loc = v.get("location", {})
                        if not loc:
                            continue
                        # Extract net name from violation message (KiCAD format:
                        # "Pin ... of ... is not driven" — net name appears in items)
                        net_name = None
                        for item in v.get("items", []):
                            desc = item.get("description", "")
                            # Typical desc: "Pin ~ of PWR_FLAG, net VBUS"
                            import re as _re2
                            m = _re2.search(r'\bnet\s+(\S+)', desc, _re2.IGNORECASE)
                            if m:
                                net_name = m.group(1).rstrip(".,;")
                                break
                        if not net_name:
                            # Fallback: parse from violation message
                            m = _re2.search(r'net\s+["\']?(\S+?)["\']?[\s,.]', msg, _re2.IGNORECASE)
                            net_name = m.group(1) if m else f"net_at_{loc.get('x',0):.1f}_{loc.get('y',0):.1f}"

                        if net_name in _seen_pwr_nets:
                            continue
                        _seen_pwr_nets.add(net_name)
                        pwr_flag_suggestions.append({
                            "net": net_name,
                            "suggested_position": {"x": loc.get("x", 0), "y": loc.get("y", 0)},
                            "action": (
                                f"Place a PWR_FLAG (power:PWR_FLAG) near ({loc.get('x',0):.2f}, {loc.get('y',0):.2f}) "
                                f"and connect it to net '{net_name}' using batch_add_and_connect or batch_add_components + batch_connect"
                            ),
                        })
                except Exception as _pwr_err:
                    logger.warning(f"PWR_FLAG suggestion generation failed: {_pwr_err}")

                result_dict = {
                    "success": True,
                    "message": f"ERC complete: {len(violations)} violation(s)",
                    "coordinate_units": "mm",
                    "notes": notes,
                    "sheets_checked": sheets_checked,
                    "summary": {
                        "total": len(violations),
                        "actionable": sum(1 for v in violations if not v.get("benign")),
                        "benign": sum(1 for v in violations if v.get("benign")),
                        "by_severity": severity_counts,
                    },
                    "violations": violations,
                }
                if pwr_flag_suggestions:
                    result_dict["pwr_flag_suggestions"] = pwr_flag_suggestions
                return result_dict

            finally:
                if os.path.exists(json_output):
                    os.unlink(json_output)
                if erc_cleanup:
                    erc_cleanup()
                if tmp_pro_symlink is not None and tmp_pro_symlink.is_symlink():
                    try:
                        tmp_pro_symlink.unlink()
                        logger.info(f"Removed temporary project symlink {tmp_pro_symlink.name}")
                    except Exception as _del_err:
                        logger.warning(f"Could not remove project symlink: {_del_err}")

        except subprocess.TimeoutExpired:
            return {"success": False, "message": "ERC timed out after 120 seconds"}
        except Exception as e:
            logger.error(f"Error running ERC: {str(e)}")
            return {"success": False, "message": str(e)}

    def _handle_generate_netlist(self, params):
        """Generate netlist from schematic"""
        logger.info("Generating netlist from schematic")
        try:
            schematic_path = params.get("schematicPath")

            if not schematic_path:
                return {"success": False, "message": "Schematic path is required"}

            schematic = SchematicManager.load_schematic(schematic_path)
            if not schematic:
                return {"success": False, "message": "Failed to load schematic"}

            netlist = ConnectionManager.generate_netlist(
                schematic, schematic_path=schematic_path
            )
            return {"success": True, "netlist": netlist}
        except Exception as e:
            logger.error(f"Error generating netlist: {str(e)}")
            return {"success": False, "message": str(e)}

    def _handle_sync_schematic_to_board(self, params):
        """Sync schematic netlist to PCB board (equivalent to KiCAD F8 'Update PCB from Schematic').
        Reads net connections from the schematic and assigns them to the matching pads in the PCB.
        """
        logger.info("Syncing schematic to board")
        try:
            from pathlib import Path

            schematic_path = params.get("schematicPath")
            board_path = params.get("boardPath")

            # Determine board to work with
            board = None
            if board_path:
                board = pcbnew.LoadBoard(board_path)
            elif self.board:
                board = self.board
                board_path = board.GetFileName() if not board_path else board_path
            else:
                return {
                    "success": False,
                    "message": "No board loaded. Use open_project first or provide boardPath.",
                }

            if not board_path:
                board_path = board.GetFileName()

            # Determine schematic path if not provided
            if not schematic_path:
                sch = Path(board_path).with_suffix(".kicad_sch")
                if sch.exists():
                    schematic_path = str(sch)
                else:
                    project_dir = Path(board_path).parent
                    sch_files = list(project_dir.glob("*.kicad_sch"))
                    if sch_files:
                        schematic_path = str(sch_files[0])

            if not schematic_path or not Path(schematic_path).exists():
                return {
                    "success": False,
                    "message": f"Schematic not found. Provide schematicPath. Tried: {schematic_path}",
                }

            # Generate netlist from schematic
            schematic = SchematicManager.load_schematic(schematic_path)
            if not schematic:
                return {"success": False, "message": "Failed to load schematic"}

            netlist = ConnectionManager.generate_netlist(
                schematic, schematic_path=schematic_path
            )

            # Build (reference, pad_number) -> net_name map
            pad_net_map = {}  # {(ref, pin_str): net_name}
            net_names = set()
            for net_entry in netlist.get("nets", []):
                net_name = net_entry["name"]
                net_names.add(net_name)
                for conn in net_entry.get("connections", []):
                    ref = conn.get("component", "")
                    pin = str(conn.get("pin", ""))
                    if ref and pin and pin != "unknown":
                        pad_net_map[(ref, pin)] = net_name

            # Add all nets to board
            netinfo = board.GetNetInfo()
            nets_by_name = netinfo.NetsByName()
            added_nets = []
            for net_name in net_names:
                if not nets_by_name.has_key(net_name):
                    net_item = pcbnew.NETINFO_ITEM(board, net_name)
                    board.Add(net_item)
                    added_nets.append(net_name)

            # Refresh nets map after additions
            netinfo = board.GetNetInfo()
            nets_by_name = netinfo.NetsByName()

            # Assign nets to pads
            assigned_pads = 0
            unmatched = []
            for fp in board.GetFootprints():
                ref = fp.GetReference()
                for pad in fp.Pads():
                    pad_num = pad.GetNumber()
                    key = (ref, str(pad_num))
                    if key in pad_net_map:
                        net_name = pad_net_map[key]
                        if nets_by_name.has_key(net_name):
                            pad.SetNet(nets_by_name[net_name])
                            assigned_pads += 1
                    else:
                        unmatched.append(f"{ref}/{pad_num}")

            board.Save(board_path)

            # If board was loaded fresh, update internal reference
            if params.get("boardPath"):
                self.board = board
                self._update_command_handlers()

            logger.info(
                f"sync_schematic_to_board: {len(added_nets)} nets added, {assigned_pads} pads assigned"
            )
            return {
                "success": True,
                "message": f"PCB nets synced from schematic: {len(added_nets)} nets added, {assigned_pads} pads assigned",
                "nets_added": added_nets,
                "nets_total": len(net_names),
                "pads_assigned": assigned_pads,
                "unmatched_pads_sample": unmatched[:10],
            }

        except Exception as e:
            logger.error(f"Error in sync_schematic_to_board: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_import_svg_logo(self, params):
        """Import an SVG file as PCB graphic polygons on the silkscreen"""
        logger.info("Importing SVG logo into PCB")
        try:
            from commands.svg_import import import_svg_to_pcb

            pcb_path = params.get("pcbPath")
            svg_path = params.get("svgPath")
            x = float(params.get("x", 0))
            y = float(params.get("y", 0))
            width = float(params.get("width", 10))
            layer = params.get("layer", "F.SilkS")
            stroke_width = float(params.get("strokeWidth", 0))
            filled = bool(params.get("filled", True))

            if not pcb_path or not svg_path:
                return {
                    "success": False,
                    "message": "Missing required parameters: pcbPath, svgPath",
                }

            result = import_svg_to_pcb(
                pcb_path, svg_path, x, y, width, layer, stroke_width, filled
            )

            # import_svg_to_pcb writes gr_poly entries directly to the .kicad_pcb file,
            # bypassing the pcbnew in-memory board object.  Any subsequent board.Save()
            # call would overwrite the file with the stale in-memory state, erasing the
            # logo.  Reload the board from disk so pcbnew's memory matches the file.
            if result.get("success") and self.board:
                try:
                    self.board = pcbnew.LoadBoard(pcb_path)
                    # Propagate updated board reference to all command handlers
                    self._update_command_handlers()
                    logger.info("Reloaded board into pcbnew after SVG logo import")
                except Exception as reload_err:
                    logger.warning(
                        f"Board reload after SVG import failed (non-fatal): {reload_err}"
                    )

            return result

        except Exception as e:
            logger.error(f"Error importing SVG logo: {str(e)}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_snapshot_project(self, params):
        """Copy the entire project folder to a snapshot directory for checkpoint/resume."""
        import shutil
        from datetime import datetime
        from pathlib import Path

        try:
            step = params.get("step", "")
            label = params.get("label", "")
            prompt_text = params.get("prompt", "")
            # Determine project directory from loaded board or explicit path
            project_dir = None
            if self.board:
                board_file = self.board.GetFileName()
                if board_file:
                    project_dir = str(Path(board_file).parent)
            if not project_dir:
                project_dir = params.get("projectPath")
            if not project_dir or not os.path.isdir(project_dir):
                return {
                    "success": False,
                    "message": "Could not determine project directory for snapshot",
                }

            ts = datetime.now().strftime("%Y%m%d_%H%M%S")

            # Save prompt + log into logs/ subdirectory before snapshotting
            logs_dir = Path(project_dir) / "logs"
            logs_dir.mkdir(exist_ok=True)

            prompt_file = None
            if prompt_text:
                prompt_filename = (
                    f"PROMPT_step{step}_{ts}.md" if step else f"PROMPT_{ts}.md"
                )
                prompt_file = logs_dir / prompt_filename
                prompt_file.write_text(prompt_text, encoding="utf-8")
                logger.info(f"Prompt saved: {prompt_file}")

            # Copy current MCP session log into logs/ before snapshotting
            import platform

            system = platform.system()
            if system == "Windows":
                mcp_log_dir = os.path.join(
                    os.environ.get("APPDATA", ""), "Claude", "logs"
                )
            elif system == "Darwin":
                mcp_log_dir = os.path.expanduser("~/Library/Logs/Claude")
            else:
                mcp_log_dir = os.path.expanduser("~/.config/Claude/logs")
            mcp_log_src = os.path.join(mcp_log_dir, "mcp-server-kicad.log")
            mcp_log_dest = None
            if os.path.exists(mcp_log_src):
                with open(mcp_log_src, "r", encoding="utf-8", errors="replace") as f:
                    all_lines = f.readlines()
                session_start = 0
                for i, line in enumerate(all_lines):
                    if "Initializing server" in line:
                        session_start = i
                session_lines = all_lines[session_start:]
                log_filename = (
                    f"mcp_log_step{step}_{ts}.txt" if step else f"mcp_log_{ts}.txt"
                )
                mcp_log_dest = logs_dir / log_filename
                with open(mcp_log_dest, "w", encoding="utf-8") as f:
                    f.writelines(session_lines)
                logger.info(
                    f"MCP session log saved: {mcp_log_dest} ({len(session_lines)} lines)"
                )

            base_name = Path(project_dir).name
            suffix_parts = [p for p in [f"step{step}" if step else "", label, ts] if p]
            snapshot_name = base_name + "_snapshot_" + "_".join(suffix_parts)
            snapshots_base = Path(project_dir) / "snapshots"
            snapshots_base.mkdir(exist_ok=True)
            snapshot_dir = str(snapshots_base / snapshot_name)

            shutil.copytree(
                project_dir, snapshot_dir, ignore=shutil.ignore_patterns("snapshots")
            )
            logger.info(f"Project snapshot saved: {snapshot_dir}")
            return {
                "success": True,
                "message": f"Snapshot saved: {snapshot_name}",
                "snapshotPath": snapshot_dir,
                "sourceDir": project_dir,
                "promptSaved": str(prompt_file) if prompt_file else None,
                "mcpLogSaved": str(mcp_log_dest) if mcp_log_dest else None,
            }
        except Exception as e:
            logger.error(f"snapshot_project error: {e}")
            return {"success": False, "message": str(e)}

    def _handle_check_kicad_ui(self, params):
        """Check if KiCAD UI is running"""
        logger.info("Checking if KiCAD UI is running")
        try:
            manager = KiCADProcessManager()
            is_running = manager.is_running()
            processes = manager.get_process_info() if is_running else []

            return {
                "success": True,
                "running": is_running,
                "processes": processes,
                "message": "KiCAD is running" if is_running else "KiCAD is not running",
            }
        except Exception as e:
            logger.error(f"Error checking KiCAD UI status: {str(e)}")
            return {"success": False, "message": str(e)}

    def _handle_launch_kicad_ui(self, params):
        """Launch KiCAD UI"""
        logger.info("Launching KiCAD UI")
        try:
            project_path = params.get("projectPath")
            auto_launch = params.get("autoLaunch", AUTO_LAUNCH_KICAD)

            # Convert project path to Path object if provided
            from pathlib import Path

            path_obj = Path(project_path) if project_path else None

            result = check_and_launch_kicad(path_obj, auto_launch)

            return {"success": True, **result}
        except Exception as e:
            logger.error(f"Error launching KiCAD UI: {str(e)}")
            return {"success": False, "message": str(e)}

    def _handle_refill_zones(self, params):
        """Refill all copper pour zones on the board.

        pcbnew.ZONE_FILLER.Fill() can cause a C++ access violation (0xC0000005)
        that crashes the entire Python process when called from SWIG outside KiCAD UI.
        To avoid killing the main process we run the fill in an isolated subprocess.
        If the subprocess crashes or times out, we return a non-fatal warning so the
        caller can continue — KiCAD Pcbnew will refill zones automatically when the
        board is opened (press B).
        """
        logger.info("Refilling zones (subprocess isolation)")
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            # First save the board so the subprocess can load it fresh
            board_path = self.board.GetFileName()
            if not board_path:
                return {
                    "success": False,
                    "message": "Board has no file path — save first",
                }
            self.board.Save(board_path)

            zone_count = (
                self.board.GetAreaCount() if hasattr(self.board, "GetAreaCount") else 0
            )

            # Run pcbnew zone fill in an isolated subprocess to prevent crashes
            import subprocess, sys, textwrap

            script = textwrap.dedent(f"""
import pcbnew, sys
board = pcbnew.LoadBoard({repr(board_path)})
filler = pcbnew.ZONE_FILLER(board)
filler.Fill(board.Zones())
board.Save({repr(board_path)})
print("ok")
""")
            try:
                result = subprocess.run(
                    [sys.executable, "-c", script],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                if result.returncode == 0 and "ok" in result.stdout:
                    # Reload board after subprocess modified it
                    self.board = pcbnew.LoadBoard(board_path)
                    self._update_command_handlers()
                    logger.info("Zone fill subprocess succeeded")
                    return {
                        "success": True,
                        "message": f"Zones refilled successfully ({zone_count} zones)",
                        "zoneCount": zone_count,
                    }
                else:
                    logger.warning(
                        f"Zone fill subprocess failed: rc={result.returncode} stderr={result.stderr[:200]}"
                    )
                    return {
                        "success": False,
                        "message": "Zone fill failed in subprocess — zones are defined and will fill when opened in KiCAD (press B). Continuing is safe.",
                        "zoneCount": zone_count,
                        "details": (
                            result.stderr[:300]
                            if result.stderr
                            else result.stdout[:300]
                        ),
                    }
            except subprocess.TimeoutExpired:
                logger.warning("Zone fill subprocess timed out after 60s")
                return {
                    "success": False,
                    "message": "Zone fill timed out — zones are defined and will fill when opened in KiCAD (press B). Continuing is safe.",
                    "zoneCount": zone_count,
                }

        except Exception as e:
            logger.error(f"Error refilling zones: {str(e)}")
            return {"success": False, "message": str(e)}

    # =========================================================================
    # IPC Backend handlers - these provide real-time UI synchronization
    # These methods are called automatically when IPC is available
    # =========================================================================

    def _ipc_route_trace(self, params):
        """IPC handler for route_trace - adds track with real-time UI update"""
        try:
            # Extract parameters matching the existing route_trace interface
            start = params.get("start", {})
            end = params.get("end", {})
            layer = params.get("layer", "F.Cu")
            width = params.get("width", 0.25)
            net = params.get("net")

            # Handle both dict format and direct x/y
            start_x = (
                start.get("x", 0)
                if isinstance(start, dict)
                else params.get("startX", 0)
            )
            start_y = (
                start.get("y", 0)
                if isinstance(start, dict)
                else params.get("startY", 0)
            )
            end_x = end.get("x", 0) if isinstance(end, dict) else params.get("endX", 0)
            end_y = end.get("y", 0) if isinstance(end, dict) else params.get("endY", 0)

            success = self.ipc_board_api.add_track(
                start_x=start_x,
                start_y=start_y,
                end_x=end_x,
                end_y=end_y,
                width=width,
                layer=layer,
                net_name=net,
            )

            return {
                "success": success,
                "message": (
                    "Added trace (visible in KiCAD UI)"
                    if success
                    else "Failed to add trace"
                ),
                "trace": {
                    "start": {"x": start_x, "y": start_y, "unit": "mm"},
                    "end": {"x": end_x, "y": end_y, "unit": "mm"},
                    "layer": layer,
                    "width": width,
                    "net": net,
                },
            }
        except Exception as e:
            logger.error(f"IPC route_trace error: {e}")
            return {"success": False, "message": str(e)}

    def _ipc_add_via(self, params):
        """IPC handler for add_via - adds via with real-time UI update"""
        try:
            position = params.get("position", {})
            x = (
                position.get("x", 0)
                if isinstance(position, dict)
                else params.get("x", 0)
            )
            y = (
                position.get("y", 0)
                if isinstance(position, dict)
                else params.get("y", 0)
            )

            size = params.get("size", 0.8)
            drill = params.get("drill", 0.4)
            net = params.get("net")
            from_layer = params.get("from_layer", "F.Cu")
            to_layer = params.get("to_layer", "B.Cu")

            success = self.ipc_board_api.add_via(
                x=x, y=y, diameter=size, drill=drill, net_name=net, via_type="through"
            )

            return {
                "success": success,
                "message": (
                    "Added via (visible in KiCAD UI)"
                    if success
                    else "Failed to add via"
                ),
                "via": {
                    "position": {"x": x, "y": y, "unit": "mm"},
                    "size": size,
                    "drill": drill,
                    "from_layer": from_layer,
                    "to_layer": to_layer,
                    "net": net,
                },
            }
        except Exception as e:
            logger.error(f"IPC add_via error: {e}")
            return {"success": False, "message": str(e)}

    def _ipc_add_net(self, params):
        """IPC handler for add_net"""
        # Note: Net creation via IPC is limited - nets are typically created
        # when components are placed. Return success for compatibility.
        name = params.get("name")
        logger.info(f"IPC add_net: {name} (nets auto-created with components)")
        return {
            "success": True,
            "message": f"Net '{name}' will be created when components are connected",
            "net": {"name": name},
        }

    def _ipc_add_copper_pour(self, params):
        """IPC handler for add_copper_pour - adds zone with real-time UI update"""
        try:
            layer = params.get("layer", "F.Cu")
            net = params.get("net")
            clearance = params.get("clearance", 0.5)
            min_width = params.get("minWidth", 0.25)
            points = params.get("points", [])
            priority = params.get("priority", 0)
            fill_type = params.get("fillType", "solid")
            name = params.get("name", "")

            if not points or len(points) < 3:
                return {
                    "success": False,
                    "message": "At least 3 points are required for copper pour outline",
                }

            # Convert points format if needed (handle both {x, y} and {x, y, unit})
            formatted_points = []
            for point in points:
                formatted_points.append(
                    {"x": point.get("x", 0), "y": point.get("y", 0)}
                )

            success = self.ipc_board_api.add_zone(
                points=formatted_points,
                layer=layer,
                net_name=net,
                clearance=clearance,
                min_thickness=min_width,
                priority=priority,
                fill_mode=fill_type,
                name=name,
            )

            return {
                "success": success,
                "message": (
                    "Added copper pour (visible in KiCAD UI)"
                    if success
                    else "Failed to add copper pour"
                ),
                "pour": {
                    "layer": layer,
                    "net": net,
                    "clearance": clearance,
                    "minWidth": min_width,
                    "priority": priority,
                    "fillType": fill_type,
                    "pointCount": len(points),
                },
            }
        except Exception as e:
            logger.error(f"IPC add_copper_pour error: {e}")
            return {"success": False, "message": str(e)}

    def _ipc_refill_zones(self, params):
        """IPC handler for refill_zones - refills all zones with real-time UI update"""
        try:
            success = self.ipc_board_api.refill_zones()

            return {
                "success": success,
                "message": (
                    "Zones refilled (visible in KiCAD UI)"
                    if success
                    else "Failed to refill zones"
                ),
            }
        except Exception as e:
            logger.error(f"IPC refill_zones error: {e}")
            return {"success": False, "message": str(e)}

    def _ipc_add_text(self, params):
        """IPC handler for add_text/add_board_text - adds text with real-time UI update"""
        try:
            text = params.get("text", "")
            position = params.get("position", {})
            x = (
                position.get("x", 0)
                if isinstance(position, dict)
                else params.get("x", 0)
            )
            y = (
                position.get("y", 0)
                if isinstance(position, dict)
                else params.get("y", 0)
            )
            layer = params.get("layer", "F.SilkS")
            size = params.get("size", 1.0)
            rotation = params.get("rotation", 0)

            success = self.ipc_board_api.add_text(
                text=text, x=x, y=y, layer=layer, size=size, rotation=rotation
            )

            return {
                "success": success,
                "message": (
                    f"Added text '{text}' (visible in KiCAD UI)"
                    if success
                    else "Failed to add text"
                ),
            }
        except Exception as e:
            logger.error(f"IPC add_text error: {e}")
            return {"success": False, "message": str(e)}

    def _ipc_set_board_size(self, params):
        """IPC handler for set_board_size"""
        try:
            width = params.get("width", 100)
            height = params.get("height", 100)
            unit = params.get("unit", "mm")

            success = self.ipc_board_api.set_size(width, height, unit)

            return {
                "success": success,
                "message": (
                    f"Board size set to {width}x{height} {unit} (visible in KiCAD UI)"
                    if success
                    else "Failed to set board size"
                ),
                "boardSize": {"width": width, "height": height, "unit": unit},
            }
        except Exception as e:
            logger.error(f"IPC set_board_size error: {e}")
            return {"success": False, "message": str(e)}

    def _ipc_get_board_info(self, params):
        """IPC handler for get_board_info"""
        try:
            size = self.ipc_board_api.get_size()
            components = self.ipc_board_api.list_components()
            tracks = self.ipc_board_api.get_tracks()
            vias = self.ipc_board_api.get_vias()
            nets = self.ipc_board_api.get_nets()

            return {
                "success": True,
                "boardInfo": {
                    "size": size,
                    "componentCount": len(components),
                    "trackCount": len(tracks),
                    "viaCount": len(vias),
                    "netCount": len(nets),
                    "backend": "ipc",
                    "realtime": True,
                },
            }
        except Exception as e:
            logger.error(f"IPC get_board_info error: {e}")
            return {"success": False, "message": str(e)}

    def _ipc_place_component(self, params):
        """IPC handler for place_component - places component with real-time UI update"""
        try:
            reference = params.get("reference", params.get("componentId", ""))
            footprint = params.get("footprint", "")
            position = params.get("position", {})
            x = (
                position.get("x", 0)
                if isinstance(position, dict)
                else params.get("x", 0)
            )
            y = (
                position.get("y", 0)
                if isinstance(position, dict)
                else params.get("y", 0)
            )
            rotation = params.get("rotation", 0)
            layer = params.get("layer", "F.Cu")
            value = params.get("value", "")

            success = self.ipc_board_api.place_component(
                reference=reference,
                footprint=footprint,
                x=x,
                y=y,
                rotation=rotation,
                layer=layer,
                value=value,
            )

            return {
                "success": success,
                "message": (
                    f"Placed component {reference} (visible in KiCAD UI)"
                    if success
                    else "Failed to place component"
                ),
                "component": {
                    "reference": reference,
                    "footprint": footprint,
                    "position": {"x": x, "y": y, "unit": "mm"},
                    "rotation": rotation,
                    "layer": layer,
                },
            }
        except Exception as e:
            logger.error(f"IPC place_component error: {e}")
            return {"success": False, "message": str(e)}

    def _ipc_move_component(self, params):
        """IPC handler for move_component - moves component with real-time UI update"""
        try:
            reference = params.get("reference", params.get("componentId", ""))
            position = params.get("position", {})
            x = (
                position.get("x", 0)
                if isinstance(position, dict)
                else params.get("x", 0)
            )
            y = (
                position.get("y", 0)
                if isinstance(position, dict)
                else params.get("y", 0)
            )
            rotation = params.get("rotation")

            success = self.ipc_board_api.move_component(
                reference=reference, x=x, y=y, rotation=rotation
            )

            return {
                "success": success,
                "message": (
                    f"Moved component {reference} (visible in KiCAD UI)"
                    if success
                    else "Failed to move component"
                ),
            }
        except Exception as e:
            logger.error(f"IPC move_component error: {e}")
            return {"success": False, "message": str(e)}

    def _ipc_delete_component(self, params):
        """IPC handler for delete_component - deletes component with real-time UI update"""
        try:
            reference = params.get("reference", params.get("componentId", ""))

            success = self.ipc_board_api.delete_component(reference=reference)

            return {
                "success": success,
                "message": (
                    f"Deleted component {reference} (visible in KiCAD UI)"
                    if success
                    else "Failed to delete component"
                ),
            }
        except Exception as e:
            logger.error(f"IPC delete_component error: {e}")
            return {"success": False, "message": str(e)}

    def _ipc_get_component_list(self, params):
        """IPC handler for get_component_list"""
        try:
            components = self.ipc_board_api.list_components()

            return {"success": True, "components": components, "count": len(components)}
        except Exception as e:
            logger.error(f"IPC get_component_list error: {e}")
            return {"success": False, "message": str(e)}

    def _ipc_save_project(self, params):
        """IPC handler for save_project"""
        try:
            success = self.ipc_board_api.save()

            return {
                "success": success,
                "message": "Project saved" if success else "Failed to save project",
            }
        except Exception as e:
            logger.error(f"IPC save_project error: {e}")
            return {"success": False, "message": str(e)}

    def _ipc_delete_trace(self, params):
        """IPC handler for delete_trace - Note: IPC doesn't support direct trace deletion yet"""
        # IPC API doesn't have a direct delete track method
        # Fall back to SWIG for this operation
        logger.info(
            "delete_trace: Falling back to SWIG (IPC doesn't support trace deletion)"
        )
        return self.routing_commands.delete_trace(params)

    def _ipc_get_nets_list(self, params):
        """IPC handler for get_nets_list - gets nets with real-time data"""
        try:
            nets = self.ipc_board_api.get_nets()

            return {"success": True, "nets": nets, "count": len(nets)}
        except Exception as e:
            logger.error(f"IPC get_nets_list error: {e}")
            return {"success": False, "message": str(e)}

    def _ipc_add_board_outline(self, params):
        """IPC handler for add_board_outline - adds board edge with real-time UI update.
        Rounded rectangles are delegated to the SWIG path because the IPC BoardSegment
        type cannot represent arcs; the SWIG path writes directly to the .kicad_pcb file
        and correctly generates PCB_SHAPE arcs for rounded corners.
        """
        shape = params.get("shape", "rectangle")
        if shape in ("rounded_rectangle", "rectangle"):
            # IPC path only supports straight segments from a points list,
            # but Claude sends rectangle/rounded_rectangle as shape+width+height.
            # Fall back to the SWIG path which correctly handles both shapes.
            logger.info(f"_ipc_add_board_outline: delegating {shape} to SWIG path")
            return self.board_commands.add_board_outline(params)

        try:
            from kipy.board_types import BoardSegment
            from kipy.geometry import Vector2
            from kipy.util.units import from_mm
            from kipy.proto.board.board_types_pb2 import BoardLayer

            board = self.ipc_board_api._get_board()

            # Unwrap nested params (Claude sends {"shape":..., "params":{...}})
            inner = params.get("params", params)
            points = inner.get("points", params.get("points", []))
            width = inner.get("width", params.get("width", 0.1))

            if len(points) < 2:
                return {
                    "success": False,
                    "message": "At least 2 points required for board outline",
                }

            commit = board.begin_commit()
            lines_created = 0

            # Create line segments connecting the points
            for i in range(len(points)):
                start = points[i]
                end = points[(i + 1) % len(points)]  # Wrap around to close the outline

                segment = BoardSegment()
                segment.start = Vector2.from_xy(
                    from_mm(start.get("x", 0)), from_mm(start.get("y", 0))
                )
                segment.end = Vector2.from_xy(
                    from_mm(end.get("x", 0)), from_mm(end.get("y", 0))
                )
                segment.layer = BoardLayer.BL_Edge_Cuts
                segment.attributes.stroke.width = from_mm(width)

                board.create_items(segment)
                lines_created += 1

            board.push_commit(commit, "Added board outline")

            return {
                "success": True,
                "message": f"Added board outline with {lines_created} segments (visible in KiCAD UI)",
                "segments": lines_created,
            }
        except Exception as e:
            logger.error(f"IPC add_board_outline error: {e}")
            return {"success": False, "message": str(e)}

    def _ipc_add_mounting_hole(self, params):
        """IPC handler for add_mounting_hole - adds mounting hole with real-time UI update"""
        try:
            from kipy.board_types import BoardCircle
            from kipy.geometry import Vector2
            from kipy.util.units import from_mm
            from kipy.proto.board.board_types_pb2 import BoardLayer

            board = self.ipc_board_api._get_board()

            x = params.get("x", 0)
            y = params.get("y", 0)
            diameter = params.get("diameter", 3.2)  # M3 hole default

            commit = board.begin_commit()

            # Create circle on Edge.Cuts layer for the hole
            circle = BoardCircle()
            circle.center = Vector2.from_xy(from_mm(x), from_mm(y))
            circle.radius = from_mm(diameter / 2)
            circle.layer = BoardLayer.BL_Edge_Cuts
            circle.attributes.stroke.width = from_mm(0.1)

            board.create_items(circle)
            board.push_commit(commit, f"Added mounting hole at ({x}, {y})")

            return {
                "success": True,
                "message": f"Added mounting hole at ({x}, {y}) mm (visible in KiCAD UI)",
                "hole": {"position": {"x": x, "y": y}, "diameter": diameter},
            }
        except Exception as e:
            logger.error(f"IPC add_mounting_hole error: {e}")
            return {"success": False, "message": str(e)}

    def _ipc_get_layer_list(self, params):
        """IPC handler for get_layer_list - gets enabled layers"""
        try:
            layers = self.ipc_board_api.get_enabled_layers()

            return {"success": True, "layers": layers, "count": len(layers)}
        except Exception as e:
            logger.error(f"IPC get_layer_list error: {e}")
            return {"success": False, "message": str(e)}

    def _ipc_rotate_component(self, params):
        """IPC handler for rotate_component - rotates component with real-time UI update"""
        try:
            reference = params.get("reference", params.get("componentId", ""))
            angle = params.get("angle", params.get("rotation", 90))

            # Get current component to find its position
            components = self.ipc_board_api.list_components()
            target = None
            for comp in components:
                if comp.get("reference") == reference:
                    target = comp
                    break

            if not target:
                return {"success": False, "message": f"Component {reference} not found"}

            # Calculate new rotation
            current_rotation = target.get("rotation", 0)
            new_rotation = (current_rotation + angle) % 360

            # Use move_component with new rotation (position stays the same)
            success = self.ipc_board_api.move_component(
                reference=reference,
                x=target.get("position", {}).get("x", 0),
                y=target.get("position", {}).get("y", 0),
                rotation=new_rotation,
            )

            return {
                "success": success,
                "message": (
                    f"Rotated component {reference} by {angle}° (visible in KiCAD UI)"
                    if success
                    else "Failed to rotate component"
                ),
                "newRotation": new_rotation,
            }
        except Exception as e:
            logger.error(f"IPC rotate_component error: {e}")
            return {"success": False, "message": str(e)}

    def _ipc_get_component_properties(self, params):
        """IPC handler for get_component_properties - gets detailed component info"""
        try:
            reference = params.get("reference", params.get("componentId", ""))

            components = self.ipc_board_api.list_components()
            target = None
            for comp in components:
                if comp.get("reference") == reference:
                    target = comp
                    break

            if not target:
                return {"success": False, "message": f"Component {reference} not found"}

            return {"success": True, "component": target}
        except Exception as e:
            logger.error(f"IPC get_component_properties error: {e}")
            return {"success": False, "message": str(e)}

    # =========================================================================
    # Legacy IPC command handlers (explicit ipc_* commands)
    # =========================================================================

    def _handle_get_backend_info(self, params):
        """Get information about the current backend"""
        return {
            "success": True,
            "backend": "ipc" if self.use_ipc else "swig",
            "realtime_sync": self.use_ipc,
            "ipc_connected": (
                self.ipc_backend.is_connected() if self.ipc_backend else False
            ),
            "version": self.ipc_backend.get_version() if self.ipc_backend else "N/A",
            "message": (
                "Using IPC backend with real-time UI sync"
                if self.use_ipc
                else "Using SWIG backend (requires manual reload)"
            ),
        }

    def _handle_ipc_add_track(self, params):
        """Add a track using IPC backend (real-time)"""
        if not self.use_ipc or not self.ipc_board_api:
            return {"success": False, "message": "IPC backend not available"}

        try:
            success = self.ipc_board_api.add_track(
                start_x=params.get("startX", 0),
                start_y=params.get("startY", 0),
                end_x=params.get("endX", 0),
                end_y=params.get("endY", 0),
                width=params.get("width", 0.25),
                layer=params.get("layer", "F.Cu"),
                net_name=params.get("net"),
            )
            return {
                "success": success,
                "message": (
                    "Track added (visible in KiCAD UI)"
                    if success
                    else "Failed to add track"
                ),
                "realtime": True,
            }
        except Exception as e:
            logger.error(f"Error adding track via IPC: {e}")
            return {"success": False, "message": str(e)}

    def _handle_ipc_add_via(self, params):
        """Add a via using IPC backend (real-time)"""
        if not self.use_ipc or not self.ipc_board_api:
            return {"success": False, "message": "IPC backend not available"}

        try:
            success = self.ipc_board_api.add_via(
                x=params.get("x", 0),
                y=params.get("y", 0),
                diameter=params.get("diameter", 0.8),
                drill=params.get("drill", 0.4),
                net_name=params.get("net"),
                via_type=params.get("type", "through"),
            )
            return {
                "success": success,
                "message": (
                    "Via added (visible in KiCAD UI)"
                    if success
                    else "Failed to add via"
                ),
                "realtime": True,
            }
        except Exception as e:
            logger.error(f"Error adding via via IPC: {e}")
            return {"success": False, "message": str(e)}

    def _handle_ipc_add_text(self, params):
        """Add text using IPC backend (real-time)"""
        if not self.use_ipc or not self.ipc_board_api:
            return {"success": False, "message": "IPC backend not available"}

        try:
            success = self.ipc_board_api.add_text(
                text=params.get("text", ""),
                x=params.get("x", 0),
                y=params.get("y", 0),
                layer=params.get("layer", "F.SilkS"),
                size=params.get("size", 1.0),
                rotation=params.get("rotation", 0),
            )
            return {
                "success": success,
                "message": (
                    "Text added (visible in KiCAD UI)"
                    if success
                    else "Failed to add text"
                ),
                "realtime": True,
            }
        except Exception as e:
            logger.error(f"Error adding text via IPC: {e}")
            return {"success": False, "message": str(e)}

    def _handle_ipc_list_components(self, params):
        """List components using IPC backend"""
        if not self.use_ipc or not self.ipc_board_api:
            return {"success": False, "message": "IPC backend not available"}

        try:
            components = self.ipc_board_api.list_components()
            return {"success": True, "components": components, "count": len(components)}
        except Exception as e:
            logger.error(f"Error listing components via IPC: {e}")
            return {"success": False, "message": str(e)}

    def _handle_ipc_get_tracks(self, params):
        """Get tracks using IPC backend"""
        if not self.use_ipc or not self.ipc_board_api:
            return {"success": False, "message": "IPC backend not available"}

        try:
            tracks = self.ipc_board_api.get_tracks()
            return {"success": True, "tracks": tracks, "count": len(tracks)}
        except Exception as e:
            logger.error(f"Error getting tracks via IPC: {e}")
            return {"success": False, "message": str(e)}

    def _handle_ipc_get_vias(self, params):
        """Get vias using IPC backend"""
        if not self.use_ipc or not self.ipc_board_api:
            return {"success": False, "message": "IPC backend not available"}

        try:
            vias = self.ipc_board_api.get_vias()
            return {"success": True, "vias": vias, "count": len(vias)}
        except Exception as e:
            logger.error(f"Error getting vias via IPC: {e}")
            return {"success": False, "message": str(e)}

    def _handle_ipc_save_board(self, params):
        """Save board using IPC backend"""
        if not self.use_ipc or not self.ipc_board_api:
            return {"success": False, "message": "IPC backend not available"}

        try:
            success = self.ipc_board_api.save()
            return {
                "success": success,
                "message": "Board saved" if success else "Failed to save board",
            }
        except Exception as e:
            logger.error(f"Error saving board via IPC: {e}")
            return {"success": False, "message": str(e)}

    # JLCPCB API handlers

    def _handle_search_jlcpcb_parts(self, params):
        """Search JLCPCB parts using the local database (FTS + parametric filters)"""
        try:
            query = params.get("query") or None
            package = params.get("package")
            library_type = params.get("library_type")
            in_stock = params.get("in_stock", True)
            limit = params.get("limit", 20)
            category = params.get("category")
            subcategory = params.get("subcategory")
            manufacturer = params.get("manufacturer")

            # Normalise library_type: treat "All" or missing as no filter
            lt_filter = library_type if library_type and library_type != "All" else None

            rows = self.jlcpcb_parts.search_parts(
                query=query,
                category=category,
                subcategory=subcategory,
                package=package,
                library_type=lt_filter,
                manufacturer=manufacturer,
                in_stock=in_stock,
                limit=limit,
            )

            parts = []
            for row in rows:
                try:
                    price_breaks = json.loads(row.get("price_json") or "[]")
                except Exception:
                    price_breaks = []
                parts.append({
                    "lcsc": row["lcsc"],
                    "mfr_part": row.get("mfr_part", ""),
                    "manufacturer": row.get("manufacturer", ""),
                    "description": row.get("description") or row.get("derived_description", ""),
                    "package": row.get("package", ""),
                    "library_type": row.get("library_type", ""),
                    "stock": row.get("stock", 0),
                    "price_breaks": price_breaks,
                    "price_approximate": True,
                    "source": "local_db",
                })

            return {"success": True, "parts": parts, "count": len(parts)}

        except Exception as e:
            logger.error(f"Error searching JLCPCB parts: {e}", exc_info=True)
            return {"success": False, "message": f"Search failed: {str(e)}"}

    def _handle_get_jlcpcb_part(self, params):
        """Get detailed information for a specific JLCPCB part via live JLCPCB API (getComponentDetailByCode)"""
        try:
            lcsc_number = params.get("lcsc_number")
            if not lcsc_number:
                return {"success": False, "message": "Missing lcsc_number parameter"}

            r = self.jlcpcb_client.get_part_by_lcsc(lcsc_number)
            if not r:
                return {"success": False, "message": f"Part not found: {lcsc_number}"}

            lib_map = {"base": "Basic", "expand": "Extended", "preferred": "Preferred"}
            lib_type = lib_map.get((r.get("libraryType") or "").lower(), r.get("libraryType", "Extended"))

            price_breaks = [
                {"qty": pb["startQuantity"], "price": pb["unitPrice"]}
                for pb in (r.get("priceRanges") or [])
            ]

            # Flatten parameters list into a dict
            parameters = {}
            for p in (r.get("parameters") or []):
                name = p.get("parameterName", "")
                val = p.get("parameterValue", "")
                if name:
                    # Append multiple values for the same parameter name
                    if name in parameters:
                        existing = parameters[name]
                        parameters[name] = f"{existing}, {val}" if isinstance(existing, str) else val
                    else:
                        parameters[name] = val

            part = {
                "lcsc": r.get("componentCode", lcsc_number),
                "mfr_part": r.get("componentModel", ""),
                "package": r.get("componentSpecification", ""),
                "category": r.get("firstTypeName", ""),
                "subcategory": r.get("secondTypeName", ""),
                "description": r.get("description", ""),
                "library_type": lib_type,
                "stock": r.get("stockCount", 0),
                "datasheet": r.get("dataManualUrl") or r.get("datasheetUrl", ""),
                "price_breaks": price_breaks,
                "parameters": parameters,
                "rohs": r.get("rohsFlag", False),
                "eccn": r.get("eccnCode", ""),
                "assembly_component": r.get("assemblyComponentFlag", False),
                "source": "live",
            }

            footprints = self.jlcpcb_parts.map_package_to_footprint(part["package"])

            return {"success": True, "part": part, "footprints": footprints}

        except Exception as e:
            logger.error(f"Error getting JLCPCB part: {e}", exc_info=True)
            return {"success": False, "message": f"Failed to get part info: {str(e)}"}

    def _handle_get_jlcpcb_database_stats(self, params):
        """Get statistics about JLCPCB database"""
        try:
            stats = self.jlcpcb_parts.get_database_stats()
            return {"success": True, "stats": stats}

        except Exception as e:
            logger.error(f"Error getting database stats: {e}", exc_info=True)
            return {"success": False, "message": f"Failed to get stats: {str(e)}"}

    def _handle_get_jlcpcb_categories(self, params):
        """Return category or subcategory list from the local DB"""
        try:
            category = params.get("category") or None
            data = self.jlcpcb_parts.get_categories(category=category)
            return {"success": True, **data}
        except Exception as e:
            logger.error(f"Error getting JLCPCB categories: {e}", exc_info=True)
            return {"success": False, "message": str(e)}

    def _handle_suggest_jlcpcb_alternatives(self, params):
        """Suggest alternative JLCPCB parts (live reference via JLCPCB API, alternatives from local DB)"""
        try:
            lcsc_number = params.get("lcsc_number")
            limit = params.get("limit", 5)

            if not lcsc_number:
                return {"success": False, "message": "Missing lcsc_number parameter"}

            # Fetch reference part live for accurate stock/price
            ref_raw = self.jlcpcb_client.get_part_by_lcsc(lcsc_number)
            if not ref_raw:
                return {"success": False, "message": f"Reference part not found: {lcsc_number}"}

            lib_map = {"base": "Basic", "expand": "Extended", "preferred": "Preferred"}
            ref_lib_type = lib_map.get((ref_raw.get("libraryType") or "").lower(), "Extended")
            ref_price_breaks = [
                {"qty": pb["startQuantity"], "price": pb["unitPrice"]}
                for pb in (ref_raw.get("priceRanges") or [])
            ]
            reference_price = ref_price_breaks[0]["price"] if ref_price_breaks else None

            # Search local DB for alternatives by category + package
            # firstTypeName → DB's category column; secondTypeName → DB's subcategory column
            package = ref_raw.get("componentSpecification", "")
            category = ref_raw.get("firstTypeName", "")
            subcategory = ref_raw.get("secondTypeName", "")
            original_lcsc = ref_raw.get("componentCode", lcsc_number)

            alt_rows = self.jlcpcb_parts.search_parts(
                category=category,
                subcategory=subcategory,
                package=package,
                in_stock=True,
                limit=limit * 3,
            )

            alternatives = []
            for row in alt_rows:
                if row["lcsc"] == original_lcsc:
                    continue
                try:
                    price_breaks = json.loads(row.get("price_json") or "[]")
                except Exception:
                    price_breaks = []
                alternatives.append({
                    "lcsc": row["lcsc"],
                    "mfr_part": row.get("mfr_part", ""),
                    "description": row.get("description", ""),
                    "package": row.get("package", ""),
                    "library_type": row.get("library_type", ""),
                    "stock": row.get("stock", 0),
                    "price_breaks": price_breaks,
                    "price_approximate": True,
                    "source": "local_db",
                })
                if len(alternatives) >= limit:
                    break

            return {
                "success": True,
                "reference": {
                    "lcsc": original_lcsc,
                    "mfr_part": ref_raw.get("componentModel", ""),
                    "package": package,
                    "library_type": ref_lib_type,
                    "stock": ref_raw.get("stockCount", 0),
                    "price_breaks": ref_price_breaks,
                },
                "reference_price": reference_price,
                "alternatives": alternatives,
            }

        except Exception as e:
            logger.error(f"Error suggesting alternatives: {e}", exc_info=True)
            return {
                "success": False,
                "message": f"Failed to suggest alternatives: {str(e)}",
            }

    def _handle_enrich_datasheets(self, params):
        """Enrich schematic Datasheet fields from LCSC numbers"""
        try:
            from pathlib import Path

            schematic_path = params.get("schematic_path")
            if not schematic_path:
                return {"success": False, "message": "Missing schematic_path parameter"}
            dry_run = params.get("dry_run", False)
            manager = DatasheetManager()
            return manager.enrich_schematic(Path(schematic_path), dry_run=dry_run)
        except Exception as e:
            logger.error(f"Error enriching datasheets: {e}", exc_info=True)
            return {
                "success": False,
                "message": f"Failed to enrich datasheets: {str(e)}",
            }

    def _handle_get_datasheet_url(self, params):
        """Return LCSC datasheet and product URLs for a part number"""
        try:
            lcsc = params.get("lcsc", "")
            if not lcsc:
                return {"success": False, "message": "Missing lcsc parameter"}
            manager = DatasheetManager()
            datasheet_url = manager.get_datasheet_url(lcsc)
            product_url = manager.get_product_url(lcsc)
            if not datasheet_url:
                return {"success": False, "message": f"Invalid LCSC number: {lcsc}"}
            norm = manager._normalize_lcsc(lcsc)
            return {
                "success": True,
                "lcsc": norm,
                "datasheet_url": datasheet_url,
                "product_url": product_url,
            }
        except Exception as e:
            logger.error(f"Error getting datasheet URL: {e}", exc_info=True)
            return {
                "success": False,
                "message": f"Failed to get datasheet URL: {str(e)}",
            }


def main():
    """Main entry point"""
    logger.info("Starting KiCAD interface...")
    interface = KiCADInterface()

    try:
        logger.info("Processing commands from stdin...")
        # Process commands from stdin
        for line in sys.stdin:
            try:
                # Parse command
                logger.debug(f"Received input: {line.strip()}")
                command_data = json.loads(line)

                # Check if this is JSON-RPC 2.0 format
                if "jsonrpc" in command_data and command_data["jsonrpc"] == "2.0":
                    logger.info("Detected JSON-RPC 2.0 format message")
                    method = command_data.get("method")
                    params = command_data.get("params", {})
                    request_id = command_data.get("id")

                    # Handle MCP protocol methods
                    if method == "initialize":
                        logger.info("Handling MCP initialize")
                        response = {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "result": {
                                "protocolVersion": "2025-06-18",
                                "capabilities": {
                                    "tools": {"listChanged": True},
                                    "resources": {
                                        "subscribe": False,
                                        "listChanged": True,
                                    },
                                },
                                "serverInfo": {
                                    "name": "kicad-mcp-server",
                                    "title": "KiCAD PCB Design Assistant",
                                    "version": "2.1.0-alpha",
                                },
                                "instructions": "AI-assisted PCB design with KiCAD. Use tools to create projects, design boards, place components, route traces, and export manufacturing files.",
                            },
                        }
                    elif method == "tools/list":
                        logger.info("Handling MCP tools/list")
                        # Return list of available tools with proper schemas
                        tools = []
                        for cmd_name in interface.command_routes.keys():
                            # Get schema from TOOL_SCHEMAS if available
                            if cmd_name in TOOL_SCHEMAS:
                                tool_def = TOOL_SCHEMAS[cmd_name].copy()
                                tools.append(tool_def)
                            else:
                                # Fallback for tools without schemas
                                logger.warning(
                                    f"No schema defined for tool: {cmd_name}"
                                )
                                tools.append(
                                    {
                                        "name": cmd_name,
                                        "description": f"KiCAD command: {cmd_name}",
                                        "inputSchema": {
                                            "type": "object",
                                            "properties": {},
                                        },
                                    }
                                )

                        logger.info(f"Returning {len(tools)} tools")
                        response = {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "result": {"tools": tools},
                        }
                    elif method == "tools/call":
                        logger.info("Handling MCP tools/call")
                        tool_name = params.get("name")
                        tool_params = params.get("arguments", {})

                        # Execute the command
                        result = interface.handle_command(tool_name, tool_params)

                        response = {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "result": {
                                "content": [
                                    {"type": "text", "text": json.dumps(result)}
                                ]
                            },
                        }
                    elif method == "resources/list":
                        logger.info("Handling MCP resources/list")
                        # Return list of available resources
                        response = {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "result": {"resources": RESOURCE_DEFINITIONS},
                        }
                    elif method == "resources/read":
                        logger.info("Handling MCP resources/read")
                        resource_uri = params.get("uri")

                        if not resource_uri:
                            response = {
                                "jsonrpc": "2.0",
                                "id": request_id,
                                "error": {
                                    "code": -32602,
                                    "message": "Missing required parameter: uri",
                                },
                            }
                        else:
                            # Read the resource
                            resource_data = handle_resource_read(
                                resource_uri, interface
                            )

                            response = {
                                "jsonrpc": "2.0",
                                "id": request_id,
                                "result": resource_data,
                            }
                    else:
                        logger.error(f"Unknown JSON-RPC method: {method}")
                        response = {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "error": {
                                "code": -32601,
                                "message": f"Method not found: {method}",
                            },
                        }
                else:
                    # Handle legacy custom format
                    logger.info("Detected custom format message")
                    command = command_data.get("command")
                    params = command_data.get("params", {})

                    if not command:
                        logger.error("Missing command field")
                        response = {
                            "success": False,
                            "message": "Missing command",
                            "errorDetails": "The command field is required",
                        }
                    else:
                        # Handle command
                        response = interface.handle_command(command, params)

                # Send response
                logger.debug(f"Sending response: {response}")
                print(json.dumps(response))
                sys.stdout.flush()

            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON input: {str(e)}")
                response = {
                    "success": False,
                    "message": "Invalid JSON input",
                    "errorDetails": str(e),
                }
                print(json.dumps(response))
                sys.stdout.flush()

    except KeyboardInterrupt:
        logger.info("KiCAD interface stopped")
        sys.exit(0)

    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}\n{traceback.format_exc()}")
        sys.exit(1)


if __name__ == "__main__":
    main()
