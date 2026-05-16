"""Tests for SystemVerilog interface parsing."""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

import pytest

from netlist_tracer import NetlistParser
from netlist_tracer.parsers.verilog.instances import _sv_parse_file


def test_simple_interface_creates_subckt() -> None:
    """Test that simple interface without modports creates a SubcktDef."""
    with tempfile.TemporaryDirectory() as tmpdir:
        fpath = Path(tmpdir) / "simple_if.sv"
        content = """interface bus_if;
    logic [7:0] data;
    logic valid;
endinterface
"""
        fpath.write_text(content, encoding="utf-8")

        mdls = _sv_parse_file((str(fpath), {}, set(), {}))

        # Should have one interface entry
        assert len(mdls) >= 1
        intrfc = mdls[0]
        assert intrfc["name"] == "bus_if"
        assert intrfc["params"]["_kind"] == "interface"
        # Check pins (at least data and valid)
        pin_names = [p["name"] for p in intrfc["ports"]]
        assert "valid" in pin_names


def test_interface_with_modports() -> None:
    """Test that interface with modports creates interface + modport SubcktDefs."""
    with tempfile.TemporaryDirectory() as tmpdir:
        fpath = Path(tmpdir) / "if_mport.sv"
        content = """interface bus_if (input logic clk);
    logic [7:0] data;
    logic valid;
    logic ready;

    modport master (
        output data, valid,
        input ready
    );

    modport slave (
        input data, valid,
        output ready
    );

endinterface
"""
        fpath.write_text(content, encoding="utf-8")

        mdls = _sv_parse_file((str(fpath), {}, set(), {}))

        # Should have interface + 2 modports = 3 entries
        assert len(mdls) >= 3

        intrfc = mdls[0]
        assert intrfc["name"] == "bus_if"
        assert intrfc["params"]["_kind"] == "interface"
        assert set(intrfc["params"]["_modports"]) == {"master", "slave"}

        # Check modports exist
        modport_names = [m["name"] for m in mdls[1:3]]
        assert "bus_if__mp_master" in modport_names
        assert "bus_if__mp_slave" in modport_names


def test_modport_pin_directions_correct() -> None:
    """Test that modport pin directions are correctly extracted via full pipeline."""
    with tempfile.TemporaryDirectory() as tmpdir:
        fpath = Path(tmpdir) / "if_mport_dir.sv"
        content = """interface bus_if;
    logic [7:0] data;
    logic valid;
    logic ready;

    modport master (
        output data,
        output valid,
        input ready
    );

endinterface
"""
        fpath.write_text(content, encoding="utf-8")

        # Use full pipeline via NetlistParser, not just _sv_parse_file
        parser = NetlistParser(str(fpath))

        # Find master modport SubcktDef
        master_subckt = parser.subckts.get("bus_if__mp_master")
        assert master_subckt is not None
        assert master_subckt.params["_kind"] == "modport"

        # Check directions: data should be expanded to bit-level keys (data[7]...data[0])
        drctn = master_subckt.params["_pin_directions"]
        # Verify bit-expanded keys exist for bus signal
        assert "data[7]" in drctn, (
            f"Expected data[7] in directions, got keys: {sorted(drctn.keys())}"
        )
        assert "data[0]" in drctn, (
            f"Expected data[0] in directions, got keys: {sorted(drctn.keys())}"
        )
        assert drctn["data[7]"] == "output"
        assert drctn["data[0]"] == "output"
        # Verify scalar signals
        assert drctn["valid"] == "output"
        assert drctn["ready"] == "input"


def test_interface_no_ports_no_modports() -> None:
    """Test interface with no ports and no modports."""
    with tempfile.TemporaryDirectory() as tmpdir:
        fpath = Path(tmpdir) / "trivial_if.sv"
        content = """interface trivial_if;
    logic a;
    logic b;
endinterface
"""
        fpath.write_text(content, encoding="utf-8")

        mdls = _sv_parse_file((str(fpath), {}, set(), {}))

        assert len(mdls) >= 1
        intrfc = mdls[0]
        assert intrfc["name"] == "trivial_if"
        assert intrfc["params"]["_kind"] == "interface"

        pin_names = [p["name"] for p in intrfc["ports"]]
        assert "a" in pin_names
        assert "b" in pin_names


def test_interface_with_parameter() -> None:
    """Test interface with parameter."""
    with tempfile.TemporaryDirectory() as tmpdir:
        fpath = Path(tmpdir) / "param_if.sv"
        content = """interface bus_if #(parameter WIDTH = 4) (input clk);
    logic [WIDTH-1:0] data;
endinterface
"""
        fpath.write_text(content, encoding="utf-8")

        mdls = _sv_parse_file((str(fpath), {}, set(), {}))

        assert len(mdls) >= 1
        intrfc = mdls[0]
        assert intrfc["name"] == "bus_if"
        # Should have clk and data pins
        pin_names = [p["name"] for p in intrfc["ports"]]
        assert "clk" in pin_names


def test_existing_module_unchanged() -> None:
    """Test that existing module parsing is unchanged."""
    with tempfile.TemporaryDirectory() as tmpdir:
        fpath = Path(tmpdir) / "module_test.v"
        content = """module test_mod (
    input clk,
    output reg ready
);
    reg valid;

    always @(posedge clk) begin
        ready <= valid;
    end
endmodule
"""
        fpath.write_text(content, encoding="utf-8")

        mdls = _sv_parse_file((str(fpath), {}, set(), {}))

        assert len(mdls) >= 1
        mod = mdls[0]
        assert mod["name"] == "test_mod"
        # Should NOT have interface params
        assert "params" not in mod or mod.get("params", {}).get("_kind") != "interface"


def test_no_subckt_key_collisions() -> None:
    """Test that interface and modport keys don't collide."""
    with tempfile.TemporaryDirectory() as tmpdir:
        fpath = Path(tmpdir) / "no_collide.sv"
        content = """interface bus_if;
    logic [7:0] data;

    modport master (output data);
    modport slave (input data);
endinterface
"""
        fpath.write_text(content, encoding="utf-8")

        mdls = _sv_parse_file((str(fpath), {}, set(), {}))

        names = [m["name"] for m in mdls]
        assert "bus_if" in names
        assert "bus_if__mp_master" in names
        assert "bus_if__mp_slave" in names

        # Check uniqueness
        assert len(names) == len(set(names))


@pytest.mark.local
@pytest.mark.skipif(
    not os.environ.get("NETLIST_TRACER_SV_INTERFACE_CORPUS"),
    reason="NETLIST_TRACER_SV_INTERFACE_CORPUS not set",
)
def test_ac9_real_interface_corpus() -> None:
    """Regression: NT parses real-world .sv files containing SystemVerilog interface
    blocks. Auto-discovers a candidate file in the corpus directory to avoid
    hardcoding any private filename.
    """
    corpus_dir = Path(os.environ["NETLIST_TRACER_SV_INTERFACE_CORPUS"])
    assert corpus_dir.is_dir(), f"Corpus directory not found: {corpus_dir}"

    target = None
    for fp in sorted(corpus_dir.glob("*.sv")):
        try:
            head = fp.read_text(encoding="utf-8", errors="replace")[:8192]
        except OSError:
            continue
        if re.search(r"\binterface\s+\w+", head):
            target = fp
            break

    assert target is not None, (
        f"No .sv file containing an `interface` declaration found under {corpus_dir}"
    )

    parser = NetlistParser(str(target))
    assert len(parser.subckts) > 0, f"NT produced no SubcktDefs for {target.name}"

    interfaces = [
        (name, sub)
        for name, sub in parser.subckts.items()
        if sub.params.get("_kind") == "interface"
    ]
    assert interfaces, (
        f"Expected at least one interface SubcktDef in {target.name}; "
        f"found kinds: {sorted({sub.params.get('_kind', 'module') for sub in parser.subckts.values()})}"
    )
