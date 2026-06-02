/**
 * Schematic connectivity & hierarchy tools: junctions, pin labels, hierarchical sheets,
 * and a fast syntax validator.
 */
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

export function registerSchematicHierarchyTools(server: McpServer, callKicadScript: Function) {
  // Junction dot (splits any wire it lands on)
  server.tool(
    "add_schematic_junction",
    "Add a junction (connection dot) at a coordinate. If a wire passes through the point it is split into two segments so connectivity analysis treats it as a real T/X connection — mirrors KiCAD's behaviour.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
      x: z.number().describe("Junction X position in mm"),
      y: z.number().describe("Junction Y position in mm"),
    },
    async (args: { schematicPath: string; x: number; y: number }) => {
      const r = await callKicadScript("add_schematic_junction", {
        schematicPath: args.schematicPath,
        position: [args.x, args.y],
      });
      return { content: [{ type: "text", text: r.success ? r.message : `Failed: ${r.message || "Unknown error"}` }] };
    }
  );

  // Net label at an exact pin endpoint
  server.tool(
    "place_net_label_at_pin",
    "Place a net label exactly at a component pin's endpoint (no wire stub), oriented so the text extends away from the pin. If a same-net label is already nearby and facing, a wire is drawn to it instead of placing a duplicate. Handles single-pin parts (PWR_FLAG, GND, +3V3) via a one-pin fallback.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
      reference: z.string().describe("Component reference (e.g., U1)"),
      pinNumber: z.string().describe("Pin number or name (e.g., '3', 'VCC')"),
      netName: z.string().describe("Net name for the label (e.g., SDA, +3V3)"),
    },
    async (args: any) => {
      const r = await callKicadScript("place_net_label_at_pin", args);
      if (!r.success) return { content: [{ type: "text", text: `Failed: ${r.message || "Unknown error"}` }] };
      const note = r.note ? ` (${r.note})` : "";
      return {
        content: [{ type: "text", text: `Placed '${r.netName}' at ${r.reference}/${r.pinNumber} (${r.position.x}, ${r.position.y})${note}` }],
      };
    }
  );

  // Link an existing sub-sheet into a parent
  server.tool(
    "add_hierarchical_sheet",
    "Insert a hierarchical-sheet reference block into a parent schematic, pointing at an existing sub-sheet file. Adds the sheet box, name/file fields, a sheet_instances path entry on the next page number, and fixes sub-sheet component instance paths so ERC resolves references.",
    {
      schematicPath: z.string().describe("Path to the parent .kicad_sch"),
      subsheetPath: z.string().describe("Path to the existing sub-sheet .kicad_sch to reference"),
      sheetName: z.string().optional().default("Sheet").describe("Display name for the sheet"),
      position: z.object({ x: z.number(), y: z.number() }).optional().describe("Top-left of the sheet box in mm (default 50,50)"),
      size: z.object({ width: z.number(), height: z.number() }).optional().describe("Sheet box size in mm (default 80x50)"),
    },
    async (args: any) => {
      const r = await callKicadScript("add_hierarchical_sheet", args);
      if (!r.success) return { content: [{ type: "text", text: `Failed: ${r.message || "Unknown error"}` }] };
      return { content: [{ type: "text", text: `Added sheet '${r.sheet_name}' -> ${r.subsheet_path} (page ${r.page})` }] };
    }
  );

  // Create a sub-sheet file AND link it in one call
  server.tool(
    "create_hierarchical_subsheet",
    "Create a new sub-sheet .kicad_sch file and link it into a parent schematic in a single call (create_schematic + add_hierarchical_sheet). The fastest way to grow a hierarchical design.",
    {
      parentSchematicPath: z.string().describe("Path to the parent .kicad_sch"),
      subsheetPath: z.string().describe("Path for the new sub-sheet .kicad_sch to create"),
      sheetName: z.string().optional().default("Sheet").describe("Display name for the sheet"),
      position: z.object({ x: z.number(), y: z.number() }).optional(),
      size: z.object({ width: z.number(), height: z.number() }).optional(),
      metadata: z.record(z.string(), z.any()).optional().describe("Optional metadata for the new sub-sheet (title, etc.)"),
    },
    async (args: any) => {
      const r = await callKicadScript("create_hierarchical_subsheet", args);
      return { content: [{ type: "text", text: r.success ? r.message : `Failed: ${r.message || "Unknown error"}` }] };
    }
  );

  // Fast syntax validator
  server.tool(
    "validate_schematic",
    "Quickly check a .kicad_sch for parenthesis balance / basic structural validity without fully parsing it. Use after manual or programmatic edits to catch corruption before other tools choke on the file. Reports the line of the first imbalance.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
    },
    async (args: { schematicPath: string }) => {
      const r = await callKicadScript("validate_schematic", args);
      if (r.valid) return { content: [{ type: "text", text: `✓ ${r.message}` }] };
      return { content: [{ type: "text", text: `✗ Invalid: ${r.error || r.message || "Unknown error"}` }] };
    }
  );
}
