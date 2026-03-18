/**
 * JLCPCB API tools for KiCAD MCP server
 * Provides access to JLCPCB's complete parts catalog via their API
 */

import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { z } from 'zod';

export function registerJLCPCBApiTools(server: McpServer, callKicadScript: Function) {
  // Search JLCPCB parts
  server.tool(
    "search_jlcpcb_parts",
    `Search JLCPCB parts catalog by specifications.

Searches the local JLCPCB database (populate it first with the /download-jlcpcb-db skill).
Provides pricing, stock info, and library type (Basic parts = free assembly).

The database has two complementary search approaches — use either or both:

1. FREE-TEXT QUERY (query=): FTS across LCSC code, manufacturer part number, manufacturer
   name, and derived attribute descriptions. ~65% of parts have attribute text like
   "450mΩ ±25% 600Ω@100MHz 0603 Ferrite Beads ROHS", making parametric FTS effective.
   Good for: MPN lookups, component type + specs ("ferrite bead 600 ohm"), value searches.

2. CATEGORY FILTERS (category= / subcategory=): Exact structural filters that work for
   all 611K parts regardless of description coverage. Use get_jlcpcb_categories to
   discover exact names. Good for: browsing a component type, guaranteeing coverage.

Both approaches can be combined — all filters apply with AND (narrowing results).

Examples:
  - MPN lookup:        query="AP63203"
  - Ferrite bead spec: query="600Ω@100MHz 200mA 0603"
  - Category browse:   category="Filters", subcategory="Ferrite Beads"
  - Combined:          query="600 ohm", category="Filters", subcategory="Ferrite Beads"
  - Buck converter:    category="Power Management (PMIC)", subcategory="DC-DC Converters"
  - Resettable fuse:   category="Circuit Protection", subcategory="Resettable Fuses"`,
    {
      query: z.string().optional()
        .describe("Free-text search across LCSC code, MPN, manufacturer, and part attributes. Works for MPN lookups ('AP63203'), component types ('ferrite bead'), and parametric specs ('600Ω@100MHz 200mA')."),
      category: z.string().optional()
        .describe("Filter by top-level category — use get_jlcpcb_categories to see all valid values (e.g., 'Resistors', 'Capacitors', 'Connectors', 'Filters', 'Circuit Protection', 'Power Management (PMIC)')"),
      subcategory: z.string().optional()
        .describe("Filter by subcategory — use get_jlcpcb_categories to see all valid values (e.g., 'Ferrite Beads', 'USB Connectors', 'DC-DC Converters', 'Resettable Fuses')"),
      package: z.string().optional()
        .describe("Filter by package type (e.g., '0603', 'SOT-23', 'QFN-32') — note: package data is sparse in the DB"),
      library_type: z.enum(["Basic", "Extended", "Preferred", "All"]).optional().default("All")
        .describe("Filter by library type (Basic = free assembly at JLCPCB)"),
      manufacturer: z.string().optional()
        .describe("Filter by manufacturer name"),
      in_stock: z.boolean().optional().default(true)
        .describe("Only show parts with available stock"),
      limit: z.number().optional().default(20)
        .describe("Maximum number of results to return")
    },
    async (args: any) => {
      const result = await callKicadScript("search_jlcpcb_parts", args);
      if (result.success && result.parts) {
        if (result.parts.length === 0) {
          return {
            content: [{
              type: "text",
              text: `No JLCPCB parts found matching your criteria.\n\n` +
                    `Try broadening your search or check if the database is populated.`
            }]
          };
        }

        const partsList = result.parts.map((p: any) => {
          const priceInfo = p.price_breaks && p.price_breaks.length > 0
            ? ` - $${p.price_breaks[0].price}/ea`
            : '';
          const stockInfo = p.stock > 0 ? ` (${p.stock} in stock)` : ' (out of stock)';
          return `${p.lcsc}: ${p.mfr_part} - ${p.description} [${p.library_type}]${priceInfo}${stockInfo}`;
        }).join('\n');

        return {
          content: [{
            type: "text",
            text: `Found ${result.count} JLCPCB parts:\n\n${partsList}\n\n` +
                  `💡 Basic parts have free assembly. Extended parts charge $3 setup fee per unique part.`
          }]
        };
      }
      return {
        content: [{
          type: "text",
          text: `Failed to search JLCPCB parts: ${result.message || 'Unknown error'}\n\n` +
                `Make sure you've populated the database first using the /download-jlcpcb-db skill.`
        }]
      };
    }
  );

  // Get JLCPCB part details
  server.tool(
    "get_jlcpcb_part",
    `Get detailed information about a specific JLCPCB part by LCSC number.

Calls the live JLCPCB API — always returns current stock, pricing, and datasheet,
unlike search_jlcpcb_parts which uses a local DB snapshot that may be months old.
Use this to confirm a part after finding candidates via search_jlcpcb_parts.`,
    {
      lcsc_number: z.string()
        .describe("LCSC part number (e.g., 'C25804', 'C2286')")
    },
    async (args: { lcsc_number: string }) => {
      const result = await callKicadScript("get_jlcpcb_part", args);
      if (result.success && result.part) {
        const p = result.part;
        const priceTable = p.price_breaks && p.price_breaks.length > 0
          ? '\n\nPrice Breaks:\n' + p.price_breaks.map((pb: any) =>
              `  ${pb.qty}+: $${pb.price}/ea`
            ).join('\n')
          : '';

        const footprints = result.footprints && result.footprints.length > 0
          ? '\n\nSuggested KiCAD Footprints:\n' + result.footprints.map((f: string) =>
              `  - ${f}`
            ).join('\n')
          : '';

        return {
          content: [{
            type: "text",
            text: `LCSC: ${p.lcsc}\n` +
                  `MFR Part: ${p.mfr_part}\n` +
                  `Manufacturer: ${p.manufacturer}\n` +
                  `Category: ${p.category} / ${p.subcategory}\n` +
                  `Package: ${p.package}\n` +
                  `Description: ${p.description}\n` +
                  `Library Type: ${p.library_type} ${p.library_type === 'Basic' ? '(Free assembly!)' : ''}\n` +
                  `Stock: ${p.stock}\n` +
                  (p.datasheet ? `Datasheet: ${p.datasheet}\n` : '') +
                  priceTable +
                  footprints
          }]
        };
      }
      return {
        content: [{
          type: "text",
          text: `Part not found: ${args.lcsc_number}\n\n` +
                `Make sure you've populated the database first using the /download-jlcpcb-db skill.`
        }]
      };
    }
  );

  // Get JLCPCB database statistics
  server.tool(
    "get_jlcpcb_database_stats",
    "Get statistics about the local JLCPCB parts database",
    {},
    async () => {
      const result = await callKicadScript("get_jlcpcb_database_stats", {});
      if (result.success) {
        const stats = result.stats;
        return {
          content: [{
            type: "text",
            text: `JLCPCB Database Statistics:\n\n` +
                  `Total parts: ${stats.total_parts.toLocaleString()}\n` +
                  `Basic parts: ${stats.basic_parts.toLocaleString()} (free assembly)\n` +
                  `Extended parts: ${stats.extended_parts.toLocaleString()} ($3 setup fee each)\n` +
                  `In stock: ${stats.in_stock.toLocaleString()}\n` +
                  `Database path: ${stats.db_path}`
          }]
        };
      }
      return {
        content: [{
          type: "text",
          text: `JLCPCB database not found or empty.\n\n` +
                `Populate it using the /download-jlcpcb-db skill.`
        }]
      };
    }
  );

  // List categories (top-level) or subcategories (drill-down)
  server.tool(
    "get_jlcpcb_categories",
    `List component categories or subcategories from the local JLCPCB database.

Use this when you want to browse by category or need to find the exact spelling
of a category/subcategory name before passing it to search_jlcpcb_parts.

Two-step drill-down to keep context usage low:
  1. get_jlcpcb_categories()                   → top-level categories only (~750 tokens)
  2. get_jlcpcb_categories(category="Filters") → subcategories for that category (~50 tokens)
  3. search_jlcpcb_parts(category="Filters", subcategory="Ferrite Beads")

Note: free-text query= in search_jlcpcb_parts also works well for component type searches
since ~65% of parts have attribute descriptions — use whichever approach fits the task.`,
    {
      category: z.string().optional()
        .describe("If provided, returns subcategories for this category instead of top-level categories")
    },
    async (args: { category?: string }) => {
      const result = await callKicadScript("get_jlcpcb_categories", args);
      if (result.success) {
        if (result.subcategories) {
          // Drill-down: subcategories for a specific category
          const lines = result.subcategories.map((s: any) =>
            `  • ${s.subcategory} (${s.count.toLocaleString()})`
          );
          return {
            content: [{
              type: "text",
              text: `Subcategories for "${result.category}":\n` + lines.join('\n') +
                    `\n\nUse subcategory= in search_jlcpcb_parts to filter.`
            }]
          };
        }
        if (result.categories) {
          // Top-level categories
          const lines = result.categories.map((c: any) =>
            `  ${c.category} (${c.count.toLocaleString()})`
          );
          return {
            content: [{
              type: "text",
              text: `JLCPCB top-level categories:\n` + lines.join('\n') +
                    `\n\nCall get_jlcpcb_categories(category="<name>") to see subcategories.`
            }]
          };
        }
      }
      return {
        content: [{
          type: "text",
          text: `Failed to load categories. Populate the database using the /download-jlcpcb-db skill.`
        }]
      };
    }
  );

  // Suggest alternative parts
  server.tool(
    "suggest_jlcpcb_alternatives",
    `Suggest alternative JLCPCB parts for a given component.

Finds similar parts that may be cheaper, have more stock, or are Basic library type.
Useful for cost optimization and finding alternatives when parts are out of stock.`,
    {
      lcsc_number: z.string()
        .describe("Reference LCSC part number to find alternatives for"),
      limit: z.number().optional().default(5)
        .describe("Maximum number of alternatives to return")
    },
    async (args: { lcsc_number: string; limit?: number }) => {
      const result = await callKicadScript("suggest_jlcpcb_alternatives", args);
      if (result.success && result.alternatives) {
        if (result.alternatives.length === 0) {
          return {
            content: [{
              type: "text",
              text: `No alternatives found for ${args.lcsc_number}`
            }]
          };
        }

        const altsList = result.alternatives.map((p: any, i: number) => {
          const priceInfo = p.price_breaks && p.price_breaks.length > 0
            ? ` - $${p.price_breaks[0].price}/ea`
            : '';
          const savings = result.reference_price && p.price_breaks && p.price_breaks.length > 0
            ? ` (${((1 - p.price_breaks[0].price / result.reference_price) * 100).toFixed(0)}% cheaper)`
            : '';
          return `${i + 1}. ${p.lcsc}: ${p.mfr_part} [${p.library_type}]${priceInfo}${savings}\n   ${p.description}\n   Stock: ${p.stock}`;
        }).join('\n\n');

        return {
          content: [{
            type: "text",
            text: `Alternative parts for ${args.lcsc_number}:\n\n${altsList}`
          }]
        };
      }
      return {
        content: [{
          type: "text",
          text: `Failed to find alternatives: ${result.message || 'Unknown error'}`
        }]
      };
    }
  );
}
