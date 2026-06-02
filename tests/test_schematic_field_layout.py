"""
Unit + integration tests for schematic field-placement/layout commands.

The text S-expression helpers and the set/batch property writers are exercised against a
real minimal .kicad_sch written to a temp file (pure text manipulation — no KiCad needed).
check_schematic_layout / autoplace_schematic_fields are tested for parameter validation;
their geometry helpers are unit-tested directly.
"""

import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from commands import schematic_field_layout as fl  # noqa: E402
from commands.schematic_field_layout import (  # noqa: E402
    SchematicFieldLayoutCommands,
    _bbox_overlaps,
    _extract_component_properties,
    _extract_property_position,
    _extract_property_visible,
    _find_matching_paren,
    _find_placed_symbol_block,
    _gather_labels,
    _get_sheet_usable_area,
    _move_property_in_block,
    _point_in_bbox,
)

MINIMAL_SCH = """(kicad_sch (version 20230121) (paper "A4")
  (lib_symbols
    (symbol "Device:R" (property "Reference" "R" (at 0 0 0)))
  )
  (symbol (lib_id "Device:R") (at 100 100 0) (uuid "11111111")
    (property "Reference" "R1" (at 102.0 98.0 0)
      (effects (font (size 1.27 1.27))))
    (property "Value" "10k" (at 102.0 102.0 0)
      (effects (font (size 1.27 1.27))))
  )
  (symbol (lib_id "Device:C") (at 150 100 0) (uuid "22222222")
    (property "Reference" "C1" (at 152.0 98.0 0)
      (effects (font (size 1.27 1.27))))
    (property "Value" "100nF" (at 152.0 102.0 0)
      (effects (font (size 1.27 1.27))))
  )
)
"""


class TestTextHelpers:
    def test_find_matching_paren(self):
        s = "(a (b) c)"
        assert _find_matching_paren(s, 0) == len(s) - 1
        assert _find_matching_paren(s, 3) == 5

    def test_find_placed_symbol_block_skips_lib_symbols(self):
        block, start, end = _find_placed_symbol_block(MINIMAL_SCH, "R1")
        assert block is not None
        # Must be the placed instance (has lib_id + (at 100 100 0)), not the lib_symbols def
        assert '(lib_id "Device:R")' in block and "(at 100 100 0)" in block

    def test_find_placed_symbol_block_missing(self):
        assert _find_placed_symbol_block(MINIMAL_SCH, "R99") == (None, -1, -1)

    def test_extract_property_position(self):
        block, _, _ = _find_placed_symbol_block(MINIMAL_SCH, "R1")
        assert _extract_property_position(block, "Reference") == {
            "x": 102.0,
            "y": 98.0,
            "angle": 0.0,
        }

    def test_extract_property_visible(self):
        block, _, _ = _find_placed_symbol_block(MINIMAL_SCH, "R1")
        assert _extract_property_visible(block, "Reference") is True

    def test_extract_component_properties(self):
        block, _, _ = _find_placed_symbol_block(MINIMAL_SCH, "R1")
        props = _extract_component_properties(block)
        assert props["Reference"] == "R1" and props["Value"] == "10k"

    def test_move_property_in_block_and_hide(self):
        block, _, _ = _find_placed_symbol_block(MINIMAL_SCH, "R1")
        new_block, n = _move_property_in_block(block, "Reference", 105, 95, 0, visible=False)
        assert n == 1
        assert "(at 105 95 0)" in new_block
        assert "(hide yes)" in new_block
        # Re-show it
        reshown, _ = _move_property_in_block(new_block, "Reference", 105, 95, 0, visible=True)
        assert "(hide yes)" not in reshown

    def test_move_property_missing(self):
        block, _, _ = _find_placed_symbol_block(MINIMAL_SCH, "R1")
        _, n = _move_property_in_block(block, "Footprint", 1, 2, 0, True)
        assert n == 0


class TestGeometryHelpers:
    def test_bbox_overlaps(self):
        a = {"x_min": 0, "y_min": 0, "x_max": 10, "y_max": 10}
        b = {"x_min": 5, "y_min": 5, "x_max": 15, "y_max": 15}
        c = {"x_min": 20, "y_min": 20, "x_max": 30, "y_max": 30}
        assert _bbox_overlaps(a, b)
        assert not _bbox_overlaps(a, c)
        assert _bbox_overlaps(a, c, margin=11)  # margin bridges the gap

    def test_point_in_bbox(self):
        bb = {"x_min": 0, "y_min": 0, "x_max": 10, "y_max": 10}
        assert _point_in_bbox(5, 5, bb)
        assert not _point_in_bbox(11, 5, bb)

    def test_get_sheet_usable_area_default_a4(self, tmp_path):
        f = tmp_path / "a4.kicad_sch"
        f.write_text('(kicad_sch (paper "A4")')
        left, top, right, bottom = _get_sheet_usable_area(str(f))
        assert (left, top) == (12.7, 12.7)
        assert right == pytest.approx(297.0 - 12.7)
        assert bottom == pytest.approx(210.0 - 12.7)

    def test_get_sheet_usable_area_a3(self, tmp_path):
        f = tmp_path / "a3.kicad_sch"
        f.write_text('(kicad_sch (paper "A3")')
        _, _, right, _ = _get_sheet_usable_area(str(f))
        assert right == pytest.approx(420.0 - 12.7)

    def test_gather_labels(self):
        def lbl(v, at):
            return types.SimpleNamespace(value=v, at=types.SimpleNamespace(value=at))

        sch = types.SimpleNamespace(
            label=[lbl("SDA", [1, 2, 0])], global_label=[lbl("VBUS", [3, 4, 90])]
        )
        labels = _gather_labels(sch)
        assert {x["name"] for x in labels} == {"SDA", "VBUS"}
        vbus = next(x for x in labels if x["name"] == "VBUS")
        assert vbus["type"] == "global" and vbus["angle"] == 90.0


class TestSetPropertyPosition:
    def _sch(self, tmp_path):
        f = tmp_path / "x.kicad_sch"
        f.write_text(MINIMAL_SCH)
        return f

    def test_missing_params(self):
        c = SchematicFieldLayoutCommands()
        assert (
            c.set_schematic_property_position({"schematicPath": "/x", "reference": "R1"})["success"]
            is False
        )

    def test_rejects_non_ref_value(self, tmp_path):
        f = self._sch(tmp_path)
        c = SchematicFieldLayoutCommands()
        r = c.set_schematic_property_position(
            {"schematicPath": str(f), "reference": "R1", "property": "Footprint", "x": 1, "y": 2}
        )
        assert r["success"] is False

    def test_moves_field(self, tmp_path):
        f = self._sch(tmp_path)
        c = SchematicFieldLayoutCommands()
        r = c.set_schematic_property_position(
            {"schematicPath": str(f), "reference": "R1", "property": "Reference", "x": 105, "y": 95}
        )
        assert r["success"] is True
        content = f.read_text()
        assert '(property "Reference" "R1" (at 105 95 0)' in content
        # C1 left untouched
        assert '(property "Reference" "C1" (at 152.0 98.0 0)' in content

    def test_component_not_found(self, tmp_path):
        f = self._sch(tmp_path)
        c = SchematicFieldLayoutCommands()
        r = c.set_schematic_property_position(
            {"schematicPath": str(f), "reference": "R99", "property": "Value", "x": 1, "y": 2}
        )
        assert r["success"] is False


class TestBatchSetPropertyPositions:
    def test_batch_applies_and_reports(self, tmp_path):
        f = tmp_path / "x.kicad_sch"
        f.write_text(MINIMAL_SCH)
        c = SchematicFieldLayoutCommands()
        r = c.batch_set_schematic_property_positions(
            {
                "schematicPath": str(f),
                "updates": [
                    {"reference": "R1", "property": "Reference", "x": 90, "y": 90},
                    {"reference": "C1", "property": "Value", "x": 160, "y": 110},
                    {"reference": "R99", "property": "Value", "x": 0, "y": 0},  # should fail
                ],
            }
        )
        assert r["applied_count"] == 2
        assert r["failed_count"] == 1
        assert r["success"] is False  # because one failed
        content = f.read_text()
        assert '(property "Reference" "R1" (at 90 90 0)' in content
        assert '(property "Value" "100nF" (at 160 110 0)' in content

    def test_requires_updates(self, tmp_path):
        f = tmp_path / "x.kicad_sch"
        f.write_text(MINIMAL_SCH)
        c = SchematicFieldLayoutCommands()
        assert (
            c.batch_set_schematic_property_positions({"schematicPath": str(f)})["success"] is False
        )


class TestCheckAndAutoplaceValidation:
    def test_check_requires_path(self):
        assert SchematicFieldLayoutCommands().check_schematic_layout({})["success"] is False

    def test_autoplace_requires_path(self):
        assert SchematicFieldLayoutCommands().autoplace_schematic_fields({})["success"] is False

    def test_check_missing_file(self):
        r = SchematicFieldLayoutCommands().check_schematic_layout(
            {"schematicPath": "/nope/x.kicad_sch"}
        )
        assert r["success"] is False

    def test_check_layout_integration(self, tmp_path, monkeypatch):
        # Use the real minimal schematic but stub the schematic loader + pin locator so the
        # full check pipeline runs without KiCad. No pins => body_bbox falls back to position pad.
        f = tmp_path / "x.kicad_sch"
        f.write_text(MINIMAL_SCH)
        fake_sch = types.SimpleNamespace(symbol=[], label=[], global_label=[])
        monkeypatch.setattr(
            fl, "SchematicManager", types.SimpleNamespace(load_schematic=lambda p: fake_sch)
        )
        monkeypatch.setattr(
            fl,
            "PinLocator",
            lambda: types.SimpleNamespace(
                get_all_symbol_pins=lambda *a: {}, get_symbol_pins=lambda *a: {}
            ),
        )
        r = SchematicFieldLayoutCommands().check_schematic_layout({"schematicPath": str(f)})
        assert r["success"] is True
        assert "violation_count" in r and "sheet_usable_area" in r
