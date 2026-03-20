/**
 * Schematic tools for KiCAD MCP server
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

export function registerSchematicTools(
  server: McpServer,
  callKicadScript: Function,
) {
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
        .describe(
          "Symbol library:name reference (e.g., Device:R, EDA-MCP:ESP32-C3)",
        ),
      reference: z.string().describe("Component reference (e.g., R1, U1)"),
      value: z.string().optional().describe("Component value"),
      footprint: z.string().optional().describe("KiCAD footprint (e.g. Resistor_SMD:R_0603_1608Metric)"),
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

      const result = await callKicadScript(
        "add_schematic_component",
        transformed,
      );
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
        return {
          content: [
            {
              type: "text",
              text: `Added ${args.reference} (${args.symbol})${snappedNote}${pinSection}`,
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
    "Place multiple schematic components in a single call. Prefer this over calling add_schematic_component repeatedly — it injects all symbol definitions and creates all instances in one round-trip, returning snapped positions and pin coordinates for each. Each component uses 'Library:SymbolName' format. If any component fails, the rest are still placed and errors are reported per-component.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
      components: z.array(z.object({
        symbol: z.string().describe("Symbol in 'Library:SymbolName' format (e.g., Device:R, power:GND)"),
        reference: z.string().describe("Reference designator (e.g., R1, C3, U2)"),
        value: z.string().optional().describe("Component value (e.g., 10k, 100nF, AP63203WU-7)"),
        footprint: z.string().optional().describe("KiCAD footprint (e.g., Resistor_SMD:R_0603_1608Metric)"),
        position: z.object({ x: z.number(), y: z.number() }).optional().describe("Schematic position in mm (auto-snapped to 50mil grid)"),
        rotation: z.number().optional().describe("Rotation in degrees CCW, multiples of 90. Use 90 for horizontal resistors/capacitors."),
        includePins: z.boolean().optional().describe("Include pin coordinates in response (default false). Set true for ICs where pin coordinate planning is needed."),
      })).describe("List of components to place"),
    },
    async (args: {
      schematicPath: string;
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
      footprint: z.string().optional().describe("New KiCAD footprint string (e.g. Resistor_SMD:R_0603_1608Metric)"),
      value: z.string().optional().describe("New value string (e.g. 10k, 100nF)"),
      newReference: z.string().optional().describe("Rename the reference designator (e.g. R1 → R10)"),
      fieldPositions: z.record(z.object({
        x: z.number(),
        y: z.number(),
        angle: z.number().optional().default(0),
      })).optional().describe("Reposition field labels: map of field name to {x, y, angle} (e.g. {\"Reference\": {\"x\": 12.5, \"y\": 17.0}})"),
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
            `  ${name}: "${f.value}" @ (${f.x}, ${f.y}, angle=${f.angle}°)`
        );
        return {
          content: [{
            type: "text",
            text: `Component ${result.reference} at ${pos}\nFields:\n${fieldLines.join("\n")}`,
          }],
        };
      }
      return {
        content: [{
          type: "text",
          text: `Failed to get component: ${result.message || "Unknown error"}`,
        }],
      };
    },
  );

  // Connect components with wire
  server.tool(
    "add_wire",
    "Add a wire connection in the schematic",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
      start: z
        .object({
          x: z.number(),
          y: z.number(),
        })
        .describe("Start position"),
      end: z
        .object({
          x: z.number(),
          y: z.number(),
        })
        .describe("End position"),
    },
    async (args: { schematicPath: string; start: { x: number; y: number }; end: { x: number; y: number } }) => {
      const result = await callKicadScript("add_wire", {
        schematicPath: args.schematicPath,
        startPoint: args.start,
        endPoint: args.end,
      });
      if (result.success) {
        return { content: [{ type: "text", text: "Wire added successfully" }] };
      }
      return { content: [{ type: "text", text: `Failed to add wire: ${result.message || "Unknown error"}` }] };
    },
  );

  // Add pin-to-pin connection
  server.tool(
    "add_schematic_connection",
    "Connect two component pins with a wire. Use this for individual connections between components with different pin roles (e.g. U1.SDA → J3.2). WARNING: Do NOT use this in a loop to wire N passthrough pins — use connect_passthrough instead (single call, cleaner layout, far fewer tokens).",
    {
      schematicPath: z.string().describe("Path to the schematic file"),
      sourceRef: z.string().describe("Source component reference (e.g., R1)"),
      sourcePin: z
        .string()
        .describe("Source pin name/number (e.g., 1, 2, GND)"),
      targetRef: z.string().describe("Target component reference (e.g., C1)"),
      targetPin: z
        .string()
        .describe("Target pin name/number (e.g., 1, 2, VCC)"),
    },
    async (args: {
      schematicPath: string;
      sourceRef: string;
      sourcePin: string;
      targetRef: string;
      targetPin: string;
    }) => {
      const result = await callKicadScript("add_schematic_connection", args);
      if (result.success) {
        return {
          content: [
            {
              type: "text",
              text: `Successfully connected ${args.sourceRef}/${args.sourcePin} to ${args.targetRef}/${args.targetPin}`,
            },
          ],
        };
      } else {
        return {
          content: [
            {
              type: "text",
              text: `Failed to add connection: ${result.message || "Unknown error"}`,
            },
          ],
        };
      }
    },
  );

  // Add net label
  server.tool(
    "add_schematic_net_label",
    "Add a net label to the schematic",
    {
      schematicPath: z.string().describe("Path to the schematic file"),
      netName: z
        .string()
        .describe("Name of the net (e.g., VCC, GND, SIGNAL_1)"),
      position: z
        .array(z.number())
        .length(2)
        .describe("Position [x, y] for the label"),
    },
    async (args: {
      schematicPath: string;
      netName: string;
      position: number[];
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

  // Get pin locations for one or more schematic components
  server.tool(
    "get_schematic_pin_locations",
    "Returns the exact x/y coordinates of every pin on one or more schematic components. Pass a single 'reference' or a list of 'references' to batch multiple components in one call — strongly prefer the batch form to avoid many round-trips.\n\nCoordinate convention: returned x/y are absolute schematic coordinates (Y-axis points DOWN). The Y-axis flip between symbol library space (Y-up) and schematic space (Y-down) is applied automatically by the underlying library — do NOT manually compute pin_schematic_y = component_y ± pin_symbol_y.",
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
            ([pinNum, data]: [string, any]) =>
              `    Pin ${pinNum} (${data.name || pinNum}): x=${data.x}, y=${data.y}`
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
          content: [{
            type: "text",
            text: `Failed to get pin locations: ${result.message || "Unknown error"}`,
          }],
        };
      }
    },
  );

  // Batch connect: place net labels on multiple pins in one call
  server.tool(
    "batch_connect",
    "Place net labels on multiple component pins in a single call. Accepts a map of {componentRef: {pinNumber: netName}} and places all labels in one round-trip. Use this instead of calling connect_to_net repeatedly — it is dramatically more token-efficient for wiring many pins at once.",
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
    },
    async (args: { schematicPath: string; connections: Record<string, Record<string, string>> }) => {
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
      netPrefix: z.string().optional().describe("Net name prefix, e.g. 'CSI' → CSI_1, CSI_2 (default: PIN)"),
      pinOffset: z.number().optional().describe("Add to pin number when building net name (default: 0)"),
    },
    async (args: { schematicPath: string; sourceRef: string; targetRef: string; netPrefix?: string; pinOffset?: number }) => {
      const result = await callKicadScript("connect_passthrough", args);
      if (result.success !== false || (result.connected && result.connected.length > 0)) {
        const lines: string[] = [];
        if (result.connected?.length) lines.push(`Connected (${result.connected.length}): ${result.connected.slice(0, 5).join(", ")}${result.connected.length > 5 ? " ..." : ""}`);
        if (result.failed?.length) lines.push(`Failed (${result.failed.length}): ${result.failed.join(", ")}`);
        return {
          content: [{ type: "text", text: result.message + "\n" + lines.join("\n") }],
        };
      } else {
        return {
          content: [{ type: "text", text: `Passthrough failed: ${result.message || "Unknown error"}` }],
        };
      }
    },
  );

  // List all components in schematic
  server.tool(
    "list_schematic_components",
    "List all components in a schematic with their references, values, positions, and pins. Essential for inspecting what's on the schematic before making edits.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
      filter: z
        .object({
          libId: z.string().optional().describe("Filter by library ID (e.g., 'Device:R')"),
          referencePrefix: z.string().optional().describe("Filter by reference prefix (e.g., 'R', 'C', 'U')"),
        })
        .optional()
        .describe("Optional filters"),
    },
    async (args: {
      schematicPath: string;
      filter?: { libId?: string; referencePrefix?: string };
    }) => {
      const result = await callKicadScript("list_schematic_components", args);
      if (result.success) {
        const comps = result.components || [];
        if (comps.length === 0) {
          return {
            content: [{ type: "text", text: "No components found in schematic." }],
          };
        }
        const lines = comps.map(
          (c: any) =>
            `  ${c.reference}: ${c.libId} = "${c.value}" at (${c.position.x}, ${c.position.y}) rot=${c.rotation}°${c.pins ? ` [${c.pins.length} pins]` : ""}`,
        );
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

  // List all nets in schematic
  server.tool(
    "list_schematic_nets",
    "List all nets in the schematic with their connections.",
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
            .map((c: any) => `${c.component}/${c.pin}`)
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
    "List all wires in the schematic with start/end coordinates.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
    },
    async (args: { schematicPath: string }) => {
      const result = await callKicadScript("list_schematic_wires", args);
      if (result.success) {
        const wires = result.wires || [];
        if (wires.length === 0) {
          return {
            content: [{ type: "text", text: "No wires found in schematic." }],
          };
        }
        const lines = wires.map(
          (w: any) =>
            `  (${w.start.x}, ${w.start.y}) → (${w.end.x}, ${w.end.y})`,
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
    "List all net labels, global labels, and power flags in the schematic.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
    },
    async (args: { schematicPath: string }) => {
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
            `  [${l.type}] ${l.name} at (${l.position.x}, ${l.position.y})`,
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

  // Move schematic component
  server.tool(
    "move_schematic_component",
    "Move a placed symbol to a new position in the schematic. The position is auto-snapped to the KiCAD 50mil (1.27mm) grid; the response shows the actual snapped position.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
      reference: z.string().describe("Reference designator (e.g., R1, U1)"),
      position: z
        .object({
          x: z.number(),
          y: z.number(),
        })
        .describe("New position"),
    },
    async (args: {
      schematicPath: string;
      reference: string;
      position: { x: number; y: number };
    }) => {
      const result = await callKicadScript("move_schematic_component", args);
      if (result.success) {
        return {
          content: [
            {
              type: "text",
              text: `Moved ${args.reference} from (${result.oldPosition.x}, ${result.oldPosition.y}) to (${result.newPosition.x}, ${result.newPosition.y})`,
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
      mirror: z
        .enum(["x", "y"])
        .optional()
        .describe("Optional mirror axis"),
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
    "Assign reference designators to unannotated components (R? → R1, R2, ...). Must be called before tools that require known references.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
    },
    async (args: { schematicPath: string }) => {
      const result = await callKicadScript("annotate_schematic", args);
      if (result.success) {
        const annotated = result.annotated || [];
        if (annotated.length === 0) {
          return {
            content: [
              { type: "text", text: "All components are already annotated." },
            ],
          };
        }
        const lines = annotated.map(
          (a: any) => `  ${a.oldReference} → ${a.newReference}`,
        );
        return {
          content: [
            {
              type: "text",
              text: `Annotated ${annotated.length} component(s):\n${lines.join("\n")}`,
            },
          ],
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
      start: z
        .object({ x: z.number(), y: z.number() })
        .describe("Wire start position"),
      end: z
        .object({ x: z.number(), y: z.number() })
        .describe("Wire end position"),
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
    "Remove a net label from the schematic.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
      netName: z.string().describe("Name of the net label to remove"),
      position: z
        .object({ x: z.number(), y: z.number() })
        .optional()
        .describe("Position to disambiguate if multiple labels with same name"),
    },
    async (args: {
      schematicPath: string;
      netName: string;
      position?: { x: number; y: number };
    }) => {
      const result = await callKicadScript("delete_schematic_net_label", args);
      if (result.success) {
        return {
          content: [
            {
              type: "text",
              text: `Deleted net label '${args.netName}'`,
            },
          ],
        };
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
      blackAndWhite: z
        .boolean()
        .optional()
        .describe("Export in black and white"),
    },
    async (args: {
      schematicPath: string;
      outputPath: string;
      blackAndWhite?: boolean;
    }) => {
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
      blackAndWhite: z
        .boolean()
        .optional()
        .describe("Export in black and white"),
    },
    async (args: {
      schematicPath: string;
      outputPath: string;
      blackAndWhite?: boolean;
    }) => {
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
      format: z
        .enum(["png", "svg"])
        .optional()
        .describe("Output format (default: png)"),
      width: z.number().optional().describe("Image width in pixels (default: 1200)"),
      height: z.number().optional().describe("Image height in pixels (default: 900)"),
      crop: z.boolean().optional().describe("Auto-crop to the bounding box of placed components with a small margin (default: false). Makes the image readable when components occupy only a small portion of the sheet. Requires Pillow (pip install Pillow)."),
    },
    async (args: {
      schematicPath: string;
      format?: "png" | "svg";
      width?: number;
      height?: number;
      crop?: boolean;
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
        return { content: [{ type: "text", text: lines.join("\n") }] };
      } else {
        return {
          content: [{ type: "text", text: `ERC failed: ${result.message || "Unknown error"}${result.errorDetails ? "\n" + result.errorDetails : ""}` }],
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
}
