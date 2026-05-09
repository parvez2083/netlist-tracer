"""Unit tests for Verilog parser (PHASE 10)."""

from nettrace import NetlistParser


def test_verilog_concat_alias_parse(synthetic_concat_alias_v):
    """Test parsing Verilog with concatenation and aliases."""
    parser = NetlistParser(synthetic_concat_alias_v)
    assert parser.format == "verilog"
    assert len(parser.subckts) > 0, "Verilog parser should find modules"


def test_verilog_generate_loop_parse(synthetic_generate_loop_v):
    """Test parsing Verilog with generate loops."""
    parser = NetlistParser(synthetic_generate_loop_v)
    assert parser.format == "verilog"
    assert len(parser.subckts) > 0, "Generate loop fixture should parse"
    # Structural assertions for generate_loop module
    assert "generate_loop" in parser.subckts, "Should find generate_loop module"
    subckt = parser.subckts["generate_loop"]
    assert len(subckt.pins) == 8, (
        f"generate_loop should have 8 pins (4-bit in, 4-bit out), got {len(subckt.pins)}"
    )
    # Strong assertions: generate loop variable expansion produces concrete per-iteration aliases
    assert isinstance(subckt.aliases, dict), "Aliases should be extractable"
    assert len(subckt.aliases) == 4, (
        f"generate_loop should have 4 alias pairs (out[i]->in[i] for i=0..3), got {len(subckt.aliases)}"
    )
    expected_aliases = {
        "out[0]": "in[0]",
        "out[1]": "in[1]",
        "out[2]": "in[2]",
        "out[3]": "in[3]",
    }
    assert subckt.aliases == expected_aliases, (
        f"Aliases should match concrete per-iteration pairs, got {subckt.aliases}"
    )


def test_verilog_param_specialize_parse(synthetic_param_specialize_v):
    """Test parsing parameterized Verilog modules."""
    parser = NetlistParser(synthetic_param_specialize_v)
    assert parser.format == "verilog"
    # Should have both the parameterized module and the top module
    assert len(parser.subckts) >= 1, "Should find parameterized module instances"
    # Structural assertions for parameter specialization
    assert "param_specialize__WIDTH_16" in parser.subckts, "Should find WIDTH=16 specialized module"
    assert "top_param" in parser.instances_by_parent, "Should find top_param module instances"
    insts = parser.instances_by_parent["top_param"]
    assert len(insts) > 0, "top_param should have instances"
    assert insts[0].cell_type == "param_specialize__WIDTH_16", (
        f"Instance cell_type should be specialized, got {insts[0].cell_type}"
    )


def test_verilog_concat_aliases(synthetic_concat_alias_v):
    """Test that Verilog parser extracts aliases from assigns."""
    parser = NetlistParser(synthetic_concat_alias_v)
    for sub in parser.subckts.values():
        assert hasattr(sub, "aliases"), "Subckt should have aliases attribute"
        assert isinstance(sub.aliases, dict), "Aliases should be a dict"
    # Additional assertion: concat_alias module should have extracted aliases
    if "concat_alias" in parser.subckts:
        assert len(parser.subckts["concat_alias"].aliases) > 0, (
            "concat_alias should have at least one alias pair"
        )


def test_verilog_pins(synthetic_concat_alias_v):
    """Test that Verilog parser extracts pins correctly."""
    parser = NetlistParser(synthetic_concat_alias_v)
    for sub in parser.subckts.values():
        assert hasattr(sub, "pins"), "Subckt should have pins attribute"
        assert isinstance(sub.pins, list), "Pins should be a list"
        # concat_alias module should have a, b, y ports
        if sub.name == "concat_alias":
            assert len(sub.pins) == 3, f"concat_alias should have 3 pins, got {len(sub.pins)}"
