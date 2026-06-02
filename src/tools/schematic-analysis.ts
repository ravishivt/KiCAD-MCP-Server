/**
 * Schematic net & design-analysis tools.
 *
 * Read-only tools that summarise schematic connectivity for design review — they help
 * an AI (or human) understand an existing schematic and spot wiring mistakes without
 * round-tripping through ERC.
 */
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

export function registerSchematicAnalysisTools(server: McpServer, callKicadScript: Function) {
  // Pins with no net connection and no no-connect marker
  server.tool(
    "list_unconnected_pins",
    "List every component pin that has no net connection and no no-connect (X) marker. Use this for a quick completeness check before ERC — it reports reference, pin number/name/type and position for each floating pin. Power symbols (power:) are skipped.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
    },
    async (args: { schematicPath: string }) => {
      const result = await callKicadScript("list_unconnected_pins", args);
      if (!result.success) {
        return { content: [{ type: "text", text: `Failed: ${result.message || "Unknown error"}` }] };
      }
      if (result.count === 0) {
        return { content: [{ type: "text", text: "No unconnected pins — all pins are wired or marked no-connect." }] };
      }
      const lines = result.unconnected.map(
        (p: any) => `  ${p.reference}/${p.pinNumber} (${p.pinName}) — ${p.pinType} at (${p.position.x}, ${p.position.y})`
      );
      return { content: [{ type: "text", text: `${result.count} unconnected pin(s):\n${lines.join("\n")}` }] };
    }
  );

  // Named nets with exactly one connected pin
  server.tool(
    "find_single_pin_nets",
    "Return all named nets that have exactly one connected pin — i.e. a label/net that goes nowhere (a common wiring mistake). Each entry gives netName, component, pin number and pin name.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
    },
    async (args: { schematicPath: string }) => {
      const result = await callKicadScript("find_single_pin_nets", args);
      if (!result.success) {
        return { content: [{ type: "text", text: `Failed: ${result.message || "Unknown error"}` }] };
      }
      if (result.count === 0) {
        return { content: [{ type: "text", text: "No single-pin nets found." }] };
      }
      const lines = result.singlePinNets.map(
        (n: any) => `  ${n.netName}: only ${n.component}/${n.pinNumber} (${n.pinName})`
      );
      return { content: [{ type: "text", text: `${result.count} single-pin net(s):\n${lines.join("\n")}` }] };
    }
  );

  // Classify every net by type with fan-out / driver / load counts
  server.tool(
    "classify_nets",
    "Classify every net as ground / power_rail / clock / differential_pair / signal, with fan-out and driver/load pin counts. Useful for a design-review pass (e.g. to spot a signal net with zero drivers, or two drivers fighting).",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
    },
    async (args: { schematicPath: string }) => {
      const result = await callKicadScript("classify_nets", args);
      if (!result.success) {
        return { content: [{ type: "text", text: `Failed: ${result.message || "Unknown error"}` }] };
      }
      const lines = result.nets.map(
        (n: any) => `  ${n.type.padEnd(18)} ${n.netName.padEnd(20)} fanout=${n.fanout} drivers=${n.driverCount} loads=${n.loadCount}`
      );
      return { content: [{ type: "text", text: `${result.count} net(s):\n${lines.join("\n")}` }] };
    }
  );

  // Compact component-to-component adjacency graph
  server.tool(
    "get_net_graph",
    "Return a compact, human-readable component-to-component adjacency graph derived from named nets. Drivers point to loads (e.g. 'U1(TX) --[UART_TX]--> U2(RX)'). By default power/ground nets with few connections are skipped to reduce noise; set skipPower=false to include them.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
      skipPower: z.boolean().optional().default(true).describe("Skip power/ground nets that have fewer than 3 connections (default true)"),
    },
    async (args: { schematicPath: string; skipPower?: boolean }) => {
      const result = await callKicadScript("get_net_graph", args);
      if (!result.success) {
        return { content: [{ type: "text", text: `Failed: ${result.message || "Unknown error"}` }] };
      }
      const body = result.graph || "(no multi-pin signal nets to graph)";
      return { content: [{ type: "text", text: `Net graph (${result.netCount} net(s)):\n${body}` }] };
    }
  );

  // One-shot text summary of the whole schematic
  server.tool(
    "get_schematic_summary",
    "Return a single compact text summary of the whole schematic: a component table (ref, value, MPN, description, footprint) plus a per-net adjacency list with net types. Designed to give an AI full design context in one call instead of many list_* round-trips.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
    },
    async (args: { schematicPath: string }) => {
      const result = await callKicadScript("get_schematic_summary", args);
      if (!result.success) {
        return { content: [{ type: "text", text: `Failed: ${result.message || "Unknown error"}` }] };
      }
      return { content: [{ type: "text", text: result.summary }] };
    }
  );

  // Full trace of a single net
  server.tool(
    "get_net_topology",
    "Trace one named net end-to-end and return its wire segments, labels, connected component pins, and any dangling wire endpoints (stubs that connect to nothing). Use this to debug why a specific net isn't connecting as expected.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
      netName: z.string().describe("Name of the net to trace (must match a label, e.g. 'SDA', 'VBUS')"),
    },
    async (args: { schematicPath: string; netName: string }) => {
      const result = await callKicadScript("get_net_topology", args);
      if (!result.success) {
        return { content: [{ type: "text", text: `Failed: ${result.message || "Unknown error"}` }] };
      }
      const parts: string[] = [`Net '${result.net}':`];
      if (result.message) parts.push(`  ${result.message}`);
      parts.push(`  wire segments: ${result.wire_segments.length}`);
      parts.push(`  labels: ${result.labels.length}`);
      parts.push(
        `  pins: ${result.pins.length}` +
          (result.pins.length ? ` — ${result.pins.map((p: any) => `${p.ref}/${p.pin_name}`).join(", ")}` : "")
      );
      if (result.dangling_endpoints.length) {
        parts.push(
          `  ⚠ dangling endpoints: ${result.dangling_endpoints.map((d: any) => `(${d.x}, ${d.y})`).join(", ")}`
        );
      }
      return { content: [{ type: "text", text: parts.join("\n") }] };
    }
  );
}
