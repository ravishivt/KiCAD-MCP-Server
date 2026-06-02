"""
Unit tests for schematic net/design analysis commands (commands/schematic_net_analysis.py).

Connectivity primitives (SchematicManager / ConnectionManager / PinLocator) are stubbed,
so these tests are fast and have no dependency on a real KiCad install or schematic file.
"""

import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from commands import schematic_net_analysis as na  # noqa: E402
from commands.schematic_net_analysis import (  # noqa: E402
    SchematicNetAnalysisCommands,
    _classify_net_type,
    _collect_net_names,
    _is_power_or_ground,
    _pin_metadata,
)


def _label(value, at=None):
    ns = types.SimpleNamespace(value=value)
    if at is not None:
        ns.at = types.SimpleNamespace(value=at)
    return ns


def _symbol(ref, lib_id="Device:R", props=None):
    prop = types.SimpleNamespace(Reference=types.SimpleNamespace(value=ref))
    for k, v in (props or {}).items():
        setattr(prop, k, types.SimpleNamespace(value=v))
    return types.SimpleNamespace(property=prop, lib_id=types.SimpleNamespace(value=lib_id))


def _schematic(labels=None, global_labels=None, symbols=None, wires=None, no_connects=None):
    return types.SimpleNamespace(
        label=labels or [],
        global_label=global_labels or [],
        symbol=symbols or [],
        wire=wires or [],
        no_connect=no_connects or [],
    )


class TestHelpers:
    def test_is_power_or_ground(self):
        assert _is_power_or_ground("GND")
        assert _is_power_or_ground("+3V3")
        assert _is_power_or_ground("VCC")
        assert not _is_power_or_ground("SDA")

    @pytest.mark.parametrize(
        "name,has_pwr,expected",
        [
            ("GND", False, "ground"),
            ("AGND", False, "ground"),
            ("+5V", False, "power_rail"),
            ("SOME_NET", True, "power_rail"),  # has power symbol attached
            ("SPI_CLK", False, "clock"),
            ("SDA", False, "signal"),
        ],
    )
    def test_classify_net_type(self, name, has_pwr, expected):
        assert _classify_net_type(name, has_pwr, {name}) == expected

    def test_classify_differential_pair(self):
        names = {"USB_P", "USB_N"}
        assert _classify_net_type("USB_P", False, names) == "differential_pair"
        assert _classify_net_type("USB_N", False, names) == "differential_pair"

    def test_collect_net_names(self):
        sch = _schematic(labels=[_label("A"), _label("B")], global_labels=[_label("VBUS")])
        assert _collect_net_names(sch) == {"A", "B", "VBUS"}

    def test_pin_metadata(self):
        loc = types.SimpleNamespace(
            _get_lib_id=lambda p, r: "Device:R",
            get_symbol_pins=lambda p, lib: {"1": {"name": "~", "type": "passive"}},
        )
        assert _pin_metadata(loc, Path("/x"), "R1", "1") == {"name": "~", "type": "passive"}

    def test_pin_metadata_no_lib(self):
        loc = types.SimpleNamespace(_get_lib_id=lambda p, r: None)
        assert _pin_metadata(loc, Path("/x"), "R1", "1") == {}


class TestParamValidation:
    def setup_method(self):
        self.c = SchematicNetAnalysisCommands()

    def test_each_requires_schematic_path(self):
        for fn in (
            self.c.list_unconnected_pins,
            self.c.find_single_pin_nets,
            self.c.classify_nets,
            self.c.get_net_graph,
            self.c.get_schematic_summary,
        ):
            assert fn({})["success"] is False

    def test_topology_requires_net_name(self):
        assert self.c.get_net_topology({"schematicPath": "/x.kicad_sch"})["success"] is False


class TestFindSinglePinNets:
    def test_happy_path(self, monkeypatch, tmp_path):
        sch_file = tmp_path / "x.kicad_sch"
        sch_file.write_text("(kicad_sch)")
        fake_sch = _schematic(labels=[_label("DANGLE"), _label("OK")])

        monkeypatch.setattr(
            na, "SchematicManager", types.SimpleNamespace(load_schematic=lambda p: fake_sch)
        )
        conns = {
            "DANGLE": [{"component": "R1", "pin": "1"}],
            "OK": [{"component": "R1", "pin": "2"}, {"component": "R2", "pin": "1"}],
        }
        monkeypatch.setattr(
            na,
            "ConnectionManager",
            types.SimpleNamespace(get_net_connections=lambda s, name, p: conns.get(name, [])),
        )
        monkeypatch.setattr(
            na,
            "PinLocator",
            lambda: types.SimpleNamespace(
                _get_lib_id=lambda p, r: "Device:R",
                get_symbol_pins=lambda p, lib: {"1": {"name": "PIN1"}},
            ),
        )

        r = SchematicNetAnalysisCommands().find_single_pin_nets({"schematicPath": str(sch_file)})
        assert r["success"] is True
        assert r["count"] == 1
        assert r["singlePinNets"][0]["netName"] == "DANGLE"
        assert r["singlePinNets"][0]["pinName"] == "PIN1"


class TestGetNetTopology:
    def test_no_labels_returns_empty(self, monkeypatch):
        monkeypatch.setattr(
            na,
            "SchematicManager",
            types.SimpleNamespace(load_schematic=lambda p: _schematic()),
        )
        r = SchematicNetAnalysisCommands().get_net_topology(
            {"schematicPath": "/x.kicad_sch", "netName": "MISSING"}
        )
        assert r["success"] is True
        assert r["wire_segments"] == [] and "No labels" in r["message"]

    def test_traces_wire_from_label(self, monkeypatch):
        # Label at (0,0); a wire from (0,0)->(10,0); no pins.
        wire = types.SimpleNamespace(
            pts=types.SimpleNamespace(
                xy=[
                    types.SimpleNamespace(value=[0.0, 0.0]),
                    types.SimpleNamespace(value=[10.0, 0.0]),
                ]
            )
        )
        fake_sch = _schematic(labels=[_label("NET1", at=[0.0, 0.0, 0])], wires=[wire])
        monkeypatch.setattr(
            na, "SchematicManager", types.SimpleNamespace(load_schematic=lambda p: fake_sch)
        )
        monkeypatch.setattr(na, "PinLocator", lambda: types.SimpleNamespace())

        r = SchematicNetAnalysisCommands().get_net_topology(
            {"schematicPath": "/x.kicad_sch", "netName": "NET1"}
        )
        assert r["success"] is True
        assert len(r["wire_segments"]) == 1
        assert len(r["labels"]) == 1
        # The (10,0) end touches one wire, no pin, no label -> dangling.
        assert {"x": 10.0, "y": 0.0} in r["dangling_endpoints"]
