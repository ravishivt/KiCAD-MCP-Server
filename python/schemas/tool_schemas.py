"""
Comprehensive tool schema definitions for all KiCAD MCP commands

Following MCP 2025-06-18 specification for tool definitions.
Each tool includes:
- name: Unique identifier
- title: Human-readable display name
- description: Detailed explanation of what the tool does
- inputSchema: JSON Schema for parameters
- outputSchema: Optional JSON Schema for return values (structured content)
"""

from typing import Any, Dict

# =============================================================================
# PROJECT TOOLS
# =============================================================================

PROJECT_TOOLS = [
    {
        "name": "create_project",
        "title": "Create New KiCAD Project",
        "description": "Creates a new KiCAD project with PCB board file and optional project configuration. Automatically creates project directory and initializes board with default settings.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "projectName": {
                    "type": "string",
                    "description": "Name of the project (used for file naming)",
                    "minLength": 1,
                },
                "path": {
                    "type": "string",
                    "description": "Directory path where project will be created (defaults to current working directory)",
                },
                "template": {
                    "type": "string",
                    "description": "Optional path to template board file to copy settings from",
                },
            },
            "required": ["projectName"],
        },
    },
    {
        "name": "open_project",
        "title": "Open Existing KiCAD Project",
        "description": "Opens an existing KiCAD project file (.kicad_pro or .kicad_pcb) and loads the board into memory for manipulation.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "Path to .kicad_pro or .kicad_pcb file",
                }
            },
            "required": ["filename"],
        },
    },
    {
        "name": "save_project",
        "title": "Save Current Project",
        "description": "Saves the current board to disk. Can optionally save to a new location.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "Optional new path to save the board (if not provided, saves to current location)",
                }
            },
        },
    },
    {
        "name": "snapshot_project",
        "title": "Snapshot Project (Checkpoint)",
        "description": "Copies the entire project folder to a new timestamped snapshot directory so you can resume from this checkpoint later without redoing earlier steps. Call this after every successfully completed design step (e.g. after Step 1 schematic, after Step 2 PCB layout) before asking for user confirmation to proceed.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "step": {
                    "type": "string",
                    "description": "Step number or name to include in snapshot folder name, e.g. '1' or '2'",
                },
                "label": {
                    "type": "string",
                    "description": "Optional short label, e.g. 'schematic_ok' or 'layout_ok'",
                },
                "projectPath": {
                    "type": "string",
                    "description": "Project directory path. Auto-detected from loaded board if omitted.",
                },
            },
        },
    },
    {
        "name": "get_project_info",
        "title": "Get Project Information",
        "description": "Retrieves metadata and properties of the currently open project including name, paths, and board status.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]

# =============================================================================
# BOARD TOOLS
# =============================================================================

BOARD_TOOLS = [
    {
        "name": "set_board_size",
        "title": "Set Board Dimensions",
        "description": "Sets the PCB board dimensions. The board outline must be added separately using add_board_outline.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "width": {
                    "type": "number",
                    "description": "Board width in millimeters",
                    "minimum": 1,
                },
                "height": {
                    "type": "number",
                    "description": "Board height in millimeters",
                    "minimum": 1,
                },
            },
            "required": ["width", "height"],
        },
    },
    {
        "name": "add_board_outline",
        "title": "Add Board Outline",
        "description": "Adds a board outline shape (rectangle, rounded_rectangle, circle, or polygon) on the Edge.Cuts layer. By default the board top-left corner is placed at (0, 0) so all coordinates are positive. Use x/y to set a different top-left corner position.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "shape": {
                    "type": "string",
                    "enum": ["rectangle", "rounded_rectangle", "circle", "polygon"],
                    "description": "Shape type for the board outline",
                },
                "width": {
                    "type": "number",
                    "description": "Width in mm (for rectangle/rounded_rectangle)",
                    "minimum": 1,
                },
                "height": {
                    "type": "number",
                    "description": "Height in mm (for rectangle/rounded_rectangle)",
                    "minimum": 1,
                },
                "x": {
                    "type": "number",
                    "description": "X coordinate of the top-left corner in mm (default: 0). Board extends from x to x+width.",
                },
                "y": {
                    "type": "number",
                    "description": "Y coordinate of the top-left corner in mm (default: 0). Board extends from y to y+height.",
                },
                "radius": {
                    "type": "number",
                    "description": "Corner radius in mm for rounded_rectangle, or radius for circle",
                    "minimum": 0,
                },
                "points": {
                    "type": "array",
                    "description": "Array of {x, y} point objects in mm (for polygon shape only)",
                    "items": {
                        "type": "object",
                        "properties": {
                            "x": {"type": "number"},
                            "y": {"type": "number"},
                        },
                        "required": ["x", "y"],
                    },
                    "minItems": 3,
                },
            },
            "required": ["shape"],
        },
    },
    {
        "name": "add_layer",
        "title": "Add Custom Layer",
        "description": "Adds a new custom layer to the board stack (e.g., User.1, User.Comments).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "layerName": {
                    "type": "string",
                    "description": "Name of the layer to add",
                },
                "layerType": {
                    "type": "string",
                    "enum": ["signal", "power", "mixed", "jumper"],
                    "description": "Type of layer (for copper layers)",
                },
            },
            "required": ["layerName"],
        },
    },
    {
        "name": "set_active_layer",
        "title": "Set Active Layer",
        "description": "Sets the currently active layer for drawing operations.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "layerName": {
                    "type": "string",
                    "description": "Name of the layer to make active (e.g., F.Cu, B.Cu, Edge.Cuts)",
                }
            },
            "required": ["layerName"],
        },
    },
    {
        "name": "get_layer_list",
        "title": "List Board Layers",
        "description": "Returns a list of all layers in the board with their properties.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_board_info",
        "title": "Get Board Information",
        "description": "Retrieves comprehensive board information including dimensions, layer count, component count, and design rules.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_board_2d_view",
        "title": "Render Board Preview",
        "description": "Generates a 2D visual representation of the current board state as a PNG image.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "width": {
                    "type": "number",
                    "description": "Image width in pixels (default: 800)",
                    "minimum": 100,
                    "default": 800,
                },
                "height": {
                    "type": "number",
                    "description": "Image height in pixels (default: 600)",
                    "minimum": 100,
                    "default": 600,
                },
            },
        },
    },
    {
        "name": "get_board_extents",
        "title": "Get Board Bounding Box",
        "description": "Returns the bounding box extents of the PCB board including all edge cuts, components, and traces.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "unit": {
                    "type": "string",
                    "enum": ["mm", "inch"],
                    "description": "Unit for returned coordinates (default: mm)",
                    "default": "mm",
                }
            },
        },
    },
    {
        "name": "add_mounting_hole",
        "title": "Add Mounting Hole",
        "description": "Adds a mounting hole (non-plated through hole) at the specified position with given diameter.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "x": {"type": "number", "description": "X coordinate in millimeters"},
                "y": {"type": "number", "description": "Y coordinate in millimeters"},
                "diameter": {
                    "type": "number",
                    "description": "Hole diameter in millimeters",
                    "minimum": 0.1,
                },
            },
            "required": ["x", "y", "diameter"],
        },
    },
    {
        "name": "import_svg_logo",
        "title": "Import SVG Logo to PCB",
        "description": "Imports an SVG file as filled graphic polygons onto a KiCAD PCB layer (default F.SilkS). Curves are linearised automatically. Supports path, rect, circle, ellipse, polygon and group transforms.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "pcbPath": {
                    "type": "string",
                    "description": "Path to the .kicad_pcb file",
                },
                "svgPath": {
                    "type": "string",
                    "description": "Path to the SVG logo file",
                },
                "x": {
                    "type": "number",
                    "description": "X position of the logo top-left corner in mm",
                },
                "y": {
                    "type": "number",
                    "description": "Y position of the logo top-left corner in mm",
                },
                "width": {
                    "type": "number",
                    "description": "Target width of the logo in mm (height scaled to preserve aspect ratio)",
                    "minimum": 0.1,
                },
                "layer": {
                    "type": "string",
                    "description": "PCB layer name, e.g. F.SilkS or B.SilkS (default: F.SilkS)",
                    "default": "F.SilkS",
                },
                "strokeWidth": {
                    "type": "number",
                    "description": "Outline stroke width in mm (0 = no outline, default 0)",
                    "default": 0,
                },
                "filled": {
                    "type": "boolean",
                    "description": "Fill polygons with solid layer colour (default true)",
                    "default": True,
                },
            },
            "required": ["pcbPath", "svgPath", "x", "y", "width"],
        },
    },
    {
        "name": "add_board_text",
        "title": "Add Text to Board",
        "description": "Adds text annotation to the board on a specified layer (e.g., F.SilkS for top silkscreen).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Text content to add",
                    "minLength": 1,
                },
                "x": {"type": "number", "description": "X coordinate in millimeters"},
                "y": {"type": "number", "description": "Y coordinate in millimeters"},
                "layer": {
                    "type": "string",
                    "description": "Layer name (e.g., F.SilkS, B.SilkS, F.Cu)",
                    "default": "F.SilkS",
                },
                "size": {
                    "type": "number",
                    "description": "Text size in millimeters",
                    "minimum": 0.1,
                    "default": 1.0,
                },
                "thickness": {
                    "type": "number",
                    "description": "Text thickness in millimeters",
                    "minimum": 0.01,
                    "default": 0.15,
                },
            },
            "required": ["text", "x", "y"],
        },
    },
]

# =============================================================================
# COMPONENT TOOLS
# =============================================================================

COMPONENT_TOOLS = [
    {
        "name": "place_component",
        "title": "Place Component",
        "description": "Places a component with specified footprint at given coordinates on the board.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "reference": {
                    "type": "string",
                    "description": "Component reference designator (e.g., R1, C2, U3)",
                },
                "footprint": {
                    "type": "string",
                    "description": "Footprint library:name (e.g., Resistor_SMD:R_0805_2012Metric)",
                },
                "x": {"type": "number", "description": "X coordinate in millimeters"},
                "y": {"type": "number", "description": "Y coordinate in millimeters"},
                "rotation": {
                    "type": "number",
                    "description": "Rotation angle in degrees (0-360)",
                    "minimum": 0,
                    "maximum": 360,
                    "default": 0,
                },
                "layer": {
                    "type": "string",
                    "enum": ["F.Cu", "B.Cu"],
                    "description": "Board layer (top or bottom)",
                    "default": "F.Cu",
                },
            },
            "required": ["reference", "footprint", "x", "y"],
        },
    },
    {
        "name": "move_component",
        "title": "Move Component",
        "description": "Moves an existing component to a new position on the board.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "reference": {
                    "type": "string",
                    "description": "Component reference designator",
                },
                "x": {
                    "type": "number",
                    "description": "New X coordinate in millimeters",
                },
                "y": {
                    "type": "number",
                    "description": "New Y coordinate in millimeters",
                },
            },
            "required": ["reference", "x", "y"],
        },
    },
    {
        "name": "rotate_component",
        "title": "Rotate Component",
        "description": "Rotates a component by specified angle. Rotation is cumulative with existing rotation.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "reference": {
                    "type": "string",
                    "description": "Component reference designator",
                },
                "angle": {
                    "type": "number",
                    "description": "Rotation angle in degrees (positive = counterclockwise)",
                },
            },
            "required": ["reference", "angle"],
        },
    },
    {
        "name": "delete_component",
        "title": "Delete Component",
        "description": "Removes a component from the board.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "reference": {
                    "type": "string",
                    "description": "Component reference designator",
                }
            },
            "required": ["reference"],
        },
    },
    {
        "name": "edit_component",
        "title": "Edit Component Properties",
        "description": "Modifies properties of an existing component (value, footprint, etc.).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "reference": {
                    "type": "string",
                    "description": "Component reference designator",
                },
                "value": {"type": "string", "description": "New component value"},
                "footprint": {
                    "type": "string",
                    "description": "New footprint library:name",
                },
            },
            "required": ["reference"],
        },
    },
    {
        "name": "get_component_properties",
        "title": "Get Component Properties",
        "description": "Retrieves detailed properties of a specific component.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "reference": {
                    "type": "string",
                    "description": "Component reference designator",
                }
            },
            "required": ["reference"],
        },
    },
    {
        "name": "get_component_list",
        "title": "List All Components",
        "description": "Returns a list of all components on the board with their properties.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "find_component",
        "title": "Find Components",
        "description": "Searches for components matching specified criteria. Supports partial matching on reference, value, or footprint patterns.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "reference": {
                    "type": "string",
                    "description": "Reference designator pattern to match (e.g., 'R1', 'U', 'C2')",
                },
                "value": {
                    "type": "string",
                    "description": "Value pattern to match (e.g., '10k', '100nF')",
                },
                "footprint": {
                    "type": "string",
                    "description": "Footprint pattern to match (e.g., '0805', 'SOIC')",
                },
            },
        },
    },
    {
        "name": "get_component_pads",
        "title": "Get Component Pads",
        "description": "Returns all pads for a component with their positions, net connections, sizes, and shapes.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "reference": {
                    "type": "string",
                    "description": "Component reference designator (e.g., U1, R5)",
                }
            },
            "required": ["reference"],
        },
    },
    {
        "name": "get_pad_position",
        "title": "Get Pad Position",
        "description": "Returns the position and properties of a specific pad on a component.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "reference": {
                    "type": "string",
                    "description": "Component reference designator",
                },
                "padName": {
                    "type": "string",
                    "description": "Pad name or number (e.g., '1', '2', 'A1')",
                },
                "padNumber": {
                    "type": "string",
                    "description": "Alternative to padName - pad number",
                },
            },
            "required": ["reference"],
        },
    },
    {
        "name": "place_component_array",
        "title": "Place Component Array",
        "description": "Places multiple copies of a component in a grid or circular pattern.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "referencePrefix": {
                    "type": "string",
                    "description": "Reference prefix (e.g., 'R' for R1, R2, R3...)",
                },
                "startNumber": {
                    "type": "integer",
                    "description": "Starting number for references",
                    "minimum": 1,
                    "default": 1,
                },
                "footprint": {
                    "type": "string",
                    "description": "Footprint library:name",
                },
                "pattern": {
                    "type": "string",
                    "enum": ["grid", "circular"],
                    "description": "Array pattern type",
                },
                "count": {
                    "type": "integer",
                    "description": "Total number of components to place",
                    "minimum": 1,
                },
                "startX": {
                    "type": "number",
                    "description": "Starting X coordinate in millimeters",
                },
                "startY": {
                    "type": "number",
                    "description": "Starting Y coordinate in millimeters",
                },
                "spacingX": {
                    "type": "number",
                    "description": "Horizontal spacing in mm (for grid pattern)",
                },
                "spacingY": {
                    "type": "number",
                    "description": "Vertical spacing in mm (for grid pattern)",
                },
                "radius": {
                    "type": "number",
                    "description": "Circle radius in mm (for circular pattern)",
                },
                "rows": {
                    "type": "integer",
                    "description": "Number of rows (for grid pattern)",
                    "minimum": 1,
                },
                "columns": {
                    "type": "integer",
                    "description": "Number of columns (for grid pattern)",
                    "minimum": 1,
                },
            },
            "required": [
                "referencePrefix",
                "footprint",
                "pattern",
                "count",
                "startX",
                "startY",
            ],
        },
    },
    {
        "name": "align_components",
        "title": "Align Components",
        "description": "Aligns multiple components horizontally or vertically.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "references": {
                    "type": "array",
                    "description": "Array of component reference designators to align",
                    "items": {"type": "string"},
                    "minItems": 2,
                },
                "direction": {
                    "type": "string",
                    "enum": ["horizontal", "vertical"],
                    "description": "Alignment direction",
                },
                "spacing": {
                    "type": "number",
                    "description": "Spacing between components in mm (optional, for even distribution)",
                },
            },
            "required": ["references", "direction"],
        },
    },
    {
        "name": "duplicate_component",
        "title": "Duplicate Component",
        "description": "Creates a copy of an existing component with new reference designator.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "sourceReference": {
                    "type": "string",
                    "description": "Reference of component to duplicate",
                },
                "newReference": {
                    "type": "string",
                    "description": "Reference designator for the new component",
                },
                "offsetX": {
                    "type": "number",
                    "description": "X offset from original position in mm",
                    "default": 0,
                },
                "offsetY": {
                    "type": "number",
                    "description": "Y offset from original position in mm",
                    "default": 0,
                },
            },
            "required": ["sourceReference", "newReference"],
        },
    },
]

# =============================================================================
# ROUTING TOOLS
# =============================================================================

ROUTING_TOOLS = [
    {
        "name": "add_net",
        "title": "Create Electrical Net",
        "description": "Creates a new electrical net for signal routing.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "netName": {
                    "type": "string",
                    "description": "Name of the net (e.g., VCC, GND, SDA)",
                    "minLength": 1,
                },
                "netClass": {
                    "type": "string",
                    "description": "Optional net class to assign (must exist first)",
                },
            },
            "required": ["netName"],
        },
    },
    {
        "name": "route_trace",
        "title": "Route PCB Trace",
        "description": "Routes a copper trace between two points or pads on a specified layer.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "netName": {"type": "string", "description": "Net name for this trace"},
                "layer": {
                    "type": "string",
                    "description": "Layer to route on (e.g., F.Cu, B.Cu)",
                    "default": "F.Cu",
                },
                "width": {
                    "type": "number",
                    "description": "Trace width in millimeters",
                    "minimum": 0.1,
                },
                "points": {
                    "type": "array",
                    "description": "Array of [x, y] waypoints in millimeters",
                    "items": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 2,
                        "maxItems": 2,
                    },
                    "minItems": 2,
                },
            },
            "required": ["points", "width"],
        },
    },
    {
        "name": "add_via",
        "title": "Add Via",
        "description": "Adds a via (plated through-hole) to connect traces between layers.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "x": {"type": "number", "description": "X coordinate in millimeters"},
                "y": {"type": "number", "description": "Y coordinate in millimeters"},
                "diameter": {
                    "type": "number",
                    "description": "Via diameter in millimeters",
                    "minimum": 0.1,
                },
                "drill": {
                    "type": "number",
                    "description": "Drill diameter in millimeters",
                    "minimum": 0.1,
                },
                "netName": {
                    "type": "string",
                    "description": "Net name to assign to this via",
                },
            },
            "required": ["x", "y", "diameter", "drill"],
        },
    },
    {
        "name": "delete_trace",
        "title": "Delete Trace",
        "description": "Removes traces from the board. Can delete by UUID, position, or bulk-delete all traces on a net.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "uuid": {
                    "type": "string",
                    "description": "UUID of a specific trace to delete",
                },
                "position": {
                    "type": "object",
                    "description": "Delete trace nearest to this position",
                    "properties": {
                        "x": {"type": "number", "description": "X coordinate"},
                        "y": {"type": "number", "description": "Y coordinate"},
                        "unit": {
                            "type": "string",
                            "enum": ["mm", "inch"],
                            "default": "mm",
                        },
                    },
                    "required": ["x", "y"],
                },
                "net": {
                    "type": "string",
                    "description": "Delete all traces on this net (bulk delete)",
                },
                "layer": {
                    "type": "string",
                    "description": "Filter by layer when using net-based deletion",
                },
                "includeVias": {
                    "type": "boolean",
                    "description": "Include vias in net-based deletion",
                    "default": False,
                },
            },
        },
    },
    {
        "name": "query_traces",
        "title": "Query Traces",
        "description": "Queries traces on the board with optional filters by net, layer, or bounding box. Returns trace details including UUID, positions, width, and length.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "net": {
                    "type": "string",
                    "description": "Filter by net name (e.g., 'GND', 'VCC')",
                },
                "layer": {
                    "type": "string",
                    "description": "Filter by layer name (e.g., 'F.Cu', 'B.Cu')",
                },
                "boundingBox": {
                    "type": "object",
                    "description": "Filter by bounding box region",
                    "properties": {
                        "x1": {"type": "number", "description": "Left X coordinate"},
                        "y1": {"type": "number", "description": "Top Y coordinate"},
                        "x2": {"type": "number", "description": "Right X coordinate"},
                        "y2": {"type": "number", "description": "Bottom Y coordinate"},
                        "unit": {
                            "type": "string",
                            "enum": ["mm", "inch"],
                            "default": "mm",
                        },
                    },
                },
                "includeVias": {
                    "type": "boolean",
                    "description": "Include vias in the result",
                    "default": False,
                },
            },
        },
    },
    {
        "name": "modify_trace",
        "title": "Modify Trace",
        "description": "Modifies properties of an existing trace. Find trace by UUID or position, then change width, layer, or net assignment.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "uuid": {
                    "type": "string",
                    "description": "UUID of the trace to modify",
                },
                "position": {
                    "type": "object",
                    "description": "Find trace nearest to this position",
                    "properties": {
                        "x": {"type": "number", "description": "X coordinate"},
                        "y": {"type": "number", "description": "Y coordinate"},
                        "unit": {
                            "type": "string",
                            "enum": ["mm", "inch"],
                            "default": "mm",
                        },
                    },
                    "required": ["x", "y"],
                },
                "width": {"type": "number", "description": "New trace width in mm"},
                "layer": {
                    "type": "string",
                    "description": "New layer name (e.g., 'F.Cu', 'B.Cu')",
                },
                "net": {"type": "string", "description": "New net name to assign"},
            },
        },
    },
    {
        "name": "copy_routing_pattern",
        "title": "Copy Routing Pattern",
        "description": "Copies routing pattern from source components to target components. Enables routing replication between identical component groups by calculating and applying position offset.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "sourceRefs": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Source component references (e.g., ['U1', 'U2', 'U3'])",
                },
                "targetRefs": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Target component references (e.g., ['U4', 'U5', 'U6'])",
                },
                "includeVias": {
                    "type": "boolean",
                    "description": "Include vias in the pattern copy",
                    "default": True,
                },
                "traceWidth": {
                    "type": "number",
                    "description": "Override trace width in mm (uses original if not specified)",
                },
            },
            "required": ["sourceRefs", "targetRefs"],
        },
    },
    {
        "name": "get_nets_list",
        "title": "List All Nets",
        "description": "Returns a list of all electrical nets defined on the board.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "create_netclass",
        "title": "Create Net Class",
        "description": "Defines a net class with specific routing rules (trace width, clearance, etc.).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Net class name",
                    "minLength": 1,
                },
                "traceWidth": {
                    "type": "number",
                    "description": "Default trace width in millimeters",
                    "minimum": 0.1,
                },
                "clearance": {
                    "type": "number",
                    "description": "Clearance in millimeters",
                    "minimum": 0.1,
                },
                "viaDiameter": {
                    "type": "number",
                    "description": "Via diameter in millimeters",
                },
                "viaDrill": {
                    "type": "number",
                    "description": "Via drill diameter in millimeters",
                },
            },
            "required": ["name", "traceWidth", "clearance"],
        },
    },
    {
        "name": "add_copper_pour",
        "title": "Add Copper Pour",
        "description": "Creates a copper pour/zone (typically for ground or power planes).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "netName": {
                    "type": "string",
                    "description": "Net to connect this copper pour to (e.g., GND, VCC)",
                },
                "layer": {
                    "type": "string",
                    "description": "Layer for the copper pour (e.g., F.Cu, B.Cu)",
                },
                "priority": {
                    "type": "integer",
                    "description": "Pour priority (higher priorities fill first)",
                    "minimum": 0,
                    "default": 0,
                },
                "clearance": {
                    "type": "number",
                    "description": "Clearance from other objects in millimeters",
                    "minimum": 0.1,
                },
                "outline": {
                    "type": "array",
                    "description": "Array of [x, y] points defining the pour boundary",
                    "items": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 2,
                        "maxItems": 2,
                    },
                    "minItems": 3,
                },
            },
            "required": ["netName", "layer", "outline"],
        },
    },
    {
        "name": "route_differential_pair",
        "title": "Route Differential Pair",
        "description": "Routes a differential signal pair with matched lengths and spacing.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "positiveName": {
                    "type": "string",
                    "description": "Positive signal net name",
                },
                "negativeName": {
                    "type": "string",
                    "description": "Negative signal net name",
                },
                "layer": {"type": "string", "description": "Layer to route on"},
                "width": {
                    "type": "number",
                    "description": "Trace width in millimeters",
                },
                "gap": {
                    "type": "number",
                    "description": "Gap between traces in millimeters",
                },
                "points": {
                    "type": "array",
                    "description": "Waypoints for the pair routing",
                    "items": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 2,
                        "maxItems": 2,
                    },
                    "minItems": 2,
                },
            },
            "required": ["positiveName", "negativeName", "width", "gap", "points"],
        },
    },
]

# =============================================================================
# LIBRARY TOOLS
# =============================================================================

LIBRARY_TOOLS = [
    {
        "name": "list_libraries",
        "title": "List Footprint Libraries",
        "description": "Lists all available footprint libraries accessible to KiCAD.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "search_footprints",
        "title": "Search Footprints",
        "description": "Searches for footprints matching a query string across all libraries.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query (e.g., '0805', 'SOIC', 'QFP')",
                    "minLength": 1,
                },
                "library": {
                    "type": "string",
                    "description": "Optional library to restrict search to",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "list_library_footprints",
        "title": "List Footprints in Library",
        "description": "Lists all footprints available in a specific library.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "library": {
                    "type": "string",
                    "description": "Library name (e.g., Resistor_SMD, Connector_PinHeader)",
                    "minLength": 1,
                }
            },
            "required": ["library"],
        },
    },
    {
        "name": "get_footprint_info",
        "title": "Get Footprint Details",
        "description": "Retrieves detailed information about a specific footprint including pad layout, dimensions, and description.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "library": {"type": "string", "description": "Library name"},
                "footprint": {"type": "string", "description": "Footprint name"},
            },
            "required": ["library", "footprint"],
        },
    },
]

# =============================================================================
# DESIGN RULE TOOLS
# =============================================================================

DESIGN_RULE_TOOLS = [
    {
        "name": "set_design_rules",
        "title": "Set Design Rules",
        "description": "Configures board design rules including clearances, trace widths, and via sizes.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "clearance": {
                    "type": "number",
                    "description": "Minimum clearance between copper in millimeters",
                    "minimum": 0.1,
                },
                "trackWidth": {
                    "type": "number",
                    "description": "Minimum track width in millimeters",
                    "minimum": 0.1,
                },
                "viaDiameter": {
                    "type": "number",
                    "description": "Minimum via diameter in millimeters",
                },
                "viaDrill": {
                    "type": "number",
                    "description": "Minimum via drill diameter in millimeters",
                },
                "microViaD iameter": {
                    "type": "number",
                    "description": "Minimum micro-via diameter in millimeters",
                },
            },
        },
    },
    {
        "name": "get_design_rules",
        "title": "Get Current Design Rules",
        "description": "Retrieves the currently configured design rules from the board.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "run_drc",
        "title": "Run Design Rule Check",
        "description": "Executes a design rule check (DRC) on the current board and reports violations.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "includeWarnings": {
                    "type": "boolean",
                    "description": "Include warnings in addition to errors",
                    "default": True,
                }
            },
        },
    },
    {
        "name": "get_drc_violations",
        "title": "Get DRC Violations",
        "description": "Returns a list of design rule violations from the most recent DRC run.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]

# =============================================================================
# EXPORT TOOLS
# =============================================================================

EXPORT_TOOLS = [
    {
        "name": "export_gerber",
        "title": "Export Gerber Files",
        "description": "Generates Gerber files for PCB fabrication (industry standard format).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "outputPath": {
                    "type": "string",
                    "description": "Directory path for output files",
                },
                "layers": {
                    "type": "array",
                    "description": "List of layers to export (if not provided, exports all copper and mask layers)",
                    "items": {"type": "string"},
                },
                "includeDrillFiles": {
                    "type": "boolean",
                    "description": "Include drill files (Excellon format)",
                    "default": True,
                },
            },
            "required": ["outputPath"],
        },
    },
    {
        "name": "export_pdf",
        "title": "Export PDF",
        "description": "Exports the board layout as a PDF document for documentation or review.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "outputPath": {
                    "type": "string",
                    "description": "Path for output PDF file",
                },
                "layers": {
                    "type": "array",
                    "description": "Layers to include in PDF",
                    "items": {"type": "string"},
                },
                "colorMode": {
                    "type": "string",
                    "enum": ["color", "black_white"],
                    "description": "Color mode for output",
                    "default": "color",
                },
            },
            "required": ["outputPath"],
        },
    },
    {
        "name": "export_svg",
        "title": "Export SVG",
        "description": "Exports the board as Scalable Vector Graphics for documentation or web display.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "outputPath": {
                    "type": "string",
                    "description": "Path for output SVG file",
                },
                "layers": {
                    "type": "array",
                    "description": "Layers to include in SVG",
                    "items": {"type": "string"},
                },
            },
            "required": ["outputPath"],
        },
    },
    {
        "name": "export_3d",
        "title": "Export 3D Model",
        "description": "Exports a 3D model of the board in STEP or VRML format for mechanical CAD integration.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "outputPath": {
                    "type": "string",
                    "description": "Path for output 3D file",
                },
                "format": {
                    "type": "string",
                    "enum": ["step", "vrml"],
                    "description": "3D model format",
                    "default": "step",
                },
                "includeComponents": {
                    "type": "boolean",
                    "description": "Include 3D component models",
                    "default": True,
                },
            },
            "required": ["outputPath"],
        },
    },
    {
        "name": "export_bom",
        "title": "Export Bill of Materials",
        "description": "Generates a bill of materials (BOM) listing all components with references, values, and footprints.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "outputPath": {
                    "type": "string",
                    "description": "Path for output BOM file",
                },
                "format": {
                    "type": "string",
                    "enum": ["csv", "xml", "html"],
                    "description": "BOM output format",
                    "default": "csv",
                },
                "groupByValue": {
                    "type": "boolean",
                    "description": "Group components with same value together",
                    "default": True,
                },
            },
            "required": ["outputPath"],
        },
    },
]

# =============================================================================
# SCHEMATIC TOOLS
# =============================================================================

SCHEMATIC_TOOLS = [
    {
        "name": "create_schematic",
        "title": "Create New Schematic",
        "description": "Creates a new KiCAD schematic file for circuit design.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "Path for the new schematic file (.kicad_sch)",
                },
                "title": {"type": "string", "description": "Schematic title"},
            },
            "required": ["filename"],
        },
    },
    {
        "name": "load_schematic",
        "title": "Load Existing Schematic",
        "description": "Opens an existing KiCAD schematic file for editing.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "Path to schematic file (.kicad_sch)",
                }
            },
            "required": ["filename"],
        },
    },
    {
        "name": "add_schematic_component",
        "title": "Add Component to Schematic",
        "description": "Places a symbol (resistor, capacitor, IC, etc.) on the schematic. Coordinates are in mm. Use 2.54mm grid multiples. Y increases downward. Space components 15-20mm apart. Use search_schematic_symbols to find the correct library:symbol_name before calling this tool. Use list_symbol_pins to discover pin names before placement.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "reference": {
                    "type": "string",
                    "description": "Reference designator (e.g., R1, C2, U3)",
                },
                "symbol": {
                    "type": "string",
                    "description": "Symbol library:name (e.g., Device:R, Device:C)",
                },
                "value": {
                    "type": "string",
                    "description": "Component value (e.g., 10k, 0.1uF)",
                },
                "x": {
                    "type": "number",
                    "description": "X coordinate on schematic"
                },
                "y": {
                    "type": "number",
                    "description": "Y coordinate on schematic"
                },
                "rotation": {
                    "type": "number",
                    "description": "Rotation in degrees, CCW positive, multiples of 90 (e.g., 0, 90, 180, 270). Default 0."
                },
                "includePins": {
                    "type": "boolean",
                    "description": "Return pin coordinates in the response. Default false. Set true only when planning add_wire routing; batch_connect does not need coordinates."
                }
            },
            "required": ["reference", "symbol", "x", "y"],
        },
    },
    {
        "name": "batch_add_components",
        "title": "Batch Add Components to Schematic",
        "description": "Places multiple symbols on the schematic in a single call. Prefer this over repeated add_schematic_component calls. All symbols must be specified as Library:SymbolName. Returns snapped positions. By default (auto_position_fields=true) automatically positions Reference and Value fields outside the component body based on rotation: rot=0/180 → labels above/below center; rot=90/270 → labels left/right of center. Set includePins: true only when planning add_wire routing; batch_connect does not need coordinates.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "schematicPath": {
                    "type": "string",
                    "description": "Path to the .kicad_sch schematic file"
                },
                "components": {
                    "type": "array",
                    "description": "List of components to place",
                    "items": {
                        "type": "object",
                        "properties": {
                            "symbol": {
                                "type": "string",
                                "description": "Symbol in Library:SymbolName format (e.g., Device:R)"
                            },
                            "reference": {
                                "type": "string",
                                "description": "Reference designator (e.g., R1, C2, U3)"
                            },
                            "value": {
                                "type": "string",
                                "description": "Component value (e.g., 10k, 100nF)"
                            },
                            "footprint": {
                                "type": "string",
                                "description": "Optional footprint (e.g., Resistor_SMD:R_0402)"
                            },
                            "position": {
                                "type": "object",
                                "description": "Placement position in mm",
                                "properties": {
                                    "x": {"type": "number"},
                                    "y": {"type": "number"}
                                },
                                "required": ["x", "y"]
                            },
                            "rotation": {
                                "type": "number",
                                "description": "Rotation in degrees, CCW positive, multiples of 90. Default 0."
                            },
                            "includePins": {
                                "type": "boolean",
                                "description": "Return pin coordinates for this component. Default false. Set true only when planning add_wire routing; batch_connect does not need coordinates."
                            }
                        },
                        "required": ["symbol", "reference", "position"]
                    }
                },
                "auto_position_fields": {
                    "type": "boolean",
                    "description": "Automatically position Reference and Value fields outside the component body based on rotation. Default true. Set false only when you want to position fields manually with batch_set_schematic_property_positions."
                }
            },
            "required": ["schematicPath", "components"]
        }
    },
    {
        "name": "batch_set_schematic_property_positions",
        "title": "Batch Set Property Positions",
        "description": "Move Reference and/or Value property fields for multiple components in a single call (one file read/write). Use this after batch_add_components when auto-positioning is insufficient (e.g., for ICs, connectors, or PWR_FLAGs with non-standard layouts). Replaces 22+ individual set_schematic_property_position calls with 1.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "schematicPath": {
                    "type": "string",
                    "description": "Path to the .kicad_sch schematic file"
                },
                "updates": {
                    "type": "array",
                    "description": "List of property position updates to apply",
                    "items": {
                        "type": "object",
                        "properties": {
                            "reference": {
                                "type": "string",
                                "description": "Component reference designator (e.g., R1, U3)"
                            },
                            "property": {
                                "type": "string",
                                "enum": ["Reference", "Value"],
                                "description": "Which property field to move"
                            },
                            "x": {
                                "type": "number",
                                "description": "New X coordinate in mm"
                            },
                            "y": {
                                "type": "number",
                                "description": "New Y coordinate in mm"
                            },
                            "angle": {
                                "type": "number",
                                "description": "Text rotation angle in degrees (0=horizontal, 90=vertical). Default 0."
                            },
                            "visible": {
                                "type": "boolean",
                                "description": "Whether the field should be visible. Default true."
                            }
                        },
                        "required": ["reference", "property", "x", "y"]
                    },
                    "minItems": 1
                }
            },
            "required": ["schematicPath", "updates"]
        }
    },
    {
        "name": "add_schematic_wire",
        "title": "Draw Wire Between Pins",
        "description": "Draws a wire on the schematic between two or more coordinate points. Always call get_schematic_pin_locations first to get the approximate pin coordinates, then pass them as the first and last waypoints. snapToPins (on by default) will correct any float imprecision by snapping endpoints to the exact nearest pin coordinate. To route around components, add intermediate waypoints between the start and end: e.g. [[x1,y1], [xMid,y1], [xMid,y2], [x2,y2]] routes horizontally then vertically. Intermediate waypoints are never snapped.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "schematicPath": {
                    "type": "string",
                    "description": "Path to schematic file",
                },
                "waypoints": {
                    "type": "array",
                    "description": "Array of [x, y] coordinates defining the wire path. First and last points are the pin locations (from get_schematic_pin_locations). Add intermediate points to route around obstacles.",
                    "items": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 2,
                        "maxItems": 2,
                    },
                    "minItems": 2,
                },
                "snapToPins": {
                    "type": "boolean",
                    "description": "When true, the first and last waypoints are snapped to the nearest schematic pin within snapTolerance mm. Intermediate waypoints are left unchanged. Enabled by default to correct float coordinate imprecision.",
                    "default": True,
                },
                "snapTolerance": {
                    "type": "number",
                    "description": "Maximum distance in mm to search for a nearby pin when snapToPins is enabled.",
                    "default": 1.0,
                },
            },
            "required": ["schematicPath", "waypoints"],
        },
    },
    {
        "name": "add_schematic_net_label",
        "title": "Add Net Label",
        "description": "Adds a net label at exact coordinates on a schematic wire or pin endpoint. WARNING: x/y must match an existing wire endpoint or pin endpoint exactly — placing the label even 0.01mm away from a pin will result in an unconnected pin ERC error. To connect a component pin to a net by reference and pin number (recommended), use connect_to_net instead. To place at a pin by reference+pinNumber with automatic position lookup, use place_net_label_at_pin instead.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "schematicPath": {
                    "type": "string",
                    "description": "Path to schematic file",
                },
                "netName": {
                    "type": "string",
                    "description": "Name of the net (e.g., VCC, GND, SDA)",
                },
                "x": {"type": "number", "description": "X coordinate on schematic"},
                "y": {"type": "number", "description": "Y coordinate on schematic"},
                "rotation": {
                    "type": "number",
                    "description": "Rotation angle in degrees (0, 90, 180, 270)",
                    "default": 0,
                },
            },
            "required": ["schematicPath", "netName", "x", "y"],
        },
    },
    {
        "name": "connect_to_net",
        "title": "Connect Pin to Net",
        "description": "Intelligently connects a component pin to a named net, automatically routing wires as needed. PREFERRED connection method. Do NOT call get_schematic_pin_locations first — pin lookup is automatic. For no-wire-stub placement, use place_net_label_at_pin instead. NOTE: If a global label with the same net name already exists on the sheet, this tool will return a warning and refuse to place a conflicting local label (to avoid ERC errors). Use force=true to override, or use add_wire to connect to the existing global label instead.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "schematicPath": {
                    "type": "string",
                    "description": "Path to schematic file",
                },
                "reference": {
                    "type": "string",
                    "description": "Component reference designator (e.g., R1, U3)",
                },
                "pinNumber": {
                    "type": "string",
                    "description": "Pin number or name on the component",
                },
                "netName": {
                    "type": "string",
                    "description": "Name of the net to connect to",
                },
                "force": {
                    "type": "boolean",
                    "description": "If true, place the local label even if a global label with the same name exists (may produce ERC warnings). Default false.",
                    "default": False,
                },
            },
            "required": ["schematicPath", "reference", "pinNumber", "netName"],
        },
    },
    {
        "name": "get_net_connections",
        "title": "Get Net Connections",
        "description": "Returns all components and pins connected to a specified net.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "schematicPath": {
                    "type": "string",
                    "description": "Path to schematic file",
                },
                "netName": {
                    "type": "string",
                    "description": "Name of the net to query",
                },
            },
            "required": ["schematicPath", "netName"],
        },
    },
    {
        "name": "get_wire_connections",
        "title": "Get Wire Connections",
        "description": "Returns all wires and component pins connected to the wire at a given point, by flood-filling through touching wires.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "schematicPath": {
                    "type": "string",
                    "description": "Path to schematic file",
                },
                "x": {
                    "type": "number",
                    "description": "X coordinate of the point on the wire",
                },
                "y": {
                    "type": "number",
                    "description": "Y coordinate of the point on the wire",
                },
            },
            "required": ["schematicPath", "x", "y"],
        },
    },
    {
        "name": "get_schematic_pin_locations",
        "title": "Get Schematic Pin Locations",
        "description": "Returns the exact absolute coordinates of all pins on a schematic component. Use this BEFORE placing net labels with add_schematic_net_label to get the correct x/y position for each pin endpoint. If the reference is not found, the error message lists all available references in the schematic. Note: unannotated components have '?' references (e.g. R?) — run annotate_schematic first or use the exact reference including '?'.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "schematicPath": {
                    "type": "string",
                    "description": "Path to the schematic file",
                },
                "reference": {
                    "type": "string",
                    "description": "Component reference designator (e.g., U1, R1, J2)",
                },
            },
            "required": ["schematicPath", "reference"],
        },
    },
    {
        "name": "connect_passthrough",
        "title": "Connect Passthrough (Pin-to-Pin)",
        "description": "Connects all pins of a source connector to the matching pins of a target connector using shared net labels. Ideal for passthrough adapters where J1 pin N connects directly to J2 pin N. Each pair gets a net label '{netPrefix}_{pinNumber}'. Use this instead of calling connect_to_net 15 times for FFC/ribbon cable passthroughs. NOTE: KiCAD Connector_Generic symbols always have pin 1 at the TOP of the symbol and pin N at the BOTTOM. When assigning named nets (e.g. GND, CAM_SCL) to specific pin numbers, always use the physical pin number as shown in the connector datasheet — pin 1 = top of symbol.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "schematicPath": {
                    "type": "string",
                    "description": "Path to the schematic file",
                },
                "sourceRef": {
                    "type": "string",
                    "description": "Reference of the source connector (e.g., J1)",
                },
                "targetRef": {
                    "type": "string",
                    "description": "Reference of the target connector (e.g., J2)",
                },
                "netPrefix": {
                    "type": "string",
                    "description": "Prefix for generated net names, e.g. 'CSI' produces CSI_1, CSI_2, ... (default: PIN)",
                },
                "pinOffset": {
                    "type": "integer",
                    "description": "Add this value to the pin number when building net names (default: 0)",
                },
            },
            "required": ["schematicPath", "sourceRef", "targetRef"],
        },
    },
    {
        "name": "place_net_label_at_pin",
        "title": "Place Net Label at Pin",
        "description": "Places a net label at the exact pin endpoint of a component, with automatic position and orientation lookup. No wire stub is generated — avoids floating-endpoint ERC errors. PREFERRED over connect_to_net for clean schematics.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "schematicPath": {
                    "type": "string",
                    "description": "Path to the .kicad_sch schematic file"
                },
                "reference": {
                    "type": "string",
                    "description": "Component reference designator (e.g., R1, U3)"
                },
                "pinNumber": {
                    "type": "string",
                    "description": "Pin number on the component"
                },
                "netName": {
                    "type": "string",
                    "description": "Net label text (e.g., VCC, GND, SDA)"
                }
            },
            "required": ["schematicPath", "reference", "pinNumber", "netName"]
        }
    },
    {
        "name": "list_unconnected_pins",
        "title": "List Unconnected Pins",
        "description": "Returns pins with no net connection and no no-connect flag. Use instead of ERC for connectivity checks — faster and returns structured data.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "schematicPath": {
                    "type": "string",
                    "description": "Path to the .kicad_sch schematic file",
                }
            },
            "required": ["schematicPath"],
        },
    },
    {
        "name": "search_schematic_symbols",
        "title": "Search Schematic Symbols",
        "description": "Search symbol libraries by name to find the correct Library:SymbolName before calling add_schematic_component. Searches symbol names and library names. E.g. query='STM32F103' returns 'MCU_ST_STM32F1:STM32F103C8Tx'. When schematicPath is provided, project-local libraries are searched first and global libraries with the same nickname are skipped (they are shadowed).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query (matched against symbol names and library names)"
                },
                "maxResults": {
                    "type": "integer",
                    "description": "Maximum number of results to return (default: 20, max: 100)",
                    "default": 20,
                    "maximum": 100
                },
                "schematicPath": {
                    "type": "string",
                    "description": "Optional path to .kicad_sch file. When provided, searches project-local libraries first and excludes shadowed global libraries. Always provide this when working in a project."
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "list_symbol_pins",
        "title": "List Symbol Pins",
        "description": "Returns pin names, numbers, and types for a symbol directly from the library — no schematic required. Use before add_schematic_component to discover pin names for connect_to_net / batch_connect calls. Returns close-match suggestions if the symbol name is slightly wrong.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "Symbol in Library:SymbolName format (e.g., Device:R, Connector:Conn_01x04)"
                },
                "schematicPath": {
                    "type": "string",
                    "description": "Optional path to .kicad_sch file; enables project-local sym-lib-table lookup"
                }
            },
            "required": ["symbol"]
        }
    },
    {
        "name": "batch_list_symbol_pins",
        "title": "Batch List Symbol Pins",
        "description": "Returns pin names, numbers, types, and symbol-local coordinates for multiple symbols in a single call. Prefer this over calling list_symbol_pins repeatedly. Returns a map of symbol -> {pins, pin_count, body_bbox}. body_bbox gives the symbol body extent in local coordinates (pin envelope ±1.27mm) with width/height fields — use these to plan component spacing before placement.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "symbols": {
                    "type": "array",
                    "description": "List of symbols in Library:SymbolName format (e.g., [\"Device:R\", \"Device:C\", \"Connector:Conn_01x04\"])",
                    "items": {"type": "string"}
                },
                "schematicPath": {
                    "type": "string",
                    "description": "Optional path to .kicad_sch file; enables project-local sym-lib-table lookup"
                }
            },
            "required": ["symbols"]
        }
    },
    {
        "name": "sync_schematic_to_board",
        "title": "Sync Schematic to PCB (F8)",
        "description": "Reads net connections from the schematic and assigns them to matching component pads in the PCB board file. Equivalent to KiCAD Pcbnew F8 'Update PCB from Schematic'. Must be called after placing components and before routing traces, so that pad-to-net assignments are correct.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "schematicPath": {
                    "type": "string",
                    "description": "Path to .kicad_sch file. If omitted, auto-detected from current board path.",
                },
                "boardPath": {
                    "type": "string",
                    "description": "Path to .kicad_pcb file. If omitted, uses currently loaded board.",
                },
            },
        },
    },
    {
        "name": "generate_netlist",
        "title": "Generate Netlist",
        "description": "Generates a full netlist from the schematic: nets + components. Use for complete connectivity analysis or PCB sync. For nets only, use list_schematic_nets.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "schematicPath": {
                    "type": "string",
                    "description": "Path to schematic file",
                },
                "outputPath": {
                    "type": "string",
                    "description": "Optional path to save netlist file",
                },
                "format": {
                    "type": "string",
                    "enum": ["kicad", "json", "spice"],
                    "description": "Netlist output format",
                    "default": "json",
                },
            },
            "required": ["schematicPath"],
        },
    },
    {
        "name": "list_schematic_libraries",
        "title": "List Symbol Libraries",
        "description": "Lists all available symbol libraries for schematic design.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "searchPaths": {
                    "type": "array",
                    "description": "Optional additional paths to search for libraries",
                    "items": {"type": "string"},
                }
            },
        },
    },
    {
        "name": "annotate_schematic",
        "title": "Annotate Schematic Components",
        "description": "Assigns reference designators to all unannotated components (e.g. R? → R1, U? → U1). Run this before get_schematic_pin_locations or run_erc to ensure all components have proper references. Returns a list of old→new reference mappings.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "schematicPath": {
                    "type": "string",
                    "description": "Path to the .kicad_sch schematic file"
                }
            },
            "required": ["schematicPath"]
        }
    },
    {
        "name": "list_schematic_components",
        "title": "List Schematic Components",
        "description": "Returns structured data for all components in the schematic including reference, value, footprint, position, pins with coordinates, and a 'properties' dict containing all KiCad symbol properties (MPN, Description, Manufacturer, Datasheet, and any custom user-defined fields). Preferred over get_schematic_view for data access.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "schematicPath": {
                    "type": "string",
                    "description": "Path to the .kicad_sch schematic file"
                },
                "filter": {
                    "type": "object",
                    "description": "Optional filters",
                    "properties": {
                        "libId": {"type": "string", "description": "Filter by library ID substring"},
                        "referencePrefix": {"type": "string", "description": "Filter by reference prefix (e.g. 'R', 'U')"}
                    }
                }
            },
            "required": ["schematicPath"]
        }
    },
    {
        "name": "list_schematic_nets",
        "title": "List Schematic Nets",
        "description": "Returns all net names and their pin connections. Each net entry includes a 'labelType' field: 'local' (local label only), 'global' (global label, takes ERC priority), or 'power' (#PWR symbol). Each connection includes 'pinName' (semantic name, e.g. 'FB', 'EN') and 'pinType' (e.g. 'input', 'output', 'passive') in addition to the pin number. For full connectivity + component data, use generate_netlist. For a single compact view of the whole schematic, use get_schematic_summary.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "schematicPath": {
                    "type": "string",
                    "description": "Path to the .kicad_sch schematic file"
                }
            },
            "required": ["schematicPath"]
        }
    },
    {
        "name": "get_schematic_view",
        "title": "Get Schematic View",
        "description": "Returns a rasterized image (PNG or SVG) of the schematic for spatial overview. For structured data, prefer list_schematic_components.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "schematicPath": {
                    "type": "string",
                    "description": "Path to the .kicad_sch schematic file"
                },
                "format": {
                    "type": "string",
                    "enum": ["png", "svg"],
                    "description": "Output image format (default: png)",
                    "default": "png"
                },
                "width": {
                    "type": "integer",
                    "description": "Output image width in pixels (default: 1200)",
                    "default": 1200
                },
                "height": {
                    "type": "integer",
                    "description": "Output image height in pixels (default: 900)",
                    "default": 900
                }
            },
            "required": ["schematicPath"]
        }
    },
    {
        "name": "export_schematic_pdf",
        "title": "Export Schematic to PDF",
        "description": "Exports the schematic as a PDF document for printing or documentation.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "schematicPath": {
                    "type": "string",
                    "description": "Path to schematic file",
                },
                "outputPath": {"type": "string", "description": "Path for output PDF"},
            },
            "required": ["schematicPath", "outputPath"],
        },
    },
    {
        "name": "add_schematic_junction",
        "title": "Add Junction to Schematic",
        "description": "Adds a junction (connection dot) at the specified coordinates on the schematic. Junctions are required in KiCAD to mark intentional connections where wires cross or where a wire branches off another wire. Without a junction, crossing wires are not electrically connected.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "schematicPath": {
                    "type": "string",
                    "description": "Path to schematic file",
                },
                "position": {
                    "type": "array",
                    "description": "The [x, y] coordinates where the junction should be placed. Must be on an existing wire intersection or branch point.",
                    "items": {"type": "number"},
                    "minItems": 2,
                    "maxItems": 2,
                },
            },
            "required": ["schematicPath", "position"],
        },
    },
    # --- Schematic Analysis Tools (read-only) ---
    {
        "name": "get_schematic_view_region",
        "title": "Get Schematic View Region",
        "description": "Exports a cropped region of the schematic as an image (PNG or SVG). Specify a bounding box in schematic mm coordinates to zoom into a specific area.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "schematicPath": {
                    "type": "string",
                    "description": "Path to the .kicad_sch schematic file",
                },
                "x1": {
                    "type": "number",
                    "description": "Left X coordinate of the region in mm",
                },
                "y1": {
                    "type": "number",
                    "description": "Top Y coordinate of the region in mm",
                },
                "x2": {
                    "type": "number",
                    "description": "Right X coordinate of the region in mm",
                },
                "y2": {
                    "type": "number",
                    "description": "Bottom Y coordinate of the region in mm",
                },
                "format": {
                    "type": "string",
                    "enum": ["png", "svg"],
                    "description": "Output image format (default: png)",
                },
                "width": {
                    "type": "integer",
                    "description": "Output image width in pixels (default: 800)",
                },
                "height": {
                    "type": "integer",
                    "description": "Output image height in pixels (default: 600)",
                },
            },
            "required": ["schematicPath", "x1", "y1", "x2", "y2"],
        },
    },
    {
        "name": "find_overlapping_elements",
        "title": "Find Overlapping Elements",
        "description": "Detects spatially overlapping symbols, wires, and labels in the schematic. Finds: duplicate power symbols at the same position, collinear overlapping wire segments, and labels stacked on top of each other.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "schematicPath": {
                    "type": "string",
                    "description": "Path to the .kicad_sch schematic file",
                },
                "tolerance": {
                    "type": "number",
                    "description": "Distance threshold in mm for label proximity and wire collinearity checks. Symbol overlap uses bounding-box intersection. (default: 0.5)",
                },
            },
            "required": ["schematicPath"],
        },
    },
    {
        "name": "get_elements_in_region",
        "title": "Get Elements in Region",
        "description": "Lists all symbols, wires, and labels within a rectangular region of the schematic. Useful for understanding what is in a specific area before modifying it.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "schematicPath": {
                    "type": "string",
                    "description": "Path to the .kicad_sch schematic file",
                },
                "x1": {
                    "type": "number",
                    "description": "Left X coordinate of the region in mm",
                },
                "y1": {
                    "type": "number",
                    "description": "Top Y coordinate of the region in mm",
                },
                "x2": {
                    "type": "number",
                    "description": "Right X coordinate of the region in mm",
                },
                "y2": {
                    "type": "number",
                    "description": "Bottom Y coordinate of the region in mm",
                },
            },
            "required": ["schematicPath", "x1", "y1", "x2", "y2"],
        },
    },
    {
        "name": "find_wires_crossing_symbols",
        "title": "Find Wires Crossing Symbols",
        "description": "Find all wires that cross over component symbol bodies. Wires passing over symbols are unacceptable in schematics — they indicate routing mistakes where a wire was drawn across a component instead of around it.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "schematicPath": {
                    "type": "string",
                    "description": "Path to the .kicad_sch schematic file",
                }
            },
            "required": ["schematicPath"],
        },
    },
    {
        "name": "add_no_connect",
        "title": "Add No-Connect Flag",
        "description": "Marks an intentionally unconnected pin with a no-connect flag (X marker) to suppress ERC 'Pin not connected' errors. Use get_schematic_pin_locations to get the exact pin coordinates first, then place the no-connect flag at the pin endpoint. This is the correct way to handle pins that are intentionally left unconnected (e.g., NC/DNP pins, unused GPIO, SBU pins on USB-C).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "schematicPath": {
                    "type": "string",
                    "description": "Path to the .kicad_sch schematic file"
                },
                "componentRef": {
                    "type": "string",
                    "description": "Component reference designator (e.g., U1). Use with pinName to auto-resolve the pin position."
                },
                "pinName": {
                    "type": "string",
                    "description": "Pin number or name on the component (e.g., '3', 'NC'). Used with componentRef to auto-resolve position."
                },
                "position": {
                    "type": "array",
                    "description": "Pin endpoint coordinates [x, y] in mm. Alternative to componentRef+pinName; must match the pin endpoint exactly.",
                    "items": {"type": "number"},
                    "minItems": 2,
                    "maxItems": 2
                }
            },
            "required": ["schematicPath"]
        }
    },
    {
        "name": "batch_add_no_connects",
        "title": "Batch Add No-Connect Flags",
        "description": "Adds no-connect (X) markers to multiple pins in a single call. Each entry auto-resolves the pin position from the schematic. Use this to suppress ERC 'Pin not connected' errors for intentionally unconnected pins (NC/DNP pins, unused GPIO, SBU pins on USB-C). Replaces multiple individual add_no_connect calls.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "schematicPath": {
                    "type": "string",
                    "description": "Path to the .kicad_sch schematic file"
                },
                "pins": {
                    "type": "array",
                    "description": "List of pins to mark as no-connect",
                    "items": {
                        "type": "object",
                        "properties": {
                            "componentRef": {
                                "type": "string",
                                "description": "Component reference designator (e.g., U1, J2)"
                            },
                            "pinName": {
                                "type": "string",
                                "description": "Pin number or name (e.g., '3', 'NC', 'SBU1')"
                            }
                        },
                        "required": ["componentRef", "pinName"]
                    },
                    "minItems": 1
                }
            },
            "required": ["schematicPath", "pins"]
        }
    },
    {
        "name": "save_schematic",
        "title": "Save Schematic",
        "description": "Confirms the schematic file is saved to disk. Note: all schematic editing tools (add_schematic_wire, connect_to_net, add_schematic_net_label, etc.) write changes directly to the .kicad_sch file immediately — there is no separate save step required. Use this tool to verify the file exists and check its current size.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "schematicPath": {
                    "type": "string",
                    "description": "Path to the .kicad_sch schematic file"
                }
            },
            "required": ["schematicPath"]
        }
    },
    {
        "name": "get_schematic_summary",
        "title": "Get Schematic Summary",
        "description": "Returns a compact, human-readable text summary of the entire schematic: a components table (ref, value, MPN, description, footprint) and a net adjacency list (net name → REF/pin_name connections). Nets are classified as ground, power_rail, clock, differential_pair, or signal. Optimised for LLM consumption — much more token-efficient than calling list_schematic_components + list_schematic_nets separately.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "schematicPath": {
                    "type": "string",
                    "description": "Path to the .kicad_sch schematic file"
                }
            },
            "required": ["schematicPath"]
        }
    },
    {
        "name": "get_net_graph",
        "title": "Get Component Net Graph",
        "description": "Returns a compact text adjacency graph showing which components connect to which through signal nets. Each line shows: SOURCE(pin) --[NET]--> DEST1(pin), DEST2(pin). Power/ground nets with fewer than 3 real components are filtered by default (use skipPower=false to include all). Useful for tracing signal paths and identifying topology (e.g. voltage-divider feedback networks) without reconstructing from two separate flat lists.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "schematicPath": {
                    "type": "string",
                    "description": "Path to the .kicad_sch schematic file"
                },
                "skipPower": {
                    "type": "boolean",
                    "description": "Skip GND/power-rail nets that connect fewer than 3 real components (default: true)",
                    "default": True
                }
            },
            "required": ["schematicPath"]
        }
    },
    {
        "name": "find_single_pin_nets",
        "title": "Find Single-Pin (Dangling) Nets",
        "description": "Returns all nets that have exactly one connected pin — dangling/floating connections that are likely unintentional wiring errors or in-progress stubs. Each entry includes the net name, component reference, pin number, and semantic pin name. Especially useful during design review to catch open connections that ERC may miss depending on pin type.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "schematicPath": {
                    "type": "string",
                    "description": "Path to the .kicad_sch schematic file"
                }
            },
            "required": ["schematicPath"]
        }
    },
    {
        "name": "classify_nets",
        "title": "Classify Schematic Nets",
        "description": "Classifies every net by type (ground, power_rail, clock, differential_pair, signal) and returns driver/load pin counts and fan-out. Classification heuristics: GND/AGND/DGND/PGND → ground; voltage-pattern names or PWR_FLAG present → power_rail; CLK/SCK/OSC in name → clock; _P/_N or +/- suffix pairs → differential_pair. Useful for quickly identifying structurally interesting nets (high fan-out, no driver, etc.) without manually counting.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "schematicPath": {
                    "type": "string",
                    "description": "Path to the .kicad_sch schematic file"
                }
            },
            "required": ["schematicPath"]
        }
    },
    {
        "name": "run_erc",
        "title": "Run Electrical Rules Check (ERC)",
        "description": "Runs the KiCAD Electrical Rules Check (ERC) on a schematic via kicad-cli and returns all violations. Each violation includes type, severity, message, location (x/y coordinates), and an 'items' array where each item has a 'description' field identifying the specific component/pin (e.g. 'Pin 1 [Passive] of R1') and its position. Annotate the schematic first (annotate_schematic) for best results. Set hierarchical=true to run ERC on every .kicad_sch in the project directory and get per-sheet violations.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "schematicPath": {
                    "type": "string",
                    "description": "Path to the .kicad_sch schematic file"
                },
                "hierarchical": {
                    "type": "boolean",
                    "description": "Run ERC on all .kicad_sch files in the project directory (root + sub-sheets) and return violations grouped by sheet. Default false (single sheet only)."
                }
            },
            "required": ["schematicPath"]
        }
    },
    {
        "name": "create_hierarchical_subsheet",
        "title": "Create Hierarchical Sub-Sheet",
        "description": "Creates a new blank sub-sheet schematic file and links it into a parent schematic in one call. Replaces the 3-step workflow of: (1) create_schematic for sub-sheet, (2) create_schematic for root if needed, (3) add_hierarchical_sheet to link them. Returns the sub-sheet file path, its UUID, the sheet block UUID in the parent, and the page number assigned.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "parentSchematicPath": {
                    "type": "string",
                    "description": "Path to the existing parent .kicad_sch file that will contain the sheet reference block"
                },
                "subsheetPath": {
                    "type": "string",
                    "description": "Path for the new sub-sheet .kicad_sch file to create (must not already exist)"
                },
                "sheetName": {
                    "type": "string",
                    "description": "Display name for the sheet block in the parent schematic (e.g., 'Power', 'USB Interface'). Default 'Sheet'."
                },
                "position": {
                    "type": "object",
                    "description": "Position of the sheet block in the parent schematic (mm). Default {x:50, y:50}.",
                    "properties": {
                        "x": {"type": "number"},
                        "y": {"type": "number"}
                    }
                },
                "size": {
                    "type": "object",
                    "description": "Size of the sheet block rectangle (mm). Default {width:80, height:50}.",
                    "properties": {
                        "width": {"type": "number"},
                        "height": {"type": "number"}
                    }
                },
                "metadata": {
                    "type": "object",
                    "description": "Optional metadata for the new sub-sheet schematic (title block, revision, etc.)"
                }
            },
            "required": ["parentSchematicPath", "subsheetPath"]
        }
    },
    {
        "name": "list_schematic_wires",
        "title": "List Schematic Wires",
        "description": "List wire segments in a schematic. Optionally filter by net name (returns only wires reachable from that net's labels via BFS). Set annotate_nets=true to include net membership for each wire segment.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "schematicPath": {
                    "type": "string",
                    "description": "Path to .kicad_sch file"
                },
                "netName": {
                    "type": "string",
                    "description": "If provided, return only wires on this net"
                },
                "annotate_nets": {
                    "type": "boolean",
                    "description": "If true, annotate each wire with its net name",
                    "default": False
                }
            },
            "required": ["schematicPath"]
        }
    },
    {
        "name": "replace_schematic_component",
        "title": "Replace Schematic Component",
        "description": "Replace a placed symbol with a different symbol from the library while preserving its position, rotation, and field values (Reference, Value, Footprint). Returns the new pin coordinates.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "schematicPath": {
                    "type": "string",
                    "description": "Path to .kicad_sch file"
                },
                "reference": {
                    "type": "string",
                    "description": "Reference designator of the component to replace (e.g. D1, U3)"
                },
                "newSymbol": {
                    "type": "string",
                    "description": "New symbol in 'Library:Symbol' format (e.g. 'Device:D_Zener')"
                },
                "newRotation": {
                    "type": "number",
                    "description": "Optional rotation angle in degrees for the new symbol. If omitted, the original rotation is preserved."
                }
            },
            "required": ["schematicPath", "reference", "newSymbol"]
        }
    }
]

# =============================================================================
# UI/PROCESS TOOLS
# =============================================================================

UI_TOOLS = [
    {
        "name": "check_kicad_ui",
        "title": "Check KiCAD UI Status",
        "description": "Checks if KiCAD user interface is currently running and returns process information.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "launch_kicad_ui",
        "title": "Launch KiCAD Application",
        "description": "Opens the KiCAD graphical user interface, optionally with a specific project loaded.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "projectPath": {
                    "type": "string",
                    "description": "Optional path to project file to open in UI",
                },
                "autoLaunch": {
                    "type": "boolean",
                    "description": "Whether to automatically launch if not running",
                    "default": True,
                },
            },
        },
    },
]

# =============================================================================
# COMBINED TOOL SCHEMAS
# =============================================================================

TOOL_SCHEMAS: Dict[str, Any] = {}

# Combine all tool categories
for tool in (
    PROJECT_TOOLS
    + BOARD_TOOLS
    + COMPONENT_TOOLS
    + ROUTING_TOOLS
    + LIBRARY_TOOLS
    + DESIGN_RULE_TOOLS
    + EXPORT_TOOLS
    + SCHEMATIC_TOOLS
    + UI_TOOLS
):
    TOOL_SCHEMAS[tool["name"]] = tool

# Total: 50 tools with comprehensive schemas
