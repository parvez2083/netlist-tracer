"""Unit tests for Verilog-A parser support."""

import logging
import os
import tempfile

from netlist_tracer import NetlistParser


def test_verilog_a_leaf_detection(synthetic_verilog_a_leaf_va):
    """Test that Verilog-A leaf cells are correctly detected and parsed."""
    parser = NetlistParser(synthetic_verilog_a_leaf_va)
    assert parser.format == "verilog"
    assert "verilog_a_leaf" in parser.subckts, "Should detect va_leaf module"
    subckt = parser.subckts["verilog_a_leaf"]
    assert subckt.pins == ["inp", "outp"], (
        f"va_leaf should have pins ['inp', 'outp'], got {subckt.pins}"
    )


def test_verilog_a_parent_with_leaf():
    """Test parsing parent module with instantiated Verilog-A leaf cell.

    Verifies that:
    1. Both parent and leaf modules are recognized
    2. Leaf module appears as a SubcktDef with correct pins
    3. Instance connection is registered
    4. Analog behavioral blocks are stripped (no parse errors)
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create Verilog-A leaf
        leaf_path = os.path.join(tmpdir, "leaf.va")
        with open(leaf_path, "w") as f:
            f.write("module va_leaf (electrical inp, electrical outp);\n")
            f.write("  analog begin\n")
            f.write("    V(outp, inp) <+ 0.0;\n")
            f.write("  end\n")
            f.write("endmodule\n")

        # Create Verilog parent
        parent_path = os.path.join(tmpdir, "parent.v")
        with open(parent_path, "w") as f:
            f.write("module top (input a, output y);\n")
            f.write("  va_leaf u_leaf (.inp(a), .outp(y));\n")
            f.write("endmodule\n")

        # Parse directory
        parser = NetlistParser(tmpdir)

        # Verify both modules are recognized
        assert "va_leaf" in parser.subckts, "Should find va_leaf module"
        assert "top" in parser.subckts, "Should find top module"

        # Verify va_leaf pins (electrical ports treated as standard pins)
        va_leaf = parser.subckts["va_leaf"]
        assert va_leaf.pins == ["inp", "outp"], (
            f"va_leaf should have ['inp', 'outp'], got {va_leaf.pins}"
        )

        # Verify instance connection
        assert "top" in parser.instances_by_parent, "top should have instances"
        insts = parser.instances_by_parent["top"]
        assert len(insts) == 1, f"top should have 1 instance, got {len(insts)}"
        assert insts[0].name == "u_leaf", f"Instance name should be u_leaf, got {insts[0].name}"
        assert insts[0].cell_type == "va_leaf", (
            f"Instance cell_type should be va_leaf, got {insts[0].cell_type}"
        )


def test_ahdl_include_resolves_relative_va():
    """Test ahdl_include directive resolves relative VA file paths."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create VA leaf in subdirectory
        subdir = os.path.join(tmpdir, "subdir")
        os.makedirs(subdir)
        va_leaf = os.path.join(subdir, "va_leaf.va")
        with open(va_leaf, "w") as f:
            f.write("module va_leaf (electrical inp, electrical outp);\n")
            f.write("  analog begin\n")
            f.write("    V(outp, inp) <+ 0.0;\n")
            f.write("  end\n")
            f.write("endmodule\n")

        # Create Spectre netlist with ahdl_include
        deck_path = os.path.join(tmpdir, "tb.scs")
        with open(deck_path, "w") as f:
            f.write("simulator lang=spectre\n")
            f.write('ahdl_include "subdir/va_leaf.va"\n')
            f.write("subckt tb (vdd vss)\n")
            f.write("ends tb\n")

        # Parse the deck
        parser = NetlistParser(deck_path)

        # Verify va_leaf was loaded via ahdl_include
        assert "va_leaf" in parser.subckts, "va_leaf should be loaded from ahdl_include"
        assert parser.subckts["va_leaf"].pins == ["inp", "outp"]
        assert "tb" in parser.subckts, "tb subckt should also be present"


def test_ahdl_include_resolves_env_var(monkeypatch):
    """Test ahdl_include directive resolves environment variables."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create VA leaf in tmpdir
        va_leaf = os.path.join(tmpdir, "va_leaf.va")
        with open(va_leaf, "w") as f:
            f.write("module va_leaf (electrical inp, electrical outp);\n")
            f.write("  analog begin\n")
            f.write("    V(outp, inp) <+ 0.0;\n")
            f.write("  end\n")
            f.write("endmodule\n")

        # Create Spectre netlist with ahdl_include using env var
        deck_path = os.path.join(tmpdir, "tb.scs")
        with open(deck_path, "w") as f:
            f.write("simulator lang=spectre\n")
            f.write('ahdl_include "$VA_DIR/va_leaf.va"\n')
            f.write("subckt tb (vdd vss)\n")
            f.write("ends tb\n")

        # Set VA_DIR env var
        monkeypatch.setenv("VA_DIR", tmpdir)

        # Parse the deck
        parser = NetlistParser(deck_path)

        # Verify va_leaf was loaded
        assert "va_leaf" in parser.subckts, "va_leaf should be loaded from env var path"
        assert parser.subckts["va_leaf"].pins == ["inp", "outp"]


def test_ahdl_include_missing_path_warns_and_continues(caplog):
    """Test ahdl_include with missing path emits WARNING and continues parsing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create Spectre netlist with unresolvable ahdl_include
        deck_path = os.path.join(tmpdir, "tb.scs")
        with open(deck_path, "w") as f:
            f.write("simulator lang=spectre\n")
            f.write('ahdl_include "definitely_not_there.va"\n')
            f.write("subckt tb (vdd vss)\n")
            f.write("  r1 (vdd vss) resistor r=1k\n")
            f.write("ends tb\n")

        # Capture warnings
        with caplog.at_level(logging.WARNING):
            parser = NetlistParser(deck_path)

        # Verify parser did NOT raise and parsed tb subckt
        assert "tb" in parser.subckts, "Parent subckt should parse despite missing ahdl_include"

        # Verify WARNING was logged
        warning_text = caplog.text.lower()
        assert "ahdl_include" in warning_text or "unresolvable" in warning_text, (
            f"Expected WARNING about ahdl_include, got: {caplog.text}"
        )


def test_ahdl_include_va_module_can_be_instantiated():
    """REGRESSION TEST for v1.2 load-order fix.

    Tests that instances referencing ahdl_include'd Verilog-A modules are
    correctly registered. This test would FAIL before the load-order fix
    (when _load_ahdl_include_modules was called AFTER the second pass)
    because the instance would be dropped when cell_type lookup fails.

    Verifies that:
    1. VA module from ahdl_include is recognized and loaded
    2. Instance referencing the VA module is correctly registered
    3. Instance appears in instances_by_celltype
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create Verilog-A leaf
        leaf_path = os.path.join(tmpdir, "leaf.va")
        with open(leaf_path, "w") as f:
            f.write("module va_leaf (electrical inp, electrical outp);\n")
            f.write("  analog begin\n")
            f.write("    V(outp, inp) <+ 0.0;\n")
            f.write("  end\n")
            f.write("endmodule\n")

        # Create Spectre netlist that ahdl_include's the VA file AND instantiates it
        deck_path = os.path.join(tmpdir, "tb.scs")
        with open(deck_path, "w") as f:
            f.write("simulator lang=spectre\n")
            f.write('ahdl_include "leaf.va"\n')
            f.write("subckt parent_cell (a b)\n")
            f.write("  inst_1 (a b) va_leaf\n")
            f.write("ends parent_cell\n")

        # Parse the deck
        parser = NetlistParser(deck_path)

        # Verify va_leaf was loaded via ahdl_include
        assert "va_leaf" in parser.subckts, (
            "va_leaf should be loaded from ahdl_include and present in subckts"
        )
        assert parser.subckts["va_leaf"].pins == ["inp", "outp"], (
            f"va_leaf pins should be ['inp', 'outp'], got {parser.subckts['va_leaf'].pins}"
        )

        # Verify parent_cell was parsed
        assert "parent_cell" in parser.subckts, "parent_cell should be defined"

        # Verify the instance referencing va_leaf was registered
        assert "va_leaf" in parser.instances_by_celltype, (
            "va_leaf instances should be registered in instances_by_celltype"
        )
        insts = parser.instances_by_celltype["va_leaf"]
        assert len(insts) >= 1, (
            f"va_leaf should have at least 1 instance, but got {len(insts)}. "
            f"This indicates the load-order bug is present: instances of VA cells are dropped."
        )

        # Verify instance details
        inst = insts[0]
        assert inst.name == "inst_1", f"Instance name should be inst_1, got {inst.name}"
        assert inst.parent_cell == "parent_cell", (
            f"Instance parent should be parent_cell, got {inst.parent_cell}"
        )
        assert inst.nets == ["a", "b"], f"Instance nets should be ['a', 'b'], got {inst.nets}"
