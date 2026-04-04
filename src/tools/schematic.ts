/**
 * Schematic tools for KiCAD MCP server
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

export function registerSchematicTools(server: McpServer, callKicadScript: Function) {
  // Create schematic tool
  server.tool(
    "create_schematic",
    "Create a new schematic",
    {
      name: z.string().describe("Schematic name"),
      path: z.string().optional().describe("Optional path"),
    },
    async (args: { name: string; path?: string }) => {
      const result = await callKicadScript("create_schematic", args);
      if (result.success) {
        const uuidNote = result.schematic_uuid ? `\nschematic_uuid: ${result.schematic_uuid}` : "";
        const templateNote = result.note ? `\n${result.note}` : "";
        return {
          content: [{
            type: "text",
            text: `Created schematic: ${result.file_path}${uuidNote}${templateNote}`,
          }],
        };
      }
      return {
        content: [{
          type: "text",
          text: `Failed to create schematic: ${result.message || JSON.stringify(result)}`,
        }],
      };
    },
  );

  // Add component to schematic
  server.tool(
    "add_schematic_component",
    "Add a component to the schematic. Symbol format is 'Library:SymbolName' (e.g., 'Device:R', 'EDA-MCP:ESP32-C3'). The position is auto-snapped to the KiCAD 50mil (1.27mm) grid. The response includes the snapped position and pin coordinates so a separate get_schematic_pin_locations call is not needed. Use list_symbol_pins to discover pin names before placement. If symbol is not found, close-match suggestions are returned.",
    {
      schematicPath: z.string().describe("Path to the schematic file"),
      symbol: z
        .string()
        .describe("Symbol library:name reference (e.g., Device:R, EDA-MCP:ESP32-C3)"),
      reference: z.string().describe("Component reference (e.g., R1, U1)"),
      value: z.string().optional().describe("Component value"),
      footprint: z.string().optional().describe("KiCAD footprint (e.g. Resistor_SMD:R_0603_1608Metric). Applied directly to the placed instance's Footprint property field — no separate edit_schematic_component call needed."),
      position: z
        .object({
          x: z.number(),
          y: z.number(),
        })
        .optional()
        .describe("Position on schematic"),
      rotation: z.number().optional().describe("Rotation in degrees, CCW positive, multiples of 90 (0, 90, 180, 270). Default 0. Use 90 for horizontal resistors/capacitors in a left-to-right power path."),
      includePins: z.boolean().optional().describe("Return pin coordinates in the response (default false). Set true for ICs where pin coordinate planning is needed."),
    },
    async (args: {
      schematicPath: string;
      symbol: string;
      reference: string;
      value?: string;
      footprint?: string;
      position?: { x: number; y: number };
      rotation?: number;
      includePins?: boolean;
    }) => {
      // Transform to what Python backend expects
      const [library, symbolName] = args.symbol.includes(":")
        ? args.symbol.split(":")
        : ["Device", args.symbol];

      const transformed = {
        schematicPath: args.schematicPath,
        component: {
          library,
          type: symbolName,
          reference: args.reference,
          value: args.value,
          footprint: args.footprint ?? "",
          // Python expects flat x, y not nested position
          x: args.position?.x ?? 0,
          y: args.position?.y ?? 0,
          rotation: args.rotation ?? 0,
          includePins: args.includePins === true,
        },
      };

      const result = await callKicadScript("add_schematic_component", transformed);
      if (result.success) {
        const pos = result.snapped_position;
        const snappedNote = pos
          ? ` (snapped to grid: ${pos.x}, ${pos.y})`
          : "";
        const pins: Record<string, any> = result.pins || {};
        const pinLines = Object.entries(pins).map(
          ([num, p]: [string, any]) =>
            `  Pin ${num} (${p.name}): x=${p.x}, y=${p.y}`,
        );
        const pinSection =
          pinLines.length > 0
            ? `\nPin locations:\n${pinLines.join("\n")}`
            : "";
        const footprintNote = result.footprint ? `\nFootprint: ${result.footprint}` : "";
        return {
          content: [
            {
              type: "text",
              text: `Added ${args.reference} (${args.symbol})${snappedNote}${footprintNote}${pinSection}`,
            },
          ],
        };
      } else {
        return {
          content: [
            {
              type: "text",
              text: `Failed to add component: ${result.message || JSON.stringify(result)}`,
            },
          ],
        };
      }
    },
  );

  // Batch add multiple components in one call
  server.tool(
    "batch_add_components",
    "Place multiple schematic components in a single call. Prefer this over calling add_schematic_component repeatedly — it injects all symbol definitions and creates all instances in one round-trip. Each component uses 'Library:SymbolName' format. If any component fails, the rest are still placed and errors are reported per-component. NOTE: includePins defaults to false and should stay false in almost all cases — batch_connect and connect_to_net accept pin name or number directly and never need pin coordinates. Only set includePins:true if you specifically need absolute schematic coordinates for manual wire routing.\n\noptional origin_x/origin_y: when provided, every per-component position is treated as an mm offset from this origin. Set x=0,y=0 for the anchor component and positive offsets for others. DO NOT mix with absolute coordinates from list_schematic_components — use one coordinate system per call. When not provided positions are absolute sheet coordinates. The response includes a placement_bbox covering all placed components.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
      origin_x: z.number().optional().describe("X coordinate of the placement origin (mm). All per-component x values are offsets from this point. Use x=0 for the anchor component. DO NOT mix with absolute sheet coordinates."),
      origin_y: z.number().optional().describe("Y coordinate of the placement origin (mm). All per-component y values are offsets from this point. Use y=0 for the anchor component. DO NOT mix with absolute sheet coordinates."),
      components: z.array(z.object({
        symbol: z.string().describe("Symbol in 'Library:SymbolName' format (e.g., Device:R, power:GND)"),
        reference: z.string().describe("Reference designator (e.g., R1, C3, U2)"),
        value: z.string().optional().describe("Component value (e.g., 10k, 100nF, AP63203WU-7)"),
        footprint: z.string().optional().describe("KiCAD footprint (e.g., Resistor_SMD:R_0603_1608Metric). Applied directly to the placed instance's Footprint property — no separate edit_schematic_component call needed. A footprint_warning in the response means library validation failed, NOT that the footprint was omitted."),
        position: z.object({ x: z.number(), y: z.number() }).optional().describe("Position in mm. If origin_x/origin_y is set, this is an offset from origin; otherwise absolute sheet coordinates (auto-snapped to 50mil grid)"),
        rotation: z.number().optional().describe("Rotation in degrees CCW, multiples of 90. Use 90 for horizontal resistors/capacitors."),
        includePins: z.boolean().optional().describe("Include pin coordinates in response (default false). Set true for ICs where pin coordinate planning is needed."),
      })).describe("List of components to place"),
    },
    async (args: {
      schematicPath: string;
      origin_x?: number;
      origin_y?: number;
      components: Array<{
        symbol: string;
        reference: string;
        value?: string;
        footprint?: string;
        position?: { x: number; y: number };
        rotation?: number;
        includePins?: boolean;
      }>;
    }) => {
      const result = await callKicadScript("batch_add_components", args);
      if (result.added_count > 0 || result.error_count === 0) {
        const lines: string[] = [`Placed ${result.added_count} component(s)${result.error_count > 0 ? `, ${result.error_count} failed` : ""}:`];
        for (const comp of (result.added || [])) {
          const pos = comp.snapped_position;
          const pinLines = Object.entries(comp.pins || {}).map(
            ([num, p]: [string, any]) => `      Pin ${num} (${p.name}): x=${p.x}, y=${p.y}`
          );
          lines.push(`  ${comp.reference} (${comp.symbol}) @ (${pos?.x}, ${pos?.y})`);
          if (pinLines.length) lines.push(...pinLines);
          if (comp.footprint_warning) lines.push(`      [footprint_warning] ${comp.footprint_warning}`);
          if (comp.pins_error) lines.push(`      [pins_error] ${comp.pins_error}`);
        }
        if (result.placement_bbox) {
          const bb = result.placement_bbox;
          lines.push(`Placement bbox: x=[${bb.x_min}, ${bb.x_max}] y=[${bb.y_min}, ${bb.y_max}]`);
        }
        if (result.errors?.length) {
          lines.push("Errors:");
          result.errors.forEach((e: any) => lines.push(`  ${e.reference} (${e.symbol}): ${e.error}`));
        }
        return { content: [{ type: "text", text: lines.join("\n") }] };
      }
      return {
        content: [{
          type: "text",
          text: `batch_add_components failed: ${result.message || "Unknown error"}\n` +
            (result.errors || []).map((e: any) => `  ${e.reference}: ${e.error}`).join("\n"),
        }],
      };
    },
  );

  // Combined place + connect in one call
  server.tool(
    "batch_add_and_connect",
    `Place multiple schematic components AND assign their net labels in a single round-trip.

This is the preferred tool for subcircuit placement — it replaces the common two-step pattern of batch_add_components followed by batch_connect. Each component accepts an optional \"nets\" field mapping pin numbers/names to net names.

Components without a \"nets\" field are placed but not connected (useful for passive components you plan to connect later, or power symbols).

The response includes placed component positions, connected pin coordinates, and any warnings (e.g. PWR_FLAG suggestions).`,
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
      origin_x: z.number().optional().describe("X coordinate of the placement origin (mm). All per-component x values are offsets from this point."),
      origin_y: z.number().optional().describe("Y coordinate of the placement origin (mm). All per-component y values are offsets from this point."),
      components: z.array(z.object({
        symbol: z.string().describe("Symbol in 'Library:SymbolName' format (e.g., Device:R, power:GND)"),
        reference: z.string().describe("Reference designator (e.g., R1, C3, U2)"),
        value: z.string().optional().describe("Component value (e.g., 10k, 100nF)"),
        footprint: z.string().optional().describe("KiCAD footprint string (e.g., Resistor_SMD:R_0603_1608Metric)"),
        position: z.object({ x: z.number(), y: z.number() }).optional().describe("Position in mm (offset from origin if origin_x/y set, otherwise absolute)"),
        rotation: z.number().optional().describe("Rotation in degrees CCW, multiples of 90"),
        nets: z.record(z.string()).optional().describe("Map of pinNumber/pinName → netName for this component. E.g. {\"1\": \"+5V\", \"2\": \"GND\"}. Omit if not connecting now."),
      })).describe("Components to place and optionally connect"),
    },
    async (args: {
      schematicPath: string;
      origin_x?: number;
      origin_y?: number;
      components: Array<{
        symbol: string;
        reference: string;
        value?: string;
        footprint?: string;
        position?: { x: number; y: number };
        rotation?: number;
        nets?: Record<string, string>;
      }>;
    }) => {
      const result = await callKicadScript("batch_add_and_connect", args);
      const lines: string[] = [result.message || ""];
      for (const comp of (result.added || [])) {
        const pos = comp.snapped_position;
        lines.push(`  ${comp.reference} (${comp.symbol}) @ (${pos?.x}, ${pos?.y})`);
        if (comp.footprint_warning) lines.push(`    [footprint_warning] ${comp.footprint_warning}`);
      }
      if ((result.connected || []).length > 0) {
        lines.push(`Connected pins (${result.connected_count}):`);
        for (const p of (result.connected || [])) {
          const note = p.note ? ` [${p.note}]` : "";
          lines.push(`  ${p.ref}/${p.pin} → ${p.net} @ (${p.position?.x}, ${p.position?.y})${note}`);
        }
      }
      if ((result.errors || []).length > 0) {
        lines.push(`Placement errors:`);
        (result.errors as any[]).forEach((e: any) => lines.push(`  ${e.reference}: ${e.error}`));
      }
      if ((result.failed_connections || []).length > 0) {
        lines.push(`Connection failures:`);
        (result.failed_connections as any[]).forEach((f: any) => lines.push(`  ${f.ref}/${f.pin}: ${f.reason}`));
      }
      if ((result.warnings || []).length > 0) {
        lines.push(`Warnings:`);
        (result.warnings as string[]).forEach((w: string) => lines.push(`  ${w}`));
      }
      if (result.placement_bbox) {
        const bb = result.placement_bbox;
        lines.push(`Placement bbox: x=[${bb.x_min}, ${bb.x_max}] y=[${bb.y_min}, ${bb.y_max}]`);
      }
      return { content: [{ type: "text", text: lines.join("\n") }] };
    },
  );

  // Delete component from schematic
  server.tool(
    "delete_schematic_component",
    `Remove a placed symbol from a KiCAD schematic (.kicad_sch).

This removes the symbol instance (the placed component) from the schematic.
It does NOT remove the symbol definition from lib_symbols.

Note: This tool operates on schematic files (.kicad_sch).
To remove a footprint from a PCB, use delete_component instead.`,
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
      reference: z
        .string()
        .describe("Reference designator of the component to remove (e.g. R1, U3)"),
    },
    async (args: { schematicPath: string; reference: string }) => {
      const result = await callKicadScript("delete_schematic_component", args);
      if (result.success) {
        return {
          content: [
            {
              type: "text",
              text: `Successfully removed ${args.reference} from schematic`,
            },
          ],
        };
      }
      return {
        content: [
          {
            type: "text",
            text: `Failed to remove component: ${result.message || "Unknown error"}`,
          },
        ],
      };
    },
  );

  // Edit component properties in schematic (footprint, value, reference)
  server.tool(
    "edit_schematic_component",
    `Update properties of a placed symbol in a KiCAD schematic (.kicad_sch) in-place.

Use this tool to assign or update a footprint, change the value, or rename the reference
of an already-placed component. This is more efficient than delete + re-add because it
preserves the component's position and UUID.

Note: operates on .kicad_sch files only. To modify a PCB footprint use edit_component.`,
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
      reference: z.string().describe("Current reference designator of the component (e.g. R1, U3)"),
      footprint: z
        .string()
        .optional()
        .describe("New KiCAD footprint string (e.g. Resistor_SMD:R_0603_1608Metric)"),
      value: z.string().optional().describe("New value string (e.g. 10k, 100nF)"),
      newReference: z
        .string()
        .optional()
        .describe("Rename the reference designator (e.g. R1 → R10)"),
      fieldPositions: z
        .record(
          z.object({
            x: z.number(),
            y: z.number(),
            angle: z.number().optional().default(0),
          }),
        )
        .optional()
        .describe(
          'Reposition field labels: map of field name to {x, y, angle} (e.g. {"Reference": {"x": 12.5, "y": 17.0}})',
        ),
    },
    async (args: {
      schematicPath: string;
      reference: string;
      footprint?: string;
      value?: string;
      newReference?: string;
      fieldPositions?: Record<string, { x: number; y: number; angle?: number }>;
    }) => {
      const result = await callKicadScript("edit_schematic_component", args);
      if (result.success) {
        const changes = Object.entries(result.updated ?? {})
          .map(([k, v]) => `${k}=${v}`)
          .join(", ");
        return {
          content: [
            {
              type: "text" as const,
              text: `Successfully updated ${args.reference}: ${changes}`,
            },
          ],
        };
      }
      return {
        content: [
          {
            type: "text" as const,
            text: `Failed to edit component: ${result.message || "Unknown error"}`,
          },
        ],
      };
    },
  );

  // Batch edit multiple component properties in one call
  server.tool(
    "batch_edit_schematic_components",
    `Update properties of multiple placed symbols in a KiCAD schematic in a single call.

Use this instead of calling edit_schematic_component repeatedly — all edits are applied
in one round-trip. Each component entry can set footprint, value, and/or newReference.

Example: {"J1": {"footprint": "Connector_USB:USB_C_Receptacle_GCT_USB4135"}, "C3": {"footprint": "Capacitor_SMD:C_0402"}}`,
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
      components: z.record(z.object({
        footprint: z.string().optional().describe("New KiCAD footprint string"),
        value: z.string().optional().describe("New value string (e.g. 10k, 100nF)"),
        newReference: z.string().optional().describe("Rename the reference designator"),
      })).describe("Map of current reference → properties to update"),
    },
    async (args: {
      schematicPath: string;
      components: Record<string, { footprint?: string; value?: string; newReference?: string }>;
    }) => {
      const result = await callKicadScript("batch_edit_schematic_components", args);
      if (result.success || result.updated_count > 0) {
        const lines: string[] = [
          `Updated ${result.updated_count} component(s)${result.error_count > 0 ? `, ${result.error_count} failed` : ""}:`,
        ];
        for (const [ref, changes] of Object.entries(result.updated ?? {})) {
          const changeStr = Object.entries(changes as Record<string, unknown>)
            .map(([k, v]) => `${k}=${v}`)
            .join(", ");
          lines.push(`  ${ref}: ${changeStr}`);
        }
        if (result.errors?.length) {
          lines.push("Errors:");
          result.errors.forEach((e: any) => lines.push(`  ${e.reference}: ${e.error}`));
        }
        return { content: [{ type: "text" as const, text: lines.join("\n") }] };
      }
      return {
        content: [{
          type: "text" as const,
          text: `batch_edit_schematic_components failed: ${result.message || "Unknown error"}\n` +
            (result.errors || []).map((e: any) => `  ${e.reference}: ${e.error}`).join("\n"),
        }],
      };
    },
  );

  // Get component properties and field positions from schematic
  server.tool(
    "get_schematic_component",
    "Get full component info from a schematic: position, field values, and each field's label position (at x/y/angle). Use this to inspect or prepare repositioning of Reference/Value labels.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
      reference: z.string().describe("Component reference designator (e.g. R1, U1)"),
    },
    async (args: { schematicPath: string; reference: string }) => {
      const result = await callKicadScript("get_schematic_component", args);
      if (result.success) {
        const pos = result.position
          ? `(${result.position.x}, ${result.position.y}, angle=${result.position.angle}°)`
          : "unknown";
        const fieldLines = Object.entries(result.fields ?? {}).map(
          ([name, f]: [string, any]) =>
            `  ${name}: "${f.value}" @ (${f.x}, ${f.y}, angle=${f.angle}°)`,
        );
        return {
          content: [
            {
              type: "text",
              text: `Component ${result.reference} at ${pos}\nFields:\n${fieldLines.join("\n")}`,
            },
          ],
        };
      }
      return {
        content: [
          {
            type: "text",
            text: `Failed to get component: ${result.message || "Unknown error"}`,
          },
        ],
      };
    },
  );

  // Draw wire between coordinate waypoints with optional pin snapping
  server.tool(
    "add_schematic_wire",
    "Draws a wire on the schematic between two or more coordinate points. Always call get_schematic_pin_locations first to get the approximate pin coordinates, then pass them as the first and last waypoints. snapToPins (on by default) will correct any float imprecision by snapping endpoints to the exact nearest pin coordinate. To route around components, add intermediate waypoints between the start and end: e.g. [[x1,y1], [xMid,y1], [xMid,y2], [x2,y2]] routes horizontally then vertically. Intermediate waypoints are never snapped.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
      waypoints: z
        .array(z.array(z.number()).length(2))
        .min(2)
        .describe("Ordered list of [x, y] coordinates. Minimum 2 points."),
      snapToPins: z
        .boolean()
        .optional()
        .describe("Snap the first and last waypoints to the nearest pin (default: true)"),
      snapTolerance: z.number().optional().describe("Maximum snap distance in mm (default: 1.0)"),
    },
    async (args: {
      schematicPath: string;
      waypoints: number[][];
      snapToPins?: boolean;
      snapTolerance?: number;
    }) => {
      const result = await callKicadScript("add_schematic_wire", args);
      if (result.success) {
        return {
          content: [
            {
              type: "text" as const,
              text: result.message || "Wire added successfully",
            },
          ],
        };
      } else {
        return {
          content: [
            {
              type: "text" as const,
              text: `Failed to add wire: ${result.message || "Unknown error"}`,
            },
          ],
        };
      }
    },
  );

  // Add junction dot at a T/X intersection
  server.tool(
    "add_schematic_junction",
    "Place a junction dot at a wire intersection in the schematic. Required at T-branch and X-cross points so KiCAD recognises the electrical connection.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
      position: z.array(z.number()).length(2).describe("Junction position [x, y] in mm"),
    },
    async (args: { schematicPath: string; position: number[] }) => {
      const result = await callKicadScript("add_schematic_junction", args);
      if (result.success) {
        return {
          content: [
            {
              type: "text" as const,
              text: result.message || "Junction added successfully",
            },
          ],
        };
      } else {
        return {
          content: [
            {
              type: "text" as const,
              text: `Failed to add junction: ${result.message || "Unknown error"}`,
            },
          ],
        };
      }
    },
  );

  // Add net label
  server.tool(
    "add_schematic_net_label",
    `Add a net label to the schematic at a pin tip location.

IMPORTANT — Power nets: For standard power nets (GND, +5V, +3V3, VBUS, +3.3V, etc.), strongly
prefer using a power symbol via add_schematic_component (e.g., kicad_power:GND, kicad_power:+5V)
rather than a net label. Power symbols always render upright and follow standard schematic
conventions. Use net labels only for signal nets (USB_DM, BUCK_SW, SDA, etc.) that don't have
a dedicated power symbol.

Parameters:
  net    — net name string (e.g. 'GND', '+3V3', 'BUCK_SW')
  x, y   — exact pin tip coordinates in mm (same as the pin's connection point — no offset needed)
  angle  — direction the label text extends FROM the pin tip (default: 0):
             0   = rightward  → use for right-edge pins (pin stub exits →)
             90  = upward     → use for top-edge pins (pin stub exits ↑)
             180 = leftward   → use for left-edge pins (pin stub exits ←)
             270 = downward   → use for bottom-edge pins (pin stub exits ↓)
  justify — text anchor (default: auto-derived from angle):
             'left'  — text starts at connection point, extends in label direction
             'right' — text ends at connection point (correct for angle=180)

Angle/justify quick reference:
  Left-edge pin   (wire exits ←): angle=180, justify=right
  Right-edge pin  (wire exits →): angle=0,   justify=left
  Top-edge pin    (wire exits ↑): angle=90,  justify=left
  Bottom-edge pin (wire exits ↓): angle=270, justify=left

NOTE: Labels with angle=90/270 (top/bottom-edge pins) render with text rotated — this is
standard KiCad behavior and cannot be changed via justify.

PREFER connect_to_net or batch_connect: these tools auto-derive angle from the pin direction
so you never need to look up the table above.

The x,y coordinates are written exactly as provided (snapped only to KiCad's 50mil grid).
Do NOT add any wire between the component pin and the label when the label is placed directly
at the pin tip. A label exactly coinciding with a pin tip is a valid KiCad connection. Only
add a wire if there is a gap between the pin tip and the desired label position.`,
    {
      schematicPath: z.string().describe("Path to the schematic file"),
      netName: z
        .string()
        .describe("Name of the net (e.g., VCC, GND, SIGNAL_1)"),
      position: z
        .array(z.number())
        .length(2)
        .describe("Position [x, y] for the label — exact pin tip coordinates in mm"),
      angle: z
        .number()
        .optional()
        .describe("Direction label extends from pin: 0=right, 90=down, 180=left, 270=up (default: 0)"),
      justify: z
        .enum(["left", "right", "center"])
        .optional()
        .describe("Text justification (default: auto-derived from angle; 180→right, others→left)"),
    },
    async (args: {
      schematicPath: string;
      netName: string;
      position: number[];
      angle?: number;
      justify?: string;
    }) => {
      const result = await callKicadScript("add_schematic_net_label", args);
      if (result.success) {
        return {
          content: [
            {
              type: "text",
              text: `Successfully added net label '${args.netName}' at position [${args.position}]`,
            },
          ],
        };
      } else {
        return {
          content: [
            {
              type: "text",
              text: `Failed to add net label: ${result.message || "Unknown error"}`,
            },
          ],
        };
      }
    },
  );

  // Move a symbol's Reference or Value property field
  server.tool(
    "set_schematic_property_position",
    `Move a symbol's Reference or Value property field to a specific schematic coordinate.
Use this after component placement to avoid overlapping text.

Parameters:
  schematicPath — path to the .kicad_sch file
  reference     — component reference designator (e.g. 'F1', 'U6', 'C3')
  property      — which field to move: 'Reference' or 'Value'
  x, y          — new absolute schematic coordinates in mm
  angle         — text rotation in degrees (default: 0 = horizontal/readable). Text angle
                  should almost always be 0 regardless of the symbol's rotation. Rotated
                  text on Reference/Value fields is nearly always an error. Only pass a
                  non-zero angle if you have a specific reason.
  visible       — whether the field is visible (default: true)

The tool writes the new position into the matching symbol's property in the .kicad_sch file.
It does NOT move the symbol body, only the property text field.
It does NOT auto-save; call save_schematic after all repositioning is done.`,
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
      reference: z.string().describe("Component reference designator (e.g. 'F1', 'U6', 'C3')"),
      property: z.enum(["Reference", "Value"]).describe("Which field to move"),
      x: z.number().describe("New X coordinate in mm"),
      y: z.number().describe("New Y coordinate in mm"),
      angle: z.number().optional().describe("Text rotation in degrees (default: 0 = horizontal). Almost always use 0 — rotated ref/val text is nearly always an error."),
      visible: z.boolean().optional().describe("Whether the field is visible (default: true)"),
    },
    async (args: {
      schematicPath: string;
      reference: string;
      property: "Reference" | "Value";
      x: number;
      y: number;
      angle?: number;
      visible?: boolean;
    }) => {
      const result = await callKicadScript("set_schematic_property_position", args);
      if (result.success) {
        return { content: [{ type: "text", text: result.message }] };
      }
      return {
        content: [{ type: "text", text: `Failed to set property position: ${result.message || "Unknown error"}` }],
        isError: true,
      };
    },
  );

  // Connect pin to net — places label directly at pin endpoint (no wire stub needed)
  server.tool(
    "connect_to_net",
    "Place a net label at a component pin endpoint to connect it to a named net. The label is placed exactly at the pin coordinate so KiCAD recognises the connection. No wire stub is needed. PREFERRED method for assigning nets to pins.",
    {
      schematicPath: z.string().describe("Path to the schematic file"),
      componentRef: z.string().describe("Component reference (e.g., U1, R1)"),
      pinName: z.string().describe("Pin name or number to connect (e.g., '1', 'GND', 'SDA')"),
      netName: z.string().describe("Name of the net to connect to (e.g., VCC, GND, SDA)"),
    },
    async (args: {
      schematicPath: string;
      componentRef: string;
      pinName: string;
      netName: string;
    }) => {
      // Use place_net_label_at_pin which places the label directly at the pin endpoint
      const result = await callKicadScript("place_net_label_at_pin", {
        schematicPath: args.schematicPath,
        reference: args.componentRef,
        pinNumber: args.pinName,
        netName: args.netName,
      });
      if (result.success) {
        return {
          content: [
            {
              type: "text",
              text: `Connected ${args.componentRef}/${args.pinName} to net '${args.netName}' at (${result.position?.x}, ${result.position?.y})`,
            },
          ],
        };
      } else {
        return {
          content: [
            {
              type: "text",
              text: `Failed to connect to net: ${result.message || "Unknown error"}`,
            },
          ],
        };
      }
    },
  );

  // Place net label directly at a pin endpoint
  server.tool(
    "place_net_label_at_pin",
    "Place a net label at the exact endpoint of a component pin. The label position and orientation are computed automatically from the pin's location and angle. This is the low-level version of connect_to_net — use connect_to_net for most cases.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
      reference: z.string().describe("Component reference designator (e.g. J1, U1)"),
      pinNumber: z.string().describe("Pin number or name (e.g. '1', 'GND', 'SDA')"),
      netName: z.string().describe("Net name to assign (e.g. VCC, GND, SIGNAL_1)"),
    },
    async (args: { schematicPath: string; reference: string; pinNumber: string; netName: string }) => {
      const result = await callKicadScript("place_net_label_at_pin", args);
      if (result.success) {
        return {
          content: [{
            type: "text",
            text: `Placed label '${args.netName}' on ${args.reference}/${args.pinNumber} at (${result.position?.x}, ${result.position?.y})`,
          }],
        };
      }
      return {
        content: [{
          type: "text",
          text: `Failed to place label: ${result.message || "Unknown error"}`,
        }],
      };
    },
  );

  // Add no-connect marker to a pin
  server.tool(
    "add_no_connect",
    "Mark a pin as intentionally unconnected (adds an X marker). This suppresses ERC 'Pin not connected' errors for pins that are deliberately left unconnected (e.g., NC/DNP pins, unused GPIO, SBU pins on USB-C). Use get_schematic_pin_locations to get pin coordinates first, or provide componentRef+pinName for automatic lookup.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
      componentRef: z.string().optional().describe("Component reference (e.g. J1, U1) — provide with pinName for auto lookup"),
      pinName: z.string().optional().describe("Pin name or number (e.g. '1', 'SBU1') — provide with componentRef for auto lookup"),
      position: z.object({ x: z.number(), y: z.number() }).optional().describe("Explicit pin position — use if you already know the coordinates"),
    },
    async (args: {
      schematicPath: string;
      componentRef?: string;
      pinName?: string;
      position?: { x: number; y: number };
    }) => {
      const result = await callKicadScript("add_no_connect", {
        schematicPath: args.schematicPath,
        componentRef: args.componentRef,
        pinName: args.pinName,
        position: args.position ? [args.position.x, args.position.y] : undefined,
      });
      if (result.success) {
        return {
          content: [{
            type: "text",
            text: result.message || `Added no-connect marker`,
          }],
        };
      }
      return {
        content: [{
          type: "text",
          text: `Failed to add no-connect: ${result.message || "Unknown error"}`,
        }],
      };
    },
  );

  // List all unconnected pins
  server.tool(
    "list_unconnected_pins",
    "List all pins that have no net connection and no no-connect marker. Use this after wiring to identify which pins still need to be connected or marked NC. Returns component ref, pin number, pin name, pin type, and position for each unconnected pin. NOTE: reads netlist from the saved file; results may differ from kicad-cli ERC if the skip library computes connectivity differently — use run_erc for the authoritative answer.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
    },
    async (args: { schematicPath: string }) => {
      const result = await callKicadScript("list_unconnected_pins", args);
      if (result.success) {
        const pins: any[] = result.unconnected || [];
        if (pins.length === 0) {
          return { content: [{ type: "text", text: "All pins are connected or marked no-connect." }] };
        }
        const lines = pins.map(
          (p: any) => `  ${p.reference}/${p.pinName || p.pinNumber} (pin ${p.pinNumber}, type=${p.pinType}) @ (${p.position.x}, ${p.position.y})`
        );
        return {
          content: [{
            type: "text",
            text: `Unconnected pins (${pins.length}):\n${lines.join("\n")}`,
          }],
        };
      }
      return {
        content: [{ type: "text", text: `Failed to list unconnected pins: ${result.message || "Unknown error"}` }],
        isError: true,
      };
    },
  );

  // Get net connections
  server.tool(
    "get_net_connections",
    "Get all connections for a named net",
    {
      schematicPath: z.string().describe("Path to the schematic file"),
      netName: z.string().describe("Name of the net to query"),
    },
    async (args: { schematicPath: string; netName: string }) => {
      const result = await callKicadScript("get_net_connections", args);
      if (result.success && result.connections) {
        const connectionList = result.connections
          .map((conn: any) => `  - ${conn.component}/${conn.pin}`)
          .join("\n");
        return {
          content: [
            {
              type: "text",
              text: `Net '${args.netName}' connections:\n${connectionList}`,
            },
          ],
        };
      } else {
        return {
          content: [
            {
              type: "text",
              text: `Failed to get net connections: ${result.message || "Unknown error"}`,
            },
          ],
        };
      }
    },
  );

  // Get wire connections
  server.tool(
    "get_wire_connections",
    "Find all component pins reachable from a schematic point via connected wires, net labels, and power symbols. The query point must be at a wire endpoint or junction — midpoints of wire segments are not matched. Use get_schematic_pin_locations or list_schematic_wires to obtain exact endpoint coordinates first.",
    {
      schematicPath: z.string().describe("Path to the schematic file"),
      x: z.number().describe("X coordinate of a wire endpoint or junction"),
      y: z.number().describe("Y coordinate of a wire endpoint or junction"),
    },
    async (args: { schematicPath: string; x: number; y: number }) => {
      const result = await callKicadScript("get_wire_connections", args);
      if (result.success && result.pins) {
        const pinList = result.pins.map((p: any) => `  - ${p.component}/${p.pin}`).join("\n");
        const wireList = (result.wires ?? [])
          .map((w: any) => `  - (${w.start.x},${w.start.y}) → (${w.end.x},${w.end.y})`)
          .join("\n");
        return {
          content: [
            {
              type: "text",
              text: `Pins connected at (${args.x},${args.y}):\n${pinList || "  (none found)"}\n\nWire segments:\n${wireList || "  (none)"}`,
            },
          ],
        };
      } else {
        return {
          content: [
            {
              type: "text",
              text: `Failed to get wire connections: ${result.message || "Unknown error"}`,
            },
          ],
        };
      }
    },
  );

  // Get pin locations for one or more schematic components
  server.tool(
    "get_schematic_pin_locations",
    "Returns the schematic coordinates of each pin's connection point — the tip of the pin stub where wires and net labels attach. These coordinates can be passed directly to add_wire, add_schematic_net_label, and add_schematic_connection without any offset.\n\nPass a single 'reference' or a list of 'references' to batch multiple components in one call — strongly prefer the batch form to avoid many round-trips.\n\nCoordinate convention: returned x/y are absolute schematic coordinates (Y-axis points DOWN). The Y-axis flip between symbol library space (Y-up) and schematic space (Y-down) is applied automatically by the underlying library — do NOT manually compute pin_schematic_y = component_y ± pin_symbol_y.\n\nEach pin includes near_boundary=true when within 20mm of the left or top sheet edge, plus suggested_component_x_offset indicating how far right to shift the component so leftward labels stay in bounds.\n\nNOTE: For components placed in the same session (not yet opened in KiCad), this tool may return empty results because the skip parser cannot always read MCP-generated files. In that case use batch_connect or connect_to_net which look up pin positions internally and do NOT require calling this tool first.",
    {
      schematicPath: z.string().describe("Path to the schematic file"),
      reference: z.string().optional().describe("Single component reference (e.g. U1). Use 'references' for batch."),
      references: z.array(z.string()).optional().describe("List of component references to look up in one call (e.g. ['J1','U6','D1'])"),
    },
    async (args: { schematicPath: string; reference?: string; references?: string[] }) => {
      const refs = args.references ?? (args.reference ? [args.reference] : []);
      if (refs.length === 0) {
        return { content: [{ type: "text", text: "Provide 'reference' or 'references'." }] };
      }

      const result = await callKicadScript("get_schematic_pin_locations", {
        schematicPath: args.schematicPath,
        references: refs,
      });

      if (result.success) {
        // Batch result: result.components is a map of ref → pins
        const components: Record<string, any> = result.components || {};
        // Fallback for single-ref old format
        if (Object.keys(components).length === 0 && result.pins && refs.length === 1) {
          components[refs[0]] = result.pins;
        }
        const sections: string[] = [];
        for (const [ref, pins] of Object.entries(components)) {
          const lines = Object.entries(pins as Record<string, any>).map(
            ([pinNum, data]: [string, any]) => {
              let s = `    Pin ${pinNum} (${data.name || pinNum}): x=${data.x}, y=${data.y}`;
              if (data.near_boundary) {
                s += ` [NEAR_BOUNDARY`;
                if (data.suggested_component_x_offset != null) {
                  s += ` — move component right by ${data.suggested_component_x_offset}mm to keep labels in bounds`;
                }
                s += `]`;
              }
              return s;
            }
          );
          sections.push(`${ref}:\n${lines.join("\n")}`);
        }
        return {
          content: [{
            type: "text",
            text: sections.join("\n\n"),
          }],
        };
      } else {
        return {
          content: [
            {
              type: "text",
              text: `Failed to get pin locations: ${result.message || "Unknown error"}`,
            },
          ],
        };
      }
    },
  );

  // Batch connect: place net labels on multiple pins in one call
  server.tool(
    "batch_connect",
    "Place net labels on multiple component pins in a single call. Accepts a map of {componentRef: {pinNumber: netName}} and places all labels in one round-trip. Use this instead of calling connect_to_net repeatedly — it is dramatically more token-efficient for wiring many pins at once. Set replace=true to atomically replace any existing label at each pin tip (useful when correcting wrong-net assignments without a separate delete step).",
    {
      schematicPath: z.string().describe("Path to the schematic file"),
      connections: z
        .record(
          z.record(z.string()).describe("Map of pinNumber -> netName for this component")
        )
        .describe(
          "Map of componentRef -> {pinNumber: netName}. " +
          "Example: {\"J1\": {\"1\": \"VCC\", \"2\": \"GND\"}, \"U1\": {\"VDD\": \"VCC\"}}"
        ),
      replace: z.boolean().optional().describe("If true, delete any existing net label at each pin tip before placing the new one. Use when correcting wrong-net assignments — eliminates the separate delete_schematic_net_label step."),
    },
    async (args: { schematicPath: string; connections: Record<string, Record<string, string>>; replace?: boolean }) => {
      const result = await callKicadScript("batch_connect", args);
      const placed: any[] = result.placed || [];
      const failed: any[] = result.failed || [];
      const total = placed.length + failed.length;
      if (failed.length === 0) {
        // Full success — summary only, no per-pin noise
        return { content: [{ type: "text", text: `${placed.length}/${total} labels placed.` }] };
      }
      // Partial or full failure — show only failures
      const lines: string[] = [`${placed.length}/${total} labels placed.`];
      lines.push(`Failed (${failed.length}):`);
      failed.forEach((f: any) => lines.push(`  ${f.ref}/${f.pin}: ${f.reason}`));
      return { content: [{ type: "text", text: lines.join("\n") }] };
    },
  );

  // Connect all pins of source connector to matching pins of target connector (passthrough)
  server.tool(
    "connect_passthrough",
    "Connects all pins of a source connector (e.g. J1) to matching pins of a target connector (e.g. J2) via shared net labels — pin N gets net '{netPrefix}_{N}'. Use this for FFC/ribbon cable passthrough adapters instead of calling connect_to_net for every pin.",
    {
      schematicPath: z.string().describe("Path to the schematic file"),
      sourceRef: z.string().describe("Source connector reference (e.g. J1)"),
      targetRef: z.string().describe("Target connector reference (e.g. J2)"),
      netPrefix: z
        .string()
        .optional()
        .describe("Net name prefix, e.g. 'CSI' → CSI_1, CSI_2 (default: PIN)"),
      pinOffset: z
        .number()
        .optional()
        .describe("Add to pin number when building net name (default: 0)"),
    },
    async (args: {
      schematicPath: string;
      sourceRef: string;
      targetRef: string;
      netPrefix?: string;
      pinOffset?: number;
    }) => {
      const result = await callKicadScript("connect_passthrough", args);
      if (result.success !== false || (result.connected && result.connected.length > 0)) {
        const lines: string[] = [];
        if (result.connected?.length)
          lines.push(
            `Connected (${result.connected.length}): ${result.connected.slice(0, 5).join(", ")}${result.connected.length > 5 ? " ..." : ""}`,
          );
        if (result.failed?.length)
          lines.push(`Failed (${result.failed.length}): ${result.failed.join(", ")}`);
        return {
          content: [{ type: "text", text: result.message + "\n" + lines.join("\n") }],
        };
      } else {
        return {
          content: [
            {
              type: "text",
              text: `Passthrough failed: ${result.message || "Unknown error"}`,
            },
          ],
        };
      }
    },
  );

  // List all components in schematic
  server.tool(
    "list_schematic_components",
    "List all components in a schematic with their references, values, positions, pins, and property field positions. Essential for inspecting what's on the schematic before making edits. Each component includes ref_field and value_field with {x, y, angle, visible} for the Reference and Value text positions, and body_bbox with {x_min, y_min, x_max, y_max} for the symbol body bounding box (not including ref/val text). Set compact=true to omit field positions, properties, and bounds — returns only ref, libId, value, position, rotation, pin_count, body_bbox for faster review.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
      filter: z
        .object({
          libId: z.string().optional().describe("Filter by library ID (e.g., 'Device:R')"),
          referencePrefix: z
            .string()
            .optional()
            .describe("Filter by reference prefix (e.g., 'R', 'C', 'U')"),
        })
        .optional()
        .describe("Optional filters"),
      compact: z.boolean().optional().describe("If true, omit ref_field, value_field, properties, and bounds — returns only the essentials for design review"),
    },
    async (args: {
      schematicPath: string;
      filter?: { libId?: string; referencePrefix?: string };
      compact?: boolean;
    }) => {
      const result = await callKicadScript("list_schematic_components", args);
      if (result.success) {
        const comps = result.components || [];
        if (comps.length === 0) {
          return {
            content: [{ type: "text", text: "No components found in schematic." }],
          };
        }
        const lines = comps.map((c: any) => {
          let line = `  ${c.reference}: ${c.libId} = "${c.value}" at (${c.position.x}, ${c.position.y}) rot=${c.rotation}°${c.pins ? ` [${c.pins.length} pins]` : ""}`;
          if (!args.compact) {
            if (c.ref_field) line += ` ref@(${c.ref_field.x},${c.ref_field.y})`;
            if (c.value_field) line += ` val@(${c.value_field.x},${c.value_field.y})`;
          }
          if (c.body_bbox) line += ` bbox=[${c.body_bbox.x_min},${c.body_bbox.y_min},${c.body_bbox.x_max},${c.body_bbox.y_max}]`;
          return line;
        });
        return {
          content: [
            {
              type: "text",
              text: `Components (${comps.length}):\n${lines.join("\n")}`,
            },
          ],
        };
      }
      return {
        content: [
          {
            type: "text",
            text: `Failed to list components: ${result.message || "Unknown error"}`,
          },
        ],
        isError: true,
      };
    },
  );

  // Check schematic layout for violations
  server.tool(
    "check_schematic_layout",
    `Analyze a .kicad_sch file and return a list of layout violations. Checks:
  1. Out-of-bounds components: symbol body bbox extends outside the sheet's usable drawing area.
  2. Out-of-bounds labels: net label text endpoint (estimated from text length × 1.5mm/char and angle) extends outside sheet border.
  3. Overlapping component bodies: two symbols whose body bboxes overlap or are within 2mm of each other.
  4. Ref/Val text inside parent body: Reference or Value text position falls within the parent symbol's body bbox.
  5. Ref/Val text overlapping another component's body: Reference or Value text position falls within a different symbol's body bbox.
  6. Field text overlap: the estimated bounding box of one component's Reference or Value text overlaps that of another component's field text (catches stacked power flags, etc.).
  7. Label overlap: two net labels whose estimated text bounding boxes overlap or are within 0.5mm of each other — indicates components placed too close on a shared bus, or opposing labels on adjacent pin tips that need more separation.
  8. Stray wire: a wire segment whose endpoint(s) have no connection (no pin, label, junction, or other wire) — typically left over after deleting a component.

Returns structured violations with type, affected_refs, position, and description. Zero violations means the layout is clean.
Call this after batch_add_components or set_schematic_property_position to get programmatic feedback instead of relying on visual inspection.

Set autofix=true to automatically apply all fixable violations (text_inside_parent_body, field_text_overlap) in a single batch operation — eliminates the check→fix loop entirely.

PREFERRED: call autoplace_schematic_fields after all net labels are placed — it handles all field positioning in one pass and accounts for net label extents, which autofix does not.`,
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
      autofix: z.boolean().optional().describe("If true, automatically apply all violations that have a suggested_fix (text_inside_parent_body, field_text_overlap) in one batch call. Returns autofix_applied_count and remaining violations."),
    },
    async (args: { schematicPath: string; autofix?: boolean }) => {
      const result = await callKicadScript("check_schematic_layout", args);
      if (result.success) {
        const violations: any[] = result.violations || [];
        const lines: string[] = [];
        if (args.autofix && (result.autofix_applied_count ?? 0) > 0) {
          lines.push(`Auto-fixed ${result.autofix_applied_count} violation(s).`);
          if ((result.autofix_failed_count ?? 0) > 0) {
            lines.push(`  (${result.autofix_failed_count} fix(es) failed)`);
          }
        }
        if (violations.length === 0) {
          lines.push("Layout check passed — no violations found.");
          return { content: [{ type: "text", text: lines.join("\n") }] };
        }
        lines.push(`Layout violations (${violations.length}):`);
        for (const v of violations) {
          const refs = (v.affected_refs || []).join(", ");
          const pos = v.position ? ` @ (${v.position.x}, ${v.position.y})` : "";
          const fix = v.suggested_fix ? ` [fix: move ${v.suggested_fix.reference}.${v.suggested_fix.property} to (${v.suggested_fix.x},${v.suggested_fix.y})]` : "";
          const del_ = v.suggested_delete_label
            ? ` [fix: delete_schematic_net_label net='${v.suggested_delete_label.net}' @ (${v.suggested_delete_label.position.x},${v.suggested_delete_label.position.y})]`
            : "";
          lines.push(`  [${v.type}] ${refs}${pos}: ${v.description}${fix}${del_}`);
        }
        const area = result.sheet_usable_area;
        if (area) {
          lines.push(`Sheet usable area: x=[${area.left}, ${area.right}] y=[${area.top}, ${area.bottom}]`);
        }
        return {
          content: [{ type: "text", text: lines.join("\n") }],
        };
      }
      return {
        content: [{ type: "text", text: `check_schematic_layout failed: ${result.message || "Unknown error"}` }],
        isError: true,
      };
    },
  );

  // Auto-place Reference/Value fields outside body and labels
  server.tool(
    "autoplace_schematic_fields",
    `Reposition Reference and Value fields for all (or selected) components so they sit outside:
  1. The component's body bounding box.
  2. Any net labels whose connection point is at one of the component's pin tips.

Call this AFTER all net labels have been connected (i.e., after batch_connect, connect_to_net,
or batch_add_and_connect). Do NOT call it before nets are assigned — it needs the labels to be
present to avoid them.

The tool uses KiCad's 50-mil grid for all positions and writes one file update for all
components in a single pass. Prefer this over manually calling set_schematic_property_position
or batch_set_schematic_property_positions after placement.

Parameters:
  schematicPath — path to the .kicad_sch file
  references    — optional list of reference designators to limit scope (default: all components)
  clearance     — minimum gap in mm between the component's occupied zone and the field text
                  (default: 1.0 mm)`,
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
      references: z.array(z.string()).optional().describe("Limit to these component references (default: all components)"),
      clearance: z.number().optional().describe("Gap in mm between occupied zone and field text centre (default: 1.0)"),
    },
    async (args: { schematicPath: string; references?: string[]; clearance?: number }) => {
      const result = await callKicadScript("autoplace_schematic_fields", args);
      if (result.success) {
        const lines = [result.message || "Fields auto-placed."];
        if ((result.failed || []).length > 0) {
          lines.push("Failed updates:");
          (result.failed as any[]).forEach((f: any) => lines.push(`  ${f.reference}.${f.property}: ${f.reason}`));
        }
        return { content: [{ type: "text", text: lines.join("\n") }] };
      }
      return {
        content: [{ type: "text", text: `autoplace_schematic_fields failed: ${result.message || "Unknown error"}` }],
        isError: true,
      };
    },
  );

  // List all nets in schematic
  server.tool(
    "list_schematic_nets",
    "List all NAMED nets in the schematic with their connections. WARNING: Only lists nets that have at least one local or global net label. Pins connected via unlabeled wire segments will NOT appear — use list_schematic_wires to verify physical connectivity, or get_net_topology for a full trace of a specific net.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
    },
    async (args: { schematicPath: string }) => {
      const result = await callKicadScript("list_schematic_nets", args);
      if (result.success) {
        const nets = result.nets || [];
        if (nets.length === 0) {
          return {
            content: [{ type: "text", text: "No nets found in schematic." }],
          };
        }
        const lines = nets.map((n: any) => {
          const conns = (n.connections || [])
            .map((c: any) => {
              const pinNum = String(c.pin);
              const pinLabel = c.pinName && c.pinName !== pinNum ? `${pinNum}(${c.pinName})` : pinNum;
              return `${c.component}/${pinLabel}`;
            })
            .join(", ");
          return `  ${n.name}: ${conns || "(no connections)"}`;
        });
        return {
          content: [
            {
              type: "text",
              text: `Nets (${nets.length}):\n${lines.join("\n")}`,
            },
          ],
        };
      }
      return {
        content: [
          { type: "text", text: `Failed to list nets: ${result.message || "Unknown error"}` },
        ],
        isError: true,
      };
    },
  );

  // List all wires in schematic
  server.tool(
    "list_schematic_wires",
    "List wires in the schematic with start/end coordinates. Use netName to filter to only wires reachable from a specific named net (BFS from that net's labels) — turns the flat wire dump into a targeted connectivity trace.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
      netName: z.string().optional().describe("If provided, return only wire segments reachable from this net's labels (local or global)"),
    },
    async (args: { schematicPath: string; netName?: string }) => {
      const result = await callKicadScript("list_schematic_wires", args);
      if (result.success) {
        const wires = result.wires || [];
        if (wires.length === 0) {
          return {
            content: [{ type: "text", text: "No wires found in schematic." }],
          };
        }
        const lines = wires.map(
          (w: any) => `  (${w.start.x}, ${w.start.y}) → (${w.end.x}, ${w.end.y})`,
        );
        return {
          content: [
            {
              type: "text",
              text: `Wires (${wires.length}):\n${lines.join("\n")}`,
            },
          ],
        };
      }
      return {
        content: [
          { type: "text", text: `Failed to list wires: ${result.message || "Unknown error"}` },
        ],
        isError: true,
      };
    },
  );

  // List all labels in schematic
  server.tool(
    "list_schematic_labels",
    "List all net labels, global labels, power flags, and no-connect markers in the schematic. Types returned: [net] = local net label, [global] = global label, [power] = power symbol instance (e.g. PWR_FLAG, not a net label), [no_connect] = unconnected pin marker. Use filter.componentRef to see only labels near a specific component's pins (within 3mm of any pin tip) — avoids the full 50+ label dump when debugging one component. Set useBodyBox=true to instead return all labels within the component's body bounding box expanded by bodyBoxExpand mm.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
      filter: z.object({
        netName: z.string().optional().describe("Return only labels whose name exactly matches this net name"),
        componentRef: z.string().optional().describe("Return only labels near the pin tips of this component (within 3mm). Most efficient way to inspect one component's connections."),
        useBodyBox: z.boolean().optional().describe("When true, use body bounding box (pin extents + bodyBoxExpand) instead of per-pin radius for componentRef filter"),
        bodyBoxExpand: z.number().optional().describe("Expand the body bounding box by this many mm on each side when useBodyBox=true (default: 2.0)"),
        boundingBox: z.object({
          x_min: z.number(), y_min: z.number(),
          x_max: z.number(), y_max: z.number(),
        }).optional().describe("Return only labels whose position falls within this bounding box (mm)"),
      }).optional().describe("Optional filters to narrow results"),
    },
    async (args: { schematicPath: string; filter?: { netName?: string; componentRef?: string; useBodyBox?: boolean; bodyBoxExpand?: number; boundingBox?: { x_min: number; y_min: number; x_max: number; y_max: number } } }) => {
      const result = await callKicadScript("list_schematic_labels", args);
      if (result.success) {
        const labels = result.labels || [];
        if (labels.length === 0) {
          return {
            content: [{ type: "text", text: "No labels found in schematic." }],
          };
        }
        const lines = labels.map(
          (l: any) =>
            `  [${l.type}] ${l.name} at (${l.position.x}, ${l.position.y})${l.angle != null ? ` angle=${l.angle}` : ""}`,
        );
        return {
          content: [
            {
              type: "text",
              text: `Labels (${labels.length}):\n${lines.join("\n")}`,
            },
          ],
        };
      }
      return {
        content: [
          { type: "text", text: `Failed to list labels: ${result.message || "Unknown error"}` },
        ],
        isError: true,
      };
    },
  );

  // Move a placed symbol, dragging connected wires
  server.tool(
    "move_schematic_component",
    "Move a placed symbol to a new position in the schematic. By default (preserveWires=true) wire endpoints touching the component's pins are stretched to follow the new position.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
      reference: z.string().describe("Reference designator (e.g., R1, U1)"),
      position: z
        .object({ x: z.number(), y: z.number() })
        .describe("New position in schematic mm coordinates"),
      preserveWires: z
        .boolean()
        .optional()
        .describe("Stretch connected wire endpoints to follow the move (default true)"),
    },
    async (args: {
      schematicPath: string;
      reference: string;
      position: { x: number; y: number };
      preserveWires?: boolean;
    }) => {
      const result = await callKicadScript("move_schematic_component", args);
      if (result.success) {
        const moved = result.wiresMoved ?? 0;
        const removed = result.wiresRemoved ?? 0;
        return {
          content: [
            {
              type: "text",
              text:
                `Moved ${args.reference} from (${result.oldPosition.x}, ${result.oldPosition.y}) ` +
                `to (${result.newPosition.x}, ${result.newPosition.y})` +
                (moved > 0 ? `, ${moved} wire endpoint(s) updated` : "") +
                (removed > 0 ? `, ${removed} zero-length wire(s) removed` : ""),
            },
          ],
        };
      }
      return {
        content: [
          {
            type: "text",
            text: `Failed to move component: ${result.message || "Unknown error"}`,
          },
        ],
        isError: true,
      };
    },
  );

  // Rotate schematic component
  server.tool(
    "rotate_schematic_component",
    "Rotate a placed symbol in the schematic.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
      reference: z.string().describe("Reference designator (e.g., R1, U1)"),
      angle: z.number().describe("Rotation angle in degrees (0, 90, 180, 270)"),
      mirror: z.enum(["x", "y"]).optional().describe("Optional mirror axis"),
    },
    async (args: {
      schematicPath: string;
      reference: string;
      angle: number;
      mirror?: "x" | "y";
    }) => {
      const result = await callKicadScript("rotate_schematic_component", args);
      if (result.success) {
        return {
          content: [
            {
              type: "text",
              text: `Rotated ${args.reference} to ${args.angle}°${args.mirror ? ` (mirrored ${args.mirror})` : ""}`,
            },
          ],
        };
      }
      return {
        content: [
          {
            type: "text",
            text: `Failed to rotate component: ${result.message || "Unknown error"}`,
          },
        ],
        isError: true,
      };
    },
  );

  // Annotate schematic
  server.tool(
    "annotate_schematic",
    "Assign reference designators to unannotated components (R? → R1, R2, ...). Must be called before tools that require known references. Automatically fixes hierarchical instance paths for sub-sheets so KiCAD ERC shows correct references when opening the parent schematic.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
      hierarchical: z
        .boolean()
        .optional()
        .describe(
          "Deprecated — hierarchical instance path fixing now happens automatically. Accepted for backward compatibility but has no additional effect.",
        ),
    },
    async (args: { schematicPath: string; hierarchical?: boolean }) => {
      const result = await callKicadScript("annotate_schematic", args);
      if (result.success) {
        const annotated = result.annotated || [];
        const subSheetsFixed: string[] = result.subSheetsFixed || [];
        const parts: string[] = [];
        if (annotated.length === 0) {
          parts.push("All components are already annotated.");
        } else {
          const lines = annotated.map(
            (a: any) => `  ${a.oldReference} → ${a.newReference}`,
          );
          parts.push(`Annotated ${annotated.length} component(s):\n${lines.join("\n")}`);
        }
        if (subSheetsFixed.length > 0) {
          parts.push(`Fixed sub-sheet instances in: ${subSheetsFixed.join(", ")}`);
        }
        return {
          content: [{ type: "text", text: parts.join("\n") }],
        };
      }
      return {
        content: [
          {
            type: "text",
            text: `Failed to annotate: ${result.message || "Unknown error"}`,
          },
        ],
        isError: true,
      };
    },
  );

  // Delete wire from schematic
  server.tool(
    "delete_schematic_wire",
    "Remove a wire from the schematic by start and end coordinates.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
      start: z.object({ x: z.number(), y: z.number() }).describe("Wire start position"),
      end: z.object({ x: z.number(), y: z.number() }).describe("Wire end position"),
    },
    async (args: {
      schematicPath: string;
      start: { x: number; y: number };
      end: { x: number; y: number };
    }) => {
      const result = await callKicadScript("delete_schematic_wire", args);
      if (result.success) {
        return {
          content: [
            {
              type: "text",
              text: `Deleted wire from (${args.start.x}, ${args.start.y}) to (${args.end.x}, ${args.end.y})`,
            },
          ],
        };
      }
      return {
        content: [
          {
            type: "text",
            text: `Failed to delete wire: ${result.message || "Unknown error"}`,
          },
        ],
        isError: true,
      };
    },
  );

  // Delete net label from schematic
  server.tool(
    "delete_schematic_net_label",
    "Remove net label(s) from the schematic. Four modes: (1) componentRef+pinName to delete whatever label sits at that pin tip — no coordinate lookup needed, (2) single label by netName + optional position, (3) deleteAll=true to remove every label at once, (4) positions array for batch deletion in one call. tolerance_mm (default 0.5) controls the coordinate match radius for modes 1 and 2.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
      componentRef: z.string().optional().describe("Component reference (e.g. R1) — use with pinName to delete the label at that pin tip without knowing its coordinates"),
      pinName: z.string().optional().describe("Pin number or name (e.g. '1', 'VDD') — use with componentRef"),
      netName: z.string().optional().describe("Name of the net label to remove (single-delete mode)"),
      position: z
        .object({ x: z.number(), y: z.number() })
        .optional()
        .describe("Position to disambiguate if multiple labels with same name (single-delete mode)"),
      tolerance_mm: z.number().optional().describe("Search radius in mm for coordinate-based matching (default 0.5). Increase to 1.0+ when the label may be slightly offset from the pin tip."),
      deleteAll: z
        .boolean()
        .optional()
        .describe("Set true to delete ALL net labels in the schematic at once"),
      positions: z
        .array(
          z.object({
            netName: z.string().describe("Net label name to delete"),
            position: z
              .object({ x: z.number(), y: z.number() })
              .optional()
              .describe("Optional position to disambiguate"),
          }),
        )
        .optional()
        .describe("Batch delete: list of {netName, position?} items removed in one call"),
    },
    async (args: {
      schematicPath: string;
      componentRef?: string;
      pinName?: string;
      netName?: string;
      position?: { x: number; y: number };
      tolerance_mm?: number;
      deleteAll?: boolean;
      positions?: Array<{ netName: string; position?: { x: number; y: number } }>;
    }) => {
      const result = await callKicadScript("delete_schematic_net_label", args);
      if (result.success) {
        let msg: string;
        if (args.deleteAll) {
          msg = `Deleted all net labels (${result.deleted ?? 0} removed)`;
        } else if (args.positions) {
          msg = `Deleted ${result.deleted ?? 0} label(s)`;
          if (result.notFound?.length) msg += `, not found: ${result.notFound.join(", ")}`;
        } else {
          msg = `Deleted net label '${args.netName}'`;
        }
        return { content: [{ type: "text", text: msg }] };
      }
      return {
        content: [
          {
            type: "text",
            text: `Failed to delete label: ${result.message || "Unknown error"}`,
          },
        ],
        isError: true,
      };
    },
  );

  // Export schematic to SVG
  server.tool(
    "export_schematic_svg",
    "Export schematic to SVG format using kicad-cli.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
      outputPath: z.string().describe("Output SVG file path"),
      blackAndWhite: z.boolean().optional().describe("Export in black and white"),
    },
    async (args: { schematicPath: string; outputPath: string; blackAndWhite?: boolean }) => {
      const result = await callKicadScript("export_schematic_svg", args);
      if (result.success) {
        return {
          content: [
            {
              type: "text",
              text: `Exported schematic SVG to ${result.file?.path || args.outputPath}`,
            },
          ],
        };
      }
      return {
        content: [
          {
            type: "text",
            text: `Failed to export SVG: ${result.message || "Unknown error"}`,
          },
        ],
        isError: true,
      };
    },
  );

  // Export schematic to PDF
  server.tool(
    "export_schematic_pdf",
    "Export schematic to PDF format using kicad-cli.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
      outputPath: z.string().describe("Output PDF file path"),
      blackAndWhite: z.boolean().optional().describe("Export in black and white"),
    },
    async (args: { schematicPath: string; outputPath: string; blackAndWhite?: boolean }) => {
      const result = await callKicadScript("export_schematic_pdf", args);
      if (result.success) {
        return {
          content: [
            {
              type: "text",
              text: `Exported schematic PDF to ${result.file?.path || args.outputPath}`,
            },
          ],
        };
      }
      return {
        content: [
          {
            type: "text",
            text: `Failed to export PDF: ${result.message || "Unknown error"}`,
          },
        ],
        isError: true,
      };
    },
  );

  // Get schematic view (rasterized image)
  server.tool(
    "get_schematic_view",
    "Return a rasterized image of the schematic (PNG by default, or SVG). Uses kicad-cli to export SVG, then converts to PNG via cairosvg. Use this for visual feedback after placing or wiring components.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
      format: z.enum(["png", "svg"]).optional().describe("Output format (default: png)"),
      width: z.number().optional().describe("Image width in pixels (default: 1200)"),
      height: z.number().optional().describe("Image height in pixels (default: 900)"),
      crop: z.boolean().optional().describe("Auto-crop to the bounding box of placed components with a small margin (default: false). Makes the image readable when components occupy only a small portion of the sheet. Requires Pillow (pip install Pillow)."),
      highlight_refs: z.array(z.string()).optional().describe("Optional list of reference designators to visually highlight in the rendered image (e.g. ['F1', 'C3']). Best-effort visual aid — accepted without error even if highlighting is not applied."),
    },
    async (args: {
      schematicPath: string;
      format?: "png" | "svg";
      width?: number;
      height?: number;
      crop?: boolean;
      highlight_refs?: string[];
    }) => {
      const result = await callKicadScript("get_schematic_view", args);
      if (result.success) {
        if (result.format === "svg") {
          const parts: { type: "text"; text: string }[] = [];
          if (result.message) {
            parts.push({ type: "text", text: result.message });
          }
          parts.push({
            type: "text",
            text: result.imageData || "",
          });
          return { content: parts };
        }
        // PNG — return as base64 image
        return {
          content: [
            {
              type: "image" as const,
              data: result.imageData,
              mimeType: "image/png",
            },
          ],
        };
      }
      return {
        content: [
          {
            type: "text",
            text: `Failed to get schematic view: ${result.message || "Unknown error"}`,
          },
        ],
        isError: true,
      };
    },
  );

  // Validate schematic syntax (paren balance check, no KiCad process needed)
  server.tool(
    "validate_schematic",
    "Check parenthesis balance and basic syntax of a .kicad_sch file without loading KiCad. Returns pass/fail and the line number of the first syntax error. Run this after placing components if batch_connect is reporting unexpected 'pin not found' errors — a paren underflow will cause those failures.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
    },
    async (args: { schematicPath: string }) => {
      const result = await callKicadScript("validate_schematic", args);
      if (result.valid) {
        return { content: [{ type: "text" as const, text: `Syntax OK: ${result.message}` }] };
      }
      return {
        content: [{
          type: "text" as const,
          text: `Syntax error: ${result.error || result.message || "Unknown error"}`,
        }],
        isError: true,
      };
    },
  );

  // Run Electrical Rules Check (ERC)
  server.tool(
    "run_erc",
    "Runs the KiCAD Electrical Rules Check (ERC) on a schematic via kicad-cli (operates on the saved file on disk). Returns violations grouped by type with counts. Use errorsOnly=false to also see warnings. All coordinates are in mm. NOTE: all schematic tools auto-save after each change, so the on-disk file is always current.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch schematic file"),
      errorsOnly: z.boolean().optional().describe("If true (default), only show error-severity violations. Set false to also show warnings and info."),
    },
    async (args: { schematicPath: string; errorsOnly?: boolean }) => {
      const result = await callKicadScript("run_erc", args);
      if (result.success) {
        const errorsOnly = args.errorsOnly !== false; // default true
        let violations: any[] = result.violations || [];
        if (errorsOnly) {
          violations = violations.filter((v: any) => v.severity === "error");
        }
        // Filter benign violations
        const actionable = violations.filter((v: any) => !v.benign);
        const benignCount = violations.length - actionable.length;

        const lines: string[] = [];
        if (result.sheets_checked?.length) {
          lines.push(`Checked: ${(result.sheets_checked as string[]).join(", ")}`);
        }
        const s = result.summary?.by_severity ?? {};
        lines.push(`ERC: ${s.error ?? 0} error(s), ${s.warning ?? 0} warning(s)${errorsOnly ? " [showing errors only]" : ""}`);
        if (benignCount > 0) lines.push(`  (${benignCount} benign library warnings hidden)`);

        if (actionable.length === 0) {
          lines.push(errorsOnly ? "No errors found." : "No violations found.");
        } else {
          // Group by type
          const byType: Record<string, any[]> = {};
          for (const v of actionable) {
            const key = v.type || "unknown";
            if (!byType[key]) byType[key] = [];
            byType[key].push(v);
          }
          lines.push("");
          for (const [type, group] of Object.entries(byType)) {
            lines.push(`[${type}] — ${group.length} violation(s):`);
            group.slice(0, 20).forEach((v: any) => {
              // Extract component reference from item descriptions
              const itemDescs = (v.items || [])
                .map((it: any) => it.description)
                .filter(Boolean)
                .join("; ");
              const toMils = (mm: number) => Math.round(mm * 1000 / 25.4);
              const loc = v.location?.x !== undefined
                ? ` @ (${toMils(v.location.x)}, ${toMils(v.location.y)}) mils / (${v.location.x.toFixed(2)}, ${v.location.y.toFixed(2)}) mm`
                : "";
              const detail = itemDescs ? `  ${itemDescs}${loc}` : `  ${v.message}${loc}`;
              lines.push(detail);
            });
            if (group.length > 20) lines.push(`  ... and ${group.length - 20} more`);
            lines.push("");
          }
        }
        // Surface PWR_FLAG suggestions so the agent can act immediately
        const pwrSuggestions: any[] = result.pwr_flag_suggestions || [];
        if (pwrSuggestions.length > 0) {
          lines.push(`PWR_FLAG suggestions (${pwrSuggestions.length} net(s) need a PWR_FLAG):`);
          for (const s of pwrSuggestions) {
            const pos = s.suggested_position;
            lines.push(`  net '${s.net}': place PWR_FLAG near (${pos.x.toFixed(2)}, ${pos.y.toFixed(2)}) mm`);
          }
          lines.push("  → Use batch_add_and_connect with symbol=power:PWR_FLAG to fix in one call.");
        }
        return { content: [{ type: "text", text: lines.join("\n") }] };
      } else {
        return {
          content: [
            {
              type: "text",
              text: `ERC failed: ${result.message || "Unknown error"}${result.errorDetails ? "\n" + result.errorDetails : ""}`,
            },
          ],
        };
      }
    },
  );

  // Generate netlist
  server.tool(
    "generate_netlist",
    "Generate a netlist from the schematic",
    {
      schematicPath: z.string().describe("Path to the schematic file"),
    },
    async (args: { schematicPath: string }) => {
      const result = await callKicadScript("generate_netlist", args);
      if (result.success && result.netlist) {
        const netlist = result.netlist;
        const output = [
          `=== Netlist for ${args.schematicPath} ===`,
          `\nComponents (${netlist.components.length}):`,
          ...netlist.components.map(
            (comp: any) =>
              `  ${comp.reference}: ${comp.value} (${comp.footprint || "No footprint"})`,
          ),
          `\nNets (${netlist.nets.length}):`,
          ...netlist.nets.map((net: any) => {
            const connections = net.connections
              .map((conn: any) => `${conn.component}/${conn.pin}`)
              .join(", ");
            return `  ${net.name}: ${connections}`;
          }),
        ].join("\n");

        return {
          content: [
            {
              type: "text",
              text: output,
            },
          ],
        };
      } else {
        return {
          content: [
            {
              type: "text",
              text: `Failed to generate netlist: ${result.message || "Unknown error"}`,
            },
          ],
        };
      }
    },
  );

  // Confirm schematic is saved (all schematic tools write immediately; this verifies the file exists)
  server.tool(
    "save_schematic",
    "Confirm the schematic file is saved to disk. Schematic tools write changes immediately — this tool verifies the file exists and returns its size. Equivalent to save_project but for .kicad_sch files.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
    },
    async (args: { schematicPath: string }) => {
      const result = await callKicadScript("save_schematic", args);
      if (result.success) {
        return {
          content: [{
            type: "text",
            text: result.message || `Schematic saved: ${args.schematicPath}`,
          }],
        };
      }
      return {
        content: [{
          type: "text",
          text: `Failed: ${result.message || "Unknown error"}`,
        }],
        isError: true,
      };
    },
  );

  // Sync schematic to PCB board (equivalent to KiCAD F8 / "Update PCB from Schematic")
  server.tool(
    "sync_schematic_to_board",
    "Import the schematic netlist into the PCB board — equivalent to pressing F8 in KiCAD (Tools → Update PCB from Schematic). MUST be called after the schematic is complete and before placing or routing components on the PCB. Without this step, the board has no footprints and no net assignments — place_component and route_pad_to_pad will produce an empty, unroutable board.",
    {
      schematicPath: z.string().describe("Absolute path to the .kicad_sch schematic file"),
      boardPath: z.string().describe("Absolute path to the .kicad_pcb board file"),
    },
    async (args: { schematicPath: string; boardPath: string }) => {
      const result = await callKicadScript("sync_schematic_to_board", args);
      return {
        content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
      };
    },
  );

  // Add hierarchical sheet reference to a parent schematic
  server.tool(
    "add_hierarchical_sheet",
    "Insert a hierarchical sheet reference block into a parent schematic. Creates the (sheet ...) block that links the parent to a sub-sheet file, and adds the corresponding entry to (sheet_instances). After populating the sub-sheet with components, call annotate_schematic on the sub-sheet — it will automatically fix hierarchical instance paths so the parent-context ERC shows correct references.",
    {
      schematicPath: z
        .string()
        .describe("Path to the parent .kicad_sch file"),
      subsheetPath: z
        .string()
        .describe(
          "Path to the referenced sub-sheet .kicad_sch file (resolved relative to the parent schematic's directory)",
        ),
      sheetName: z
        .string()
        .describe("Display name shown on the sheet block in the schematic"),
      position: z
        .object({ x: z.number(), y: z.number() })
        .describe("Top-left corner of the sheet rectangle in mm"),
      size: z
        .object({ width: z.number(), height: z.number() })
        .optional()
        .describe("Sheet rectangle dimensions in mm (default 80×50)"),
    },
    async (args: {
      schematicPath: string;
      subsheetPath: string;
      sheetName: string;
      position: { x: number; y: number };
      size?: { width: number; height: number };
    }) => {
      const result = await callKicadScript("add_hierarchical_sheet", args);
      if (result.success) {
        return {
          content: [
            {
              type: "text",
              text: `Sheet '${result.sheet_name}' added (uuid: ${result.sheet_uuid}, file: ${result.subsheet_path}, page: ${result.page})`,
            },
          ],
        };
      }
      return {
        content: [
          {
            type: "text",
            text: `Failed to add hierarchical sheet: ${result.message || "Unknown error"}`,
          },
        ],
        isError: true,
      };
    },
  );

  // ============================================================
  // Schematic Analysis Tools (read-only)
  // ============================================================

  // Get a zoomed view of a schematic region
  server.tool(
    "get_schematic_view_region",
    "Export a cropped region of the schematic as an image (PNG or SVG). Specify bounding box coordinates in schematic mm. Useful for zooming into a specific area to inspect wiring or layout.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch schematic file"),
      x1: z.number().describe("Left X coordinate of the region in mm"),
      y1: z.number().describe("Top Y coordinate of the region in mm"),
      x2: z.number().describe("Right X coordinate of the region in mm"),
      y2: z.number().describe("Bottom Y coordinate of the region in mm"),
      format: z.enum(["png", "svg"]).optional().describe("Output image format (default: png)"),
      width: z.number().optional().describe("Output image width in pixels (default: 800)"),
      height: z.number().optional().describe("Output image height in pixels (default: 600)"),
    },
    async (args: {
      schematicPath: string;
      x1: number;
      y1: number;
      x2: number;
      y2: number;
      format?: string;
      width?: number;
      height?: number;
    }) => {
      const result = await callKicadScript("get_schematic_view_region", args);
      if (result.success && result.imageData) {
        if (result.format === "svg") {
          return { content: [{ type: "text", text: result.imageData }] };
        }
        return {
          content: [
            {
              type: "image",
              data: result.imageData,
              mimeType: "image/png",
            },
          ],
        };
      }
      return {
        content: [{ type: "text", text: `Failed: ${result.message || "Unknown error"}` }],
      };
    },
  );

  // Trace a complete net topology
  server.tool(
    "get_net_topology",
    `Trace a complete named net and return every element on it in one call:
- wire_segments: all wire segments (start/end coordinates) that form this net
- labels: all local and global net labels on this net (position, type, angle)
- pins: all component pins connected to this net (ref, pin_number, pin_name, pin_type, world position)
- dangling_endpoints: wire endpoints with no pin, no label, and no junction — true open circuits

This replaces multiple separate tool calls (list_schematic_wires + list_schematic_labels + list_schematic_nets) when you need to inspect or debug a specific net. Use it to verify connectivity, find floating stubs, or map out signal paths.`,
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
      netName: z.string().describe("Net name to trace (must match a local or global label exactly)"),
    },
    async (args: { schematicPath: string; netName: string }) => {
      const result = await callKicadScript("get_net_topology", args);
      if (result.success) {
        const lines: string[] = [`Net: ${result.net}`];
        const segs = result.wire_segments || [];
        lines.push(`Wire segments (${segs.length}):`);
        for (const s of segs) {
          lines.push(`  (${s.start.x}, ${s.start.y}) → (${s.end.x}, ${s.end.y})`);
        }
        const lbls = result.labels || [];
        lines.push(`Labels (${lbls.length}):`);
        for (const l of lbls) {
          lines.push(`  [${l.type}] ${l.name} at (${l.position.x}, ${l.position.y}) angle=${l.angle}`);
        }
        const pins = result.pins || [];
        lines.push(`Pins (${pins.length}):`);
        for (const p of pins) {
          lines.push(`  ${p.ref}/${p.pin_number}(${p.pin_name}) [${p.pin_type}] at (${p.position.x}, ${p.position.y})`);
        }
        const dang = result.dangling_endpoints || [];
        if (dang.length > 0) {
          lines.push(`DANGLING endpoints (${dang.length}) — open circuits:`);
          for (const d of dang) {
            lines.push(`  (${d.x}, ${d.y})`);
          }
        } else {
          lines.push("No dangling endpoints.");
        }
        if (result.message) lines.push(result.message);
        return { content: [{ type: "text", text: lines.join("\n") }] };
      }
      return {
        content: [{ type: "text", text: `get_net_topology failed: ${result.message || "Unknown error"}` }],
        isError: true,
      };
    },
  );


  // Find overlapping elements
  server.tool(
    "find_overlapping_elements",
    "Detect spatially overlapping symbols, wires, and labels in the schematic. Finds duplicate power symbols at the same position, collinear overlapping wires, and labels stacked on top of each other.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch schematic file"),
      tolerance: z
        .number()
        .optional()
        .describe(
          "Distance threshold in mm for label proximity and wire collinearity checks. Symbol overlap uses bounding-box intersection. (default: 0.5)",
        ),
    },
    async (args: { schematicPath: string; tolerance?: number }) => {
      const result = await callKicadScript("find_overlapping_elements", args);
      if (result.success) {
        const lines = [`Found ${result.totalOverlaps} overlap(s):`];
        const syms: any[] = result.overlappingSymbols || [];
        const lbls: any[] = result.overlappingLabels || [];
        const wires: any[] = result.overlappingWires || [];
        if (syms.length) {
          lines.push(`\nOverlapping symbols (${syms.length}):`);
          syms.slice(0, 20).forEach((o: any) => {
            lines.push(
              `  ${o.element1.reference} ↔ ${o.element2.reference} (${o.distance}mm) [${o.type}]`,
            );
          });
        }
        if (lbls.length) {
          lines.push(`\nOverlapping labels (${lbls.length}):`);
          lbls.slice(0, 20).forEach((o: any) => {
            lines.push(`  "${o.element1.name}" ↔ "${o.element2.name}" (${o.distance}mm)`);
          });
        }
        if (wires.length) {
          lines.push(`\nOverlapping wires (${wires.length}):`);
          wires.slice(0, 20).forEach((o: any) => {
            lines.push(
              `  wire @ (${o.wire1.start.x},${o.wire1.start.y})→(${o.wire1.end.x},${o.wire1.end.y}) overlaps with another`,
            );
          });
        }
        return { content: [{ type: "text", text: lines.join("\n") }] };
      }
      return {
        content: [{ type: "text", text: `Failed: ${result.message || "Unknown error"}` }],
      };
    },
  );

  // Get component pin world positions
  server.tool(
    "get_component_pin_positions",
    `Return the world (schematic) coordinates for every pin of a component reference — after applying the component's position, rotation, and KiCad's Y-flip. Returns pin_number, pin_name, pin_type, position {x, y}, and stub_direction_angle for each pin.

Use this instead of manually combining list_symbol_pins (symbol-local coords) + rotation math. Internally uses the same PinLocator as add_no_connect and place_net_label_at_pin.`,
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
      reference: z.string().describe("Component reference designator (e.g., 'U9', 'R3')"),
    },
    async (args: { schematicPath: string; reference: string }) => {
      const result = await callKicadScript("get_component_pin_positions", args);
      if (result.success) {
        const pins = result.pins || [];
        const lines = [
          `${result.reference} — ${result.count} pin(s):`,
          ...pins.map((p: any) => {
            const angle = p.stub_direction_angle != null ? ` dir=${p.stub_direction_angle}°` : "";
            return `  pin ${p.pin_number} (${p.pin_name}) [${p.pin_type}] at (${p.position.x}, ${p.position.y})${angle}`;
          }),
        ];
        return { content: [{ type: "text", text: lines.join("\n") }] };
      }
      return {
        content: [{ type: "text", text: `get_component_pin_positions failed: ${result.message || "Unknown error"}` }],
        isError: true,
      };
    },
  );

  // Get elements in a region
  server.tool(
    "get_elements_in_region",
    "List all symbols, wires, and labels within a rectangular region of the schematic. Useful for understanding what is in a specific area before modifying it.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch schematic file"),
      x1: z.number().describe("Left X coordinate of the region in mm"),
      y1: z.number().describe("Top Y coordinate of the region in mm"),
      x2: z.number().describe("Right X coordinate of the region in mm"),
      y2: z.number().describe("Bottom Y coordinate of the region in mm"),
    },
    async (args: { schematicPath: string; x1: number; y1: number; x2: number; y2: number }) => {
      const result = await callKicadScript("get_elements_in_region", args);
      if (result.success) {
        const c = result.counts;
        const lines = [
          `Region (${args.x1},${args.y1})→(${args.x2},${args.y2}): ${c.symbols} symbols, ${c.wires} wires, ${c.labels} labels`,
        ];
        const syms: any[] = result.symbols || [];
        if (syms.length) {
          lines.push("\nSymbols:");
          syms.forEach((s: any) => {
            const pinCount = s.pins ? Object.keys(s.pins).length : 0;
            lines.push(
              `  ${s.reference} (${s.libId}) @ (${s.position.x}, ${s.position.y}) [${pinCount} pins]`,
            );
          });
        }
        const wires: any[] = result.wires || [];
        if (wires.length) {
          lines.push(`\nWires (${wires.length}):`);
          wires.slice(0, 30).forEach((w: any) => {
            lines.push(`  (${w.start.x},${w.start.y}) → (${w.end.x},${w.end.y})`);
          });
          if (wires.length > 30) lines.push(`  ... and ${wires.length - 30} more`);
        }
        const labels: any[] = result.labels || [];
        if (labels.length) {
          lines.push(`\nLabels (${labels.length}):`);
          labels.forEach((l: any) => {
            lines.push(`  "${l.name}" [${l.type}] @ (${l.position.x}, ${l.position.y})`);
          });
        }
        return { content: [{ type: "text", text: lines.join("\n") }] };
      }
      return {
        content: [{ type: "text", text: `Failed: ${result.message || "Unknown error"}` }],
      };
    },
  );

  // Find wires crossing symbols
  server.tool(
    "find_wires_crossing_symbols",
    "Find all wires that cross over component symbol bodies. Wires passing over symbols are unacceptable in schematics — they indicate routing mistakes where a wire was drawn across a component instead of around it.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch schematic file"),
    },
    async (args: { schematicPath: string }) => {
      const result = await callKicadScript("find_wires_crossing_symbols", args);
      if (result.success) {
        const collisions: any[] = result.collisions || [];
        const lines = [`Found ${collisions.length} wire(s) crossing symbols:`];
        collisions.slice(0, 30).forEach((c: any, i: number) => {
          lines.push(
            `  ${i + 1}. Wire (${c.wire.start.x},${c.wire.start.y})→(${c.wire.end.x},${c.wire.end.y}) crosses ${c.component.reference} (${c.component.libId})`,
          );
        });
        if (collisions.length > 30) lines.push(`  ... and ${collisions.length - 30} more`);
        return { content: [{ type: "text", text: lines.join("\n") }] };
      }
      return {
        content: [{ type: "text", text: `Failed: ${result.message || "Unknown error"}` }],
      };
    },
  );
}
