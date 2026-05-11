#!/usr/bin/env python3
################################################################################
# AI GENERATED CODE - Review and test before production use
# Author: AI Generated | Date: 2026-05-10
#
# Description: Unit tests for SPICE parsing helpers: inline comments,
# continuations, controlled sources (B/E/F/G/H), coupled inductors (K),
# global directives, numerical parsing, and edge cases.
#
# Usage: pytest tests/test_spice_quickwins.py
#
# Changelog:
#   2026-05-10 - Initial test suite for SPICE parsing helpers
################################################################################

from netlist_tracer import NetlistParser

################################################################################
# SECTION: Inline Comment Tests
# Description: Verify semicolon and dollar-sign inline comment stripping.
################################################################################


def test_spice_inline_comments_semicolon(synthetic_spice_inline_comments_sp):
    """Test inline semicolon comment stripping."""
    parser = NetlistParser(synthetic_spice_inline_comments_sp)
    # Verify X1 instance is parsed (line has ; comment at end)
    insts = parser.instances_by_parent.get("test_inline", [])
    assert len(insts) >= 1, f"Expected at least 1 instance, got {len(insts)}"
    # Check first instance nets (should be stripped of comment)
    assert insts[0].nets == ["A", "B", "C"], f"Got nets {insts[0].nets}"


def test_spice_inline_comments_dollar(synthetic_spice_inline_comments_sp):
    """Test inline dollar-sign comment stripping."""
    parser = NetlistParser(synthetic_spice_inline_comments_sp)
    insts = parser.instances_by_parent.get("test_inline", [])
    # X2 has $ comment; verify it's parsed correctly
    x2_insts = [inst for inst in insts if inst.name == "X2"]
    assert len(x2_insts) == 1, "Expected X2 instance"
    assert x2_insts[0].nets == ["D", "E", "F"], f"Got nets {x2_insts[0].nets}"


################################################################################
# SECTION: Continuation Line Tests
# Description: Verify continuation line merging across comment lines.
################################################################################


def test_spice_continuation_across_comment(synthetic_spice_continuation_across_comment_sp):
    """Test continuation lines are merged properly across comment lines."""
    parser = NetlistParser(synthetic_spice_continuation_across_comment_sp)
    insts = parser.instances_by_parent.get("test_cont", [])
    assert len(insts) == 1, f"Expected 1 instance, got {len(insts)}"
    # X1 should have all nets from continuation lines merged (A B C D E)
    assert insts[0].cell_type == "test_cell", f"Got cell_type {insts[0].cell_type}"
    assert len(insts[0].nets) == 5, (
        f"Expected 5 nets from merged continuations, got {len(insts[0].nets)}"
    )
    assert insts[0].nets == ["A", "B", "C", "D", "E"], f"Got nets {insts[0].nets}"


################################################################################
# SECTION: Controlled Source Tests
# Description: Verify B/E/F/G/H element recognition and proper netlist capture.
################################################################################


def test_spice_b_element_behavioral_source(synthetic_spice_controlled_sources_sp):
    """Test B (behavioral source) element parsing."""
    parser = NetlistParser(synthetic_spice_controlled_sources_sp)
    # Look for B1 element
    b_insts = parser.instances_by_celltype.get("B_BSRC", [])
    assert len(b_insts) >= 1, f"Expected B_BSRC instance, got {len(b_insts)}"
    b1 = [inst for inst in b_insts if inst.name == "B1"]
    assert len(b1) == 1, "Expected B1 instance"
    assert b1[0].nets == ["OUT", "VSS"], f"Got nets {b1[0].nets}"


def test_spice_e_element_vcvs(synthetic_spice_controlled_sources_sp):
    """Test E (voltage-controlled voltage source) element parsing."""
    parser = NetlistParser(synthetic_spice_controlled_sources_sp)
    e_insts = parser.instances_by_celltype.get("E_VCVS", [])
    assert len(e_insts) >= 1, f"Expected E_VCVS instance, got {len(e_insts)}"
    e1 = [inst for inst in e_insts if inst.name == "E1"]
    assert len(e1) == 1, "Expected E1 instance"
    # E1 has 4 nets: N1, VSS (output), IN, VSS (input)
    assert len(e1[0].nets) == 4, f"Expected 4 nets, got {len(e1[0].nets)}"


def test_spice_g_element_vccs(synthetic_spice_controlled_sources_sp):
    """Test G (voltage-controlled current source) element parsing."""
    parser = NetlistParser(synthetic_spice_controlled_sources_sp)
    g_insts = parser.instances_by_celltype.get("G_VCCS", [])
    assert len(g_insts) >= 1, f"Expected G_VCCS instance, got {len(g_insts)}"
    g1 = [inst for inst in g_insts if inst.name == "G1"]
    assert len(g1) == 1, "Expected G1 instance"
    assert len(g1[0].nets) == 4, f"Expected 4 nets, got {len(g1[0].nets)}"


def test_spice_f_element_cccs(synthetic_spice_controlled_sources_sp):
    """Test F (current-controlled current source) element parsing."""
    parser = NetlistParser(synthetic_spice_controlled_sources_sp)
    f_insts = parser.instances_by_celltype.get("F_CCCS", [])
    assert len(f_insts) >= 1, f"Expected F_CCCS instance, got {len(f_insts)}"
    f1 = [inst for inst in f_insts if inst.name == "F1"]
    assert len(f1) == 1, "Expected F1 instance"
    assert f1[0].nets == ["N3", "VSS"], f"Got nets {f1[0].nets}"
    assert "_vctrl" in f1[0].params, "Expected _vctrl in params"


def test_spice_h_element_ccvs(synthetic_spice_controlled_sources_sp):
    """Test H (current-controlled voltage source) element parsing."""
    parser = NetlistParser(synthetic_spice_controlled_sources_sp)
    h_insts = parser.instances_by_celltype.get("H_CCVS", [])
    assert len(h_insts) >= 1, f"Expected H_CCVS instance, got {len(h_insts)}"
    h1 = [inst for inst in h_insts if inst.name == "H1"]
    assert len(h1) == 1, "Expected H1 instance"
    assert h1[0].nets == ["N4", "VSS"], f"Got nets {h1[0].nets}"
    assert "_vctrl" in h1[0].params, "Expected _vctrl in params"


################################################################################
# SECTION: Coupled Inductor Tests
# Description: Verify K element (coupled inductor) recognition.
################################################################################


def test_spice_k_element_coupled_inductor(synthetic_spice_coupled_inductor_sp):
    """Test K (coupled inductor) element parsing."""
    parser = NetlistParser(synthetic_spice_coupled_inductor_sp)
    k_insts = parser.instances_by_celltype.get("K_COUPLED", [])
    assert len(k_insts) >= 1, f"Expected K_COUPLED instance, got {len(k_insts)}"
    k1 = [inst for inst in k_insts if inst.name == "K1"]
    assert len(k1) == 1, "Expected K1 instance"
    # nets should hold inductor names, not nodes
    assert k1[0].nets == ["L1", "L2"], f"Got nets {k1[0].nets}"
    assert "_k_coeff" in k1[0].params, "Expected _k_coeff in params"


################################################################################
# SECTION: Global Directive Tests
# Description: Verify .global directive capture into parser.global_nets.
################################################################################


def test_spice_global_directive_captured(synthetic_spice_global_directive_sp):
    """Test .global directive is captured into parser.global_nets."""
    parser = NetlistParser(synthetic_spice_global_directive_sp)
    assert hasattr(parser, "global_nets"), "Parser should have global_nets attribute"
    assert len(parser.global_nets) == 3, f"Expected 3 global nets, got {len(parser.global_nets)}"
    assert "VDD" in parser.global_nets, "VDD should be in global_nets"
    assert "VSS" in parser.global_nets, "VSS should be in global_nets"
    assert "GND" in parser.global_nets, "GND should be in global_nets"


################################################################################
# SECTION: Numerical Parsing Tests
# Description: Verify parse_numerical handles MEG/M distinction, all suffixes,
# case insensitivity, scientific notation, and edge cases.
################################################################################


def test_parse_numerical_meg_vs_m():
    """Test MEG (mega, 1e6) vs M (milli, 1e-3) distinction."""
    from netlist_tracer.parsers._numerics import parse_numerical

    assert parse_numerical("1MEG") == 1e6, "1MEG should be 1,000,000"
    assert parse_numerical("1M") == 1e-3, "1M should be 0.001"
    assert parse_numerical("1meg") == 1e6, "1meg (lowercase) should be 1,000,000"
    assert parse_numerical("1m") == 1e-3, "1m (lowercase) should be 0.001"


def test_parse_numerical_all_suffixes():
    """Test all SPICE/HSPICE unit suffixes."""
    from netlist_tracer.parsers._numerics import parse_numerical

    assert parse_numerical("1T") == 1e12, "T (tera)"
    assert parse_numerical("1G") == 1e9, "G (giga)"
    assert parse_numerical("1K") == 1e3, "K (kilo)"
    assert parse_numerical("1U") == 1e-6, "U (micro)"
    assert parse_numerical("1N") == 1e-9, "N (nano)"
    assert parse_numerical("1P") == 1e-12, "P (pico)"
    assert parse_numerical("1F") == 1e-15, "F (femto)"
    assert parse_numerical("1A") == 1e-18, "A (atto)"


def test_parse_numerical_unicode_mu():
    """Test Unicode micro symbol (μ)."""
    from netlist_tracer.parsers._numerics import parse_numerical

    assert parse_numerical("1μ") == 1e-6, "Unicode μ should be micro"


def test_parse_numerical_case_insensitivity():
    """Test case insensitivity for all suffixes."""
    from netlist_tracer.parsers._numerics import parse_numerical

    assert parse_numerical("1K") == parse_numerical("1k"), "K/k equivalence"
    assert parse_numerical("1T") == parse_numerical("1t"), "T/t equivalence"
    assert parse_numerical("1MEG") == parse_numerical("1Meg"), "MEG/Meg equivalence"


def test_parse_numerical_scientific_notation():
    """Test plain scientific notation (no suffix)."""
    from netlist_tracer.parsers._numerics import parse_numerical

    assert parse_numerical("1.5e-9") == 1.5e-9, "Scientific notation 1.5e-9"
    assert parse_numerical("2.0e6") == 2.0e6, "Scientific notation 2.0e6"
    assert parse_numerical("1e12") == 1e12, "Scientific notation 1e12"


def test_parse_numerical_plain_floats():
    """Test plain floating point numbers."""
    from netlist_tracer.parsers._numerics import parse_numerical

    assert parse_numerical("3.14") == 3.14, "Plain float 3.14"
    assert parse_numerical("0.001") == 0.001, "Plain float 0.001"
    assert parse_numerical("1000") == 1000.0, "Plain integer 1000"


def test_parse_numerical_none_on_garbage():
    """Test None return on garbage input."""
    from netlist_tracer.parsers._numerics import parse_numerical

    assert parse_numerical("abc") is None, "Garbage 'abc' should return None"
    assert parse_numerical("12X34") is None, "Invalid '12X34' should return None"
    assert parse_numerical("M2") is None, "Invalid 'M2' should return None"


def test_parse_numerical_none_on_empty_string():
    """Test None return on empty string."""
    from netlist_tracer.parsers._numerics import parse_numerical

    assert parse_numerical("") is None, "Empty string should return None"
    assert parse_numerical("   ") is None, "Whitespace-only should return None"


def test_parse_numerical_none_on_non_string():
    """Test None return on non-string input."""
    from netlist_tracer.parsers._numerics import parse_numerical

    assert parse_numerical(None) is None, "None input should return None"
    assert parse_numerical(123) is None, "Integer input should return None"
    assert parse_numerical(1.5) is None, "Float input should return None"


################################################################################
# SECTION: Edge Case Tests
# Description: Verify robustness with CRLF, UTF-8 BOM, long lines, tabs,
# and mixed case.
################################################################################


def test_spice_edge_case_crlf(synthetic_spice_edge_crlf_sp):
    """Test CRLF line endings parse without error."""
    parser = NetlistParser(synthetic_spice_edge_crlf_sp)
    assert parser.format == "spice", f"Format should be spice, got {parser.format}"
    assert "test_crlf" in parser.subckts, "test_crlf should be in subckts"


def test_spice_edge_case_utf8_bom(synthetic_spice_edge_utf8_bom_sp):
    """Test UTF-8 BOM handling."""
    parser = NetlistParser(synthetic_spice_edge_utf8_bom_sp)
    assert parser.format == "spice", f"Format should be spice, got {parser.format}"
    assert "test_bom" in parser.subckts, "test_bom should be in subckts"


def test_spice_edge_case_long_line(synthetic_spice_edge_long_line_sp):
    """Test very long netlist line."""
    parser = NetlistParser(synthetic_spice_edge_long_line_sp)
    insts = parser.instances_by_parent.get("test_long_line", [])
    assert len(insts) >= 1, f"Expected at least 1 instance, got {len(insts)}"


def test_spice_edge_case_tab_continuation(synthetic_spice_edge_tab_continuation_sp):
    """Test tab characters in continuation lines."""
    parser = NetlistParser(synthetic_spice_edge_tab_continuation_sp)
    insts = parser.instances_by_parent.get("test_tab_cont", [])
    assert len(insts) >= 1, f"Expected at least 1 instance, got {len(insts)}"


def test_spice_edge_case_mixed_case(synthetic_spice_edge_mixed_case_sp):
    """Test mixed case keywords and identifiers."""
    parser = NetlistParser(synthetic_spice_edge_mixed_case_sp)
    assert "MixedCase_Cell" in parser.subckts, "MixedCase_Cell should be in subckts"
    assert "Sub_Component" in parser.subckts, "Sub_Component should be in subckts"
    assert "Another_Comp" in parser.subckts, "Another_Comp should be in subckts"
