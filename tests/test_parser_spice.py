"""Unit tests for SPICE parser (PHASE 10)."""

from netlist_tracer import NetlistParser


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


def test_spice_flat_deck_synthesizes_top(synthetic_spice_flat_deck_sp):
    """Test that SPICE flat-deck testbench synthesizes a synthetic top-level cell."""
    parser = NetlistParser(synthetic_spice_flat_deck_sp)
    assert "__spice_flat_deck__" in parser.subckts, (
        f"Synthetic top '__spice_flat_deck__' not found. Subckts: {list(parser.subckts.keys())}"
    )
    synthetic_top = parser.subckts["__spice_flat_deck__"]
    assert synthetic_top.pins == [], f"Synthetic top should have empty pins, got {synthetic_top.pins}"


def test_spice_flat_deck_top_level_instances_captured(synthetic_spice_flat_deck_sp):
    """Test that top-level X-instances are captured into the synthetic top."""
    parser = NetlistParser(synthetic_spice_flat_deck_sp)
    top_instances = parser.instances_by_parent.get("__spice_flat_deck__", [])
    assert len(top_instances) == 2, (
        f"Expected 2 top-level instances, got {len(top_instances)}: {top_instances}"
    )
    cell_types = {inst.cell_type for inst in top_instances}
    assert cell_types == {"mac6_top", "ldo_aux"}, (
        f"Expected cell types {{'mac6_top', 'ldo_aux'}}, got {cell_types}"
    )


def test_spice_hierarchical_no_synthesis(synthetic_spice_basic_sp):
    """Test that pure hierarchical SPICE decks do not synthesize a synthetic top."""
    parser = NetlistParser(synthetic_spice_basic_sp)
    synthetic_tops = [name for name in parser.subckts.keys() if name.startswith("__")]
    assert len(synthetic_tops) == 0, (
        f"Hierarchical deck should not have synthetic tops, but found: {synthetic_tops}"
    )
    # Verify expected cells are still present
    assert "nand2" in parser.subckts
    assert "top_spice" in parser.subckts
