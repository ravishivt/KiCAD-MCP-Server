"""
Unit/integration tests for connectivity & hierarchy commands (commands/schematic_hierarchy.py).

validate_schematic and the hierarchical-sheet text manipulation are exercised against real
files in tmp; PinLocator/WireManager are stubbed for the pin-label tests. No KiCad needed.
"""

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from commands import schematic_hierarchy as hier  # noqa: E402
from commands.schematic_hierarchy import SchematicHierarchyCommands  # noqa: E402


def _cmds(iface=None):
    return SchematicHierarchyCommands(iface or types.SimpleNamespace())


class TestValidateSchematic:
    def test_valid(self, tmp_path):
        f = tmp_path / "ok.kicad_sch"
        f.write_text('(kicad_sch (uuid "a") (paper "A4"))')
        r = _cmds().validate_schematic({"schematicPath": str(f)})
        assert r["success"] is True and r["valid"] is True

    def test_paren_underflow(self, tmp_path):
        f = tmp_path / "bad.kicad_sch"
        f.write_text("(kicad_sch ))")
        r = _cmds().validate_schematic({"schematicPath": str(f)})
        assert r["valid"] is False and "underflow" in r["error"]

    def test_unclosed(self, tmp_path):
        f = tmp_path / "open.kicad_sch"
        f.write_text("(kicad_sch (paper")
        r = _cmds().validate_schematic({"schematicPath": str(f)})
        assert r["valid"] is False and r["unclosed"] == 2

    def test_parens_in_strings_ignored(self, tmp_path):
        f = tmp_path / "str.kicad_sch"
        f.write_text('(kicad_sch (property "Value" "f(x))") )')
        assert _cmds().validate_schematic({"schematicPath": str(f)})["valid"] is True

    def test_missing(self):
        assert _cmds().validate_schematic({})["success"] is False
        assert (
            _cmds().validate_schematic({"schematicPath": "/no/such.kicad_sch"})["success"] is False
        )


class TestAddJunction:
    def test_requires_params(self):
        assert _cmds().add_schematic_junction({"schematicPath": "/x"})["success"] is False
        assert _cmds().add_schematic_junction({"position": [1, 2]})["success"] is False

    def test_inserts_junction(self, tmp_path):
        f = tmp_path / "j.kicad_sch"
        f.write_text('(kicad_sch (uuid "abcd") (sheet_instances (path "/" (page "1"))))')
        r = _cmds().add_schematic_junction({"schematicPath": str(f), "position": [25.4, 25.4]})
        assert r["success"] is True
        content = f.read_text()
        assert "junction" in content and "25.4" in content


class TestPlaceNetLabelAtPin:
    def test_requires_params(self):
        assert (
            _cmds().place_net_label_at_pin({"schematicPath": "/x", "reference": "U1"})["success"]
            is False
        )

    def test_places_label(self, monkeypatch, tmp_path):
        f = tmp_path / "s.kicad_sch"
        f.write_text("(kicad_sch)")
        loc = types.SimpleNamespace(
            get_pin_location=lambda p, r, pin: [10.0, 20.0],
            get_pin_angle=lambda p, r, pin: 0,
            get_all_symbol_pins=lambda p, r: {"1": [10.0, 20.0]},
        )
        labels = []
        wm = types.SimpleNamespace(
            add_label=lambda p, net, pos, label_type="label", orientation=0: labels.append(
                (net, orientation)
            )
            or True,
            add_wire=lambda *a: True,
        )
        monkeypatch.setattr(hier, "PinLocator", lambda: loc)
        monkeypatch.setattr(hier, "WireManager", wm)
        monkeypatch.setattr(hier, "_find_facing_label", lambda *a, **k: None)
        r = _cmds().place_net_label_at_pin(
            {"schematicPath": str(f), "reference": "U1", "pinNumber": "1", "netName": "SDA"}
        )
        assert r["success"] is True
        assert labels == [("SDA", 180)]  # pin angle 0 -> orientation 180

    def test_wires_to_facing_label(self, monkeypatch, tmp_path):
        f = tmp_path / "s.kicad_sch"
        f.write_text("(kicad_sch)")
        loc = types.SimpleNamespace(
            get_pin_location=lambda p, r, pin: [10.0, 20.0],
            get_pin_angle=lambda p, r, pin: 0,
            get_all_symbol_pins=lambda p, r: {"1": [10.0, 20.0]},
        )
        wires = []
        wm = types.SimpleNamespace(
            add_wire=lambda p, a, b: wires.append((a, b)) or True,
            add_label=lambda *a, **k: True,
        )
        monkeypatch.setattr(hier, "PinLocator", lambda: loc)
        monkeypatch.setattr(hier, "WireManager", wm)
        monkeypatch.setattr(hier, "_find_facing_label", lambda *a, **k: [30.0, 20.0])
        r = _cmds().place_net_label_at_pin(
            {"schematicPath": str(f), "reference": "U1", "pinNumber": "1", "netName": "VBUS"}
        )
        assert r["success"] is True
        assert wires == [([10.0, 20.0], [30.0, 20.0])]
        assert "Wired to existing" in r["note"]


class TestAddHierarchicalSheet:
    def test_requires_params(self):
        assert _cmds().add_hierarchical_sheet({"schematicPath": "/x"})["success"] is False

    def test_inserts_sheet_block(self, tmp_path):
        parent = tmp_path / "top.kicad_sch"
        parent.write_text(
            '(kicad_sch (uuid abcd-1234)\n  (sheet_instances (path "/" (page "1")))\n)'
        )
        r = _cmds().add_hierarchical_sheet(
            {
                "schematicPath": str(parent),
                "subsheetPath": str(tmp_path / "sub.kicad_sch"),
                "sheetName": "Power",
            }
        )
        assert r["success"] is True
        assert r["page"] == 2  # next page after existing "1"
        content = parent.read_text()
        assert "(sheet " in content
        assert '"Sheet name" "Power"' in content
        assert '"Sheet file" "sub.kicad_sch"' in content
        # a sheet_instances path entry for the new sheet block was added
        assert f'/{ "abcd-1234" }/{ r["sheet_uuid"] }' in content


class TestCreateHierarchicalSubsheet:
    def test_orchestrates(self):
        iface = types.SimpleNamespace(
            _handle_create_schematic=lambda p: {
                "success": True,
                "file_path": p["filename"],
                "schematic_uuid": "sub-uuid",
            }
        )
        c = SchematicHierarchyCommands(iface)
        c.add_hierarchical_sheet = lambda p: {"success": True, "sheet_uuid": "blk", "page": 2}
        r = c.create_hierarchical_subsheet(
            {
                "parentSchematicPath": "/top.kicad_sch",
                "subsheetPath": "/sub.kicad_sch",
                "sheetName": "IO",
            }
        )
        assert r["success"] is True
        assert r["sheet_block_uuid"] == "blk" and r["page"] == 2

    def test_requires_params(self):
        assert (
            _cmds().create_hierarchical_subsheet({"parentSchematicPath": "/x"})["success"] is False
        )


class TestFixSubsheetInstances:
    def test_adds_path_entry(self, tmp_path):
        sub = tmp_path / "sub.kicad_sch"
        sub.write_text(
            '(kicad_sch (symbol (lib_id "Device:R")'
            ' (instances (project "proj" (path "/old" (reference "R1") (unit 1))))))'
        )
        parent = tmp_path / "top.kicad_sch"
        parent_content = (
            "(kicad_sch (uuid abcd-1234)"
            ' (sheet (at 50 50) (uuid "sheet-blk-1")'
            ' (property "Sheet name" "Sub" (at 1 1 0))'
            ' (property "Sheet file" "sub.kicad_sch" (at 1 2 0)))'
            ' (sheet_instances (path "/" (page "1"))))'
        )
        parent.write_text(parent_content)

        modified = _cmds().fix_subsheet_instances(str(parent), parent_content)
        assert str(sub) in modified
        sub_after = sub.read_text()
        assert "/abcd-1234/sheet-blk-1" in sub_after
        assert '(reference "R1")' in sub_after
