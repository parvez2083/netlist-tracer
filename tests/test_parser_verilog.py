"""Unit tests for Verilog parser (PHASE 10)."""

from netlist_tracer import NetlistParser


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


def test_verilog_nested_generate_loop(synthetic_nested_generate_v):
    """Test parsing Verilog with nested 2-level generate-for loops (fixed-point unrolling).

    This fixture exercises the fixed-point unrolling capability: both outer and inner
    loop variables should be fully substituted with concrete indices in the aliases dict.
    Pins are expanded to individual bits by the Verilog parser (standard behavior).
    """
    parser = NetlistParser(synthetic_nested_generate_v)
    assert parser.format == "verilog"
    assert len(parser.subckts) > 0, "Nested generate fixture should parse"
    assert "nested_generate" in parser.subckts, "Should find nested_generate module"

    subckt = parser.subckts["nested_generate"]
    # Pins are expanded to individual bits: in0[0..3], in1[0..3], out0[0..3], out1[0..3] = 16 total
    assert len(subckt.pins) == 16, (
        f"nested_generate pins should be expanded to 16 individual bits, got {len(subckt.pins)}"
    )

    # Strong assertions: nested loop variable expansion produces concrete indices
    assert isinstance(subckt.aliases, dict), "Aliases should be extractable"

    # Expected aliases from nested loops:
    # Outer loop i in [0, 1], inner loop j in [0, 1]:
    #   out0[i] = in0[i] is assigned (2 * 2) = 4 times, but deduped to 2 unique pairs
    #   out1[j] = in1[j] is assigned (2 * 2) = 4 times, but deduped to 2 unique pairs
    # Total: exactly 4 unique pairs (out0[0]->in0[0], out0[1]->in0[1], out1[0]->in1[0], out1[1]->in1[1])
    assert len(subckt.aliases) == 4, (
        f"nested_generate should have exactly 4 alias pairs from 2x2 nested loops, got {len(subckt.aliases)}"
    )

    # Verify all alias keys/values are concrete bit indices (not loop variables)
    import re

    for key, val in subckt.aliases.items():
        assert key.count("[") == 1 and key.count("]") == 1, (
            f"Alias key {key!r} should be concrete bit form (e.g. out0[0]), not loop-variable form"
        )
        assert val.count("[") == 1 and val.count("]") == 1, (
            f"Alias value {val!r} should be concrete bit form (e.g. in0[0]), not loop-variable form"
        )
        # Verify no bare loop-variable names remain (word boundary check)
        assert not re.search(r"\b[ij]\b", key), (
            f"Alias key {key!r} should not contain loop variables (i, j)"
        )
        assert not re.search(r"\b[ij]\b", val), (
            f"Alias value {val!r} should not contain loop variables (i, j)"
        )

    # Verify specific aliases are present
    expected_pairs = {
        "out0[0]": "in0[0]",
        "out0[1]": "in0[1]",
        "out1[0]": "in1[0]",
        "out1[1]": "in1[1]",
    }
    for exp_key, exp_val in expected_pairs.items():
        assert exp_key in subckt.aliases, (
            f"Expected alias {exp_key!r} not found in {list(subckt.aliases.keys())}"
        )
        assert subckt.aliases[exp_key] == exp_val, (
            f"Expected {exp_key!r} -> {exp_val!r}, got {subckt.aliases[exp_key]!r}"
        )
