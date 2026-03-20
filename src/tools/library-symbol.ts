/**
 * Symbol Library tools for KiCAD MCP server
 * Provides search/browse access to local KiCad symbol libraries
 */

import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { z } from 'zod';

export function registerSymbolLibraryTools(server: McpServer, callKicadScript: Function) {
  // List available symbol libraries
  server.tool(
    "list_symbol_libraries",
    "List KiCAD symbol libraries. Use projectOnly=true with schematicPath to see only libraries registered in the project's sym-lib-table (avoids noise from 200+ global libraries).",
    {
      schematicPath: z.string().optional()
        .describe("Path to the .kicad_sch file (or project directory) — required when projectOnly=true"),
      projectOnly: z.boolean().optional().default(false)
        .describe("When true, return only libraries from the project's sym-lib-table"),
    },
    async (args: { schematicPath?: string; projectOnly?: boolean }) => {
      const result = await callKicadScript("list_symbol_libraries", {
        schematicPath: args.schematicPath,
        projectOnly: args.projectOnly ?? false,
      });
      if (result.success && result.libraries) {
        const note = result.source ? ` (from ${result.source})` : '';
        return {
          content: [
            {
              type: "text",
              text: `Found ${result.count} symbol libraries${note}:\n${result.libraries.join('\n')}`
            }
          ]
        };
      }
      return {
        content: [
          {
            type: "text",
            text: `Failed to list symbol libraries: ${result.message || 'Unknown error'}`
          }
        ]
      };
    }
  );

  // Search for symbols across all libraries
  server.tool(
    "search_symbols",
    `Search for symbols in local KiCAD symbol libraries.

Searches by: symbol name, LCSC ID, description, manufacturer, MPN, category.
Use this to find components already in your local libraries (e.g., JLCPCB-KiCad-Library).

Returns symbol references that can be used directly in schematics.`,
    {
      query: z.string()
        .describe("Search query (e.g., 'ESP32', 'STM32F103', 'C8734' for LCSC ID)"),
      library: z.string().optional()
        .describe("Optional: filter to specific library name pattern (e.g., 'JLCPCB')"),
      limit: z.number().optional().default(20)
        .describe("Maximum number of results to return")
    },
    async (args: { query: string; library?: string; limit?: number }) => {
      const result = await callKicadScript("search_symbols", args);
      if (result.success && result.symbols) {
        if (result.symbols.length === 0) {
          return {
            content: [
              {
                type: "text",
                text: `No symbols found matching "${args.query}"${args.library ? ` in libraries matching "${args.library}"` : ''}`
              }
            ]
          };
        }

        const symbolList = result.symbols.map((s: any) => {
          const parts = [`${s.full_ref}`];
          if (s.lcsc_id) parts.push(`LCSC: ${s.lcsc_id}`);
          if (s.description) parts.push(s.description);
          else if (s.value) parts.push(s.value);
          return parts.join(' | ');
        }).join('\n');

        return {
          content: [
            {
              type: "text",
              text: `Found ${result.count} symbols matching "${args.query}":\n\n${symbolList}`
            }
          ]
        };
      }
      return {
        content: [
          {
            type: "text",
            text: `Failed to search symbols: ${result.message || 'Unknown error'}`
          }
        ]
      };
    }
  );

  // List symbols in a specific library
  server.tool(
    "list_library_symbols",
    "List all symbols in a specific KiCAD symbol library",
    {
      library: z.string()
        .describe("Library name (e.g., 'Device', 'PCM_JLCPCB-MCUs')")
    },
    async (args: { library: string }) => {
      const result = await callKicadScript("list_library_symbols", args);
      if (result.success && result.symbols) {
        const symbolList = result.symbols.map((s: any) => {
          const parts = [`  - ${s.name}`];
          if (s.lcsc_id) parts.push(`(LCSC: ${s.lcsc_id})`);
          return parts.join(' ');
        }).join('\n');

        return {
          content: [
            {
              type: "text",
              text: `Library "${args.library}" contains ${result.count} symbols:\n${symbolList}`
            }
          ]
        };
      }
      return {
        content: [
          {
            type: "text",
            text: `Failed to list symbols in library ${args.library}: ${result.message || 'Unknown error'}`
          }
        ]
      };
    }
  );

  // Get detailed information about a specific symbol
  server.tool(
    "get_symbol_info",
    "Get detailed information about a specific symbol. Pass schematicPath to also search project-local symbol libraries (sym-lib-table) — required for project-specific symbols like custom connectors.",
    {
      symbol: z.string()
        .describe("Symbol specification (e.g., 'Device:R' or 'connectors:Korean-Hroparts_TYPE-C-31-M-12')"),
      schematicPath: z.string().optional()
        .describe("Path to .kicad_sch — enables project-local library search in addition to global KiCad libs"),
    },
    async (args: { symbol: string; schematicPath?: string }) => {
      const result = await callKicadScript("get_symbol_info", args);
      if (result.success && result.symbol_info) {
        const info = result.symbol_info;
        const details = [
          `Symbol: ${info.full_ref}`,
          info.value ? `Value: ${info.value}` : '',
          info.description ? `Description: ${info.description}` : '',
          info.lcsc_id ? `LCSC: ${info.lcsc_id}` : '',
          info.manufacturer ? `Manufacturer: ${info.manufacturer}` : '',
          info.mpn ? `MPN: ${info.mpn}` : '',
          info.footprint ? `Footprint: ${info.footprint}` : '',
          info.category ? `Category: ${info.category}` : '',
          info.lib_class ? `Class: ${info.lib_class}` : '',
          info.datasheet ? `Datasheet: ${info.datasheet}` : '',
        ].filter(line => line).join('\n');

        return {
          content: [
            {
              type: "text",
              text: details
            }
          ]
        };
      }
      return {
        content: [
          {
            type: "text",
            text: `Failed to get symbol info: ${result.message || 'Unknown error'}`
          }
        ]
      };
    }
  );

  // List pins for a symbol from the library (no schematic needed)
  server.tool(
    "list_symbol_pins",
    "Return pin names, numbers, and types for a symbol directly from the library — no schematic required. Use this before add_schematic_component or batch_add_components to discover pins for batch_connect / connect_to_net calls. Each pin has 'number' (e.g. '1', 'A5') and 'name' (e.g. 'FB', 'GND') — batch_connect and connect_to_net accept either. Pass schematicPath to resolve project-local symbols (e.g. connectors:Korean-Hroparts_TYPE-C-31-M-12). Returns close-match suggestions if the symbol name is slightly wrong.",
    {
      symbol: z.string()
        .describe("Symbol in 'Library:SymbolName' format (e.g., Device:R, Connector:Conn_01x04, Device:FerriteBead)"),
      schematicPath: z.string().optional()
        .describe("Path to .kicad_sch — enables project-local sym-lib-table lookup for project-specific symbols"),
    },
    async (args: { symbol: string; schematicPath?: string }) => {
      const result = await callKicadScript("list_symbol_pins", args);
      if (result.success) {
        if (result.pins.length === 0) {
          return {
            content: [{ type: "text", text: `Symbol ${result.symbol} has no pins.` }]
          };
        }
        const lines = result.pins.map((p: any) => `  Pin ${p.number} (${p.name}) — type: ${p.type}`);
        return {
          content: [{
            type: "text",
            text: `${result.symbol} — ${result.pin_count} pin(s):\n${lines.join('\n')}`
          }]
        };
      }
      const hint = result.suggestions?.length
        ? `\nDid you mean: ${result.suggestions.join(', ')}?`
        : '';
      return {
        content: [{
          type: "text",
          text: `Failed to list pins: ${result.message || 'Unknown error'}${hint}`
        }]
      };
    }
  );

  // Search symbol names across KiCAD standard libraries (fast name/lib search)
  server.tool(
    "search_schematic_symbols",
    "Search for symbol names across KiCAD standard symbol libraries by name substring. Returns 'Library:SymbolName' strings usable in add_schematic_component. Use this when you know part of the symbol name (e.g., 'FerriteBead', 'NPN', 'AMS1117') but not the exact library. For JLCPCB/LCSC parts use search_symbols instead.",
    {
      query: z.string().describe("Name substring to search for (matched against symbol name and library name)"),
      maxResults: z.number().optional().default(20).describe("Maximum results to return (default 20, max 100)"),
    },
    async (args: { query: string; maxResults?: number }) => {
      const result = await callKicadScript("search_schematic_symbols", args);
      if (result.success) {
        if (result.count === 0) {
          return { content: [{ type: "text", text: `No symbols found matching "${args.query}".` }] };
        }
        const lines = result.results.map((r: any) => `  ${r.fullName}`);
        return {
          content: [{
            type: "text",
            text: `Found ${result.count} symbol(s) matching "${args.query}":\n${lines.join('\n')}`
          }]
        };
      }
      return {
        content: [{ type: "text", text: `Search failed: ${result.message || 'Unknown error'}` }]
      };
    }
  );
}
