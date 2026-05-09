"""Unit tests for format detection (PHASE 10)."""

from netlist_tracer.parsers.detect import detect_format


def test_detect_format_verilog(synthetic_concat_alias_v):
    """Test detection of Verilog format."""
    fmt = detect_format([synthetic_concat_alias_v])
    assert fmt == "verilog", f"Expected verilog, got {fmt}"


def test_detect_format_spice(synthetic_spice_basic_sp):
    """Test detection of SPICE format."""
    fmt = detect_format([synthetic_spice_basic_sp])
    assert fmt == "spice", f"Expected spice, got {fmt}"


def test_detect_format_cdl(synthetic_cdl_basic_cdl):
    """Test detection of CDL format."""
    fmt = detect_format([synthetic_cdl_basic_cdl])
    assert fmt == "cdl", f"Expected cdl, got {fmt}"


def test_detect_format_spectre(synthetic_spectre_basic_scs):
    """Test detection of Spectre format."""
    fmt = detect_format([synthetic_spectre_basic_scs])
    assert fmt == "spectre", f"Expected spectre, got {fmt}"
