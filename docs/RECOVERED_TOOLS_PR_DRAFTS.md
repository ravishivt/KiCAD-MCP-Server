# Recovered schematic tools — upstream PR drafts

This document contains ready-to-submit PR descriptions for the 25 schematic MCP tools
recovered onto current `upstream/main`. The work was originally lost when an upstream
merge resolved `python/kicad_interface.py` entirely in upstream's favour; it has been
re-ported, restructured into self-contained modules, and covered with tests.

Each module is independent and can be submitted as its own PR. They are ordered by
dependency (later PRs may import helpers from earlier ones).

Design notes common to all PRs:
- Handlers live in dedicated `python/commands/*.py` modules (not inlined into
  `kicad_interface.py`), so future upstream merges have a minimal conflict surface.
- Each module exposes a `*Commands` class; `kicad_interface.py` only gains a one-line
  import, a one-line instantiation, and the dispatch-table entries.
- TS tool wrappers live in dedicated `src/tools/schematic-*.ts` files registered in
  `src/server.ts`, with catalog entries in `src/tools/registry.ts`.
- Every module has env-independent unit tests (KiCad/`pcbnew` not required).

---

## PR 1 — Symbol & pin discovery tools

**Tools:** `search_schematic_symbols`, `list_symbol_pins`, `batch_list_symbol_pins`,
`get_component_pin_positions`

Read-only tools to inspect symbol pins and search symbol libraries without a schematic
loaded — a pre-flight step before placing/wiring components.

- `python/commands/symbol_pins.py` — `SymbolPinCommands`; ports a `list_symbol_pins`
  parser on top of upstream `DynamicSymbolLoader.extract_symbol_from_library`
  (upstream's loader has `find_kicad_symbol_libraries`/`_resolve_sym_uri` but no pin reader).
- `src/tools/library-symbol.ts` — adds the 4 tool wrappers.
- `src/tools/registry.ts` — `symbol_library` category.
- `tests/test_symbol_pins.py` (16 tests).

## PR 2 — Schematic net / design-analysis tools

**Tools:** `list_unconnected_pins`, `find_single_pin_nets`, `classify_nets`,
`get_net_graph`, `get_schematic_summary`, `get_net_topology`

Read-only connectivity review for design QA / LLM context.

- `python/commands/schematic_net_analysis.py` — `SchematicNetAnalysisCommands`; reuses
  upstream `ConnectionManager.get_net_connections`/`generate_netlist` and `PinLocator`;
  re-implements the small `get_pin_metadata` / `build_full_netmap` helpers locally.
- `src/tools/schematic-analysis.ts`, `src/server.ts`, `src/tools/registry.ts`
  (`schematic_analysis` category).
- `tests/test_schematic_net_analysis.py` (16 tests).

## PR 3 — Schematic field placement & layout checking

**Tools:** `set_schematic_property_position`, `batch_set_schematic_property_positions`,
`check_schematic_layout`, `autoplace_schematic_fields`

Move Ref/Value field labels, audit layout (out-of-bounds, overlaps, fields-in-bodies,
duplicate labels, stray wires) with optional autofix, and net-label-aware auto-placement.

- `python/commands/schematic_field_layout.py` — `SchematicFieldLayoutCommands`; ports the
  text S-expression helpers (`_find_placed_symbol_block`, `_extract_property_position`,
  `_extract_property_visible`, `_get_sheet_usable_area`, etc.) and gathers enriched
  component/label data directly (upstream `list_schematic_components` doesn't emit
  `body_bbox`/`ref_field`/`value_field`). Also home to the shared `_find_facing_label`
  and `_find_project_root` helpers.
- `src/tools/schematic-layout.ts`, `src/server.ts`, `src/tools/registry.ts`
  (`schematic_layout` category).
- `tests/test_schematic_field_layout.py` (23 tests, incl. end-to-end set/batch on a real .kicad_sch).

## PR 4 — Batch schematic authoring

**Tools:** `batch_add_components`, `batch_edit_schematic_components`,
`replace_schematic_component`, `batch_add_no_connects`, `batch_connect`,
`batch_add_and_connect`

Fewest-round-trip placement and wiring.

- `python/commands/schematic_batch.py` — `SchematicBatchCommands(iface)`; reuses upstream
  single-item handlers (`add`/`edit`/`get_schematic_component`), `DynamicSymbolLoader`,
  `WireManager`, `PinLocator`, and the PR-3 text helpers. Note: upstream's
  `DynamicSymbolLoader.add_component` takes `angle=` (the fork's used `rotation=`) — remapped.
- `src/tools/schematic-batch.ts`, `src/server.ts`, `src/tools/registry.ts`
  (`schematic_batch` category).
- `tests/test_schematic_batch.py` (13 tests).
- Depends on PR 3 (text helpers) and PR 5 (`fix_subsheet_instances`, reached at runtime
  via the interface — no import cycle).

## PR 5 — Connectivity & hierarchy

**Tools:** `add_schematic_junction`, `place_net_label_at_pin`, `add_hierarchical_sheet`,
`create_hierarchical_subsheet`, `validate_schematic`

Junction dots (with wire splitting via upstream `WireManager._break_wires_at_point`),
exact pin-endpoint net labels, hierarchical sheet insertion/creation, and a fast
parenthesis-balance validator. Also restores `fix_subsheet_instances` (used by PR 4).

- `python/commands/schematic_hierarchy.py` — `SchematicHierarchyCommands(iface)`.
- `src/tools/schematic-hierarchy.ts`, `src/server.ts`, `src/tools/registry.ts`
  (`schematic_hierarchy` category).
- `tests/test_schematic_hierarchy.py` (15 tests).

---

## Registry hygiene (fold into PR 1 or a standalone cleanup PR)

`src/tools/registry.ts` `schematic` category was corrected while wiring these in:
- replaced the non-existent `add_wire` with the real `add_schematic_wire`;
- restored `add_schematic_text` / `list_schematic_texts` (real tools that had been dropped);
- moved batch/hierarchy tools into their dedicated categories.
