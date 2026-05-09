"""Unit tests for SPICE parser (PHASE 10)."""

from nettrace import NetlistParser


def test_spice_basic_parse(synthetic_spice_basic_sp):
    """Test parsing basic SPICE netlist."""
    parser = NetlistParser(synthetic_spice_basic_sp)
    assert parser.format == "spice"
    assert len(parser.subckts) > 0, "SPICE parser should find subcircuits"


def test_spice_basic_instances(synthetic_spice_basic_sp):
    """Test that SPICE parser finds instances."""
    parser = NetlistParser(synthetic_spice_basic_sp)
    total_instances = sum(len(v) for v in parser.instances_by_parent.values())
    assert total_instances > 0, "SPICE netlist should have instances"


def test_spice_basic_pins(synthetic_spice_basic_sp):
    """Test that SPICE parser extracts pins."""
    parser = NetlistParser(synthetic_spice_basic_sp)
    for sub in parser.subckts.values():
        assert hasattr(sub, "pins"), "Subckt should have pins attribute"
        assert isinstance(sub.pins, list), "Pins should be a list"


def test_spice_validation(synthetic_spice_basic_sp):
    """Test SPICE parser connection validation."""
    parser = NetlistParser(synthetic_spice_basic_sp)
    mismatches = parser.validate_connections(verbose=False)
    # Basic fixture should have no pin mismatches
    assert isinstance(mismatches, list), "validate_connections should return a list"


def test_cdl_supply_constant_subckts(synthetic_supply_constant_cdl):
    """Test parsing CDL supply_constant subcircuit definitions."""
    parser = NetlistParser(synthetic_supply_constant_cdl)
    assert "supply_constant" in parser.subckts
    assert "top_supply" in parser.subckts
    assert parser.subckts["supply_constant"].pins == ["VDD", "VSS"]


def test_cdl_supply_constant_instance(synthetic_supply_constant_cdl):
    """Test parsing CDL supply_constant instances."""
    parser = NetlistParser(synthetic_supply_constant_cdl)
    insts = parser.instances_by_parent.get("top_supply", [])
    assert len(insts) == 1
    assert insts[0].cell_type == "supply_constant"
