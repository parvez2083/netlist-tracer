"""Unit tests for Spectre parser (PHASE 10)."""

from netlist_tracer import NetlistParser


def test_spectre_basic_parse(synthetic_spectre_basic_scs):
    """Test parsing basic Spectre netlist."""
    parser = NetlistParser(synthetic_spectre_basic_scs)
    assert parser.format == "spectre"
    assert len(parser.subckts) > 0, "Spectre parser should find subcircuits"


def test_spectre_basic_instances(synthetic_spectre_basic_scs):
    """Test that Spectre parser finds instances."""
    parser = NetlistParser(synthetic_spectre_basic_scs)
    total_instances = sum(len(v) for v in parser.instances_by_parent.values())
    assert total_instances > 0, "Spectre netlist should have instances"


def test_spectre_basic_pins(synthetic_spectre_basic_scs):
    """Test that Spectre parser extracts pins."""
    parser = NetlistParser(synthetic_spectre_basic_scs)
    for sub in parser.subckts.values():
        assert hasattr(sub, "pins"), "Subckt should have pins attribute"
        assert isinstance(sub.pins, list), "Pins should be a list"


def test_spectre_validation(synthetic_spectre_basic_scs):
    """Test Spectre parser connection validation."""
    parser = NetlistParser(synthetic_spectre_basic_scs)
    mismatches = parser.validate_connections(verbose=False)
    assert isinstance(mismatches, list), "validate_connections should return a list"
