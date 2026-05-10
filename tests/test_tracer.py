"""Unit tests for the bidirectional tracer (PHASE 10)."""

from netlist_tracer import BidirectionalTracer, NetlistParser, format_path


def test_tracer_basic_instantiation(synthetic_concat_alias_v):
    """Test that tracer can be instantiated from a parser."""
    parser = NetlistParser(synthetic_concat_alias_v)
    tracer = BidirectionalTracer(parser)
    assert tracer is not None, "Tracer should instantiate successfully"
    assert hasattr(tracer, "trace"), "Tracer should have trace method"


def test_tracer_trace_method_returns_list(synthetic_concat_alias_v):
    """Test that trace() method returns a list."""
    parser = NetlistParser(synthetic_concat_alias_v)
    tracer = BidirectionalTracer(parser)
    # concat_alias has 'a', 'b', 'y' pins
    paths = tracer.trace("concat_alias", "y")
    assert isinstance(paths, list), "trace() should return a list"


def test_tracer_format_path(synthetic_concat_alias_v):
    """Test that format_path() works on traced paths."""
    parser = NetlistParser(synthetic_concat_alias_v)
    tracer = BidirectionalTracer(parser)
    paths = tracer.trace("concat_alias", "y")
    if paths:
        for path in paths:
            formatted = format_path(path)
            assert isinstance(formatted, str), "format_path should return a string"
            assert len(formatted) > 0, "formatted path should not be empty"


def test_tracer_on_spice(synthetic_spice_basic_sp):
    """Test tracer on SPICE netlist."""
    parser = NetlistParser(synthetic_spice_basic_sp)
    tracer = BidirectionalTracer(parser)
    # Get first subckt name
    if parser.subckts:
        first_cell = list(parser.subckts.keys())[0]
        first_pins = parser.subckts[first_cell].pins
        if first_pins:
            paths = tracer.trace(first_cell, first_pins[0])
            assert isinstance(paths, list), "trace() should return list on SPICE"


def test_tracer_max_depth(synthetic_concat_alias_v):
    """Test tracer with max_depth parameter."""
    parser = NetlistParser(synthetic_concat_alias_v)
    tracer = BidirectionalTracer(parser)
    paths_unlimited = tracer.trace("concat_alias", "y")
    paths_depth0 = tracer.trace("concat_alias", "y", max_depth=0)
    assert isinstance(paths_unlimited, list), "Should handle unlimited depth"
    assert isinstance(paths_depth0, list), "Should handle max_depth=0"
    # max_depth=0 should return only the starting point
    for path in paths_depth0:
        assert len(path) <= 1, "Path depth=0 should have at most one step (start)"


def test_trace_pins_single_bit(synthetic_concat_alias_v):
    """Test trace_pins with explicit single bit."""
    parser = NetlistParser(synthetic_concat_alias_v)
    tracer = BidirectionalTracer(parser)
    # concat_alias has pins 'a', 'b', 'y'
    result = tracer.trace_pins("concat_alias", pins=["y"])
    assert isinstance(result, dict), "trace_pins should return a dict"
    assert "y" in result, "Result dict should have 'y' key"
    assert isinstance(result["y"], list), "Pin value should be a list of paths"


def test_trace_pins_omit_all(synthetic_concat_alias_v):
    """Test trace_pins with pins=None traces all bit-level pins."""
    parser = NetlistParser(synthetic_concat_alias_v)
    tracer = BidirectionalTracer(parser)
    result = tracer.trace_pins("concat_alias", pins=None)
    assert isinstance(result, dict), "trace_pins should return a dict"
    # Result keys should match all pin_to_pos keys for concat_alias
    subckt = parser.subckts.get("concat_alias")
    assert subckt is not None, "concat_alias should exist"
    expected_pins = set(subckt.pin_to_pos.keys())
    actual_pins = set(result.keys())
    assert actual_pins == expected_pins, (
        f"Omit-mode should trace all pins. Expected {expected_pins}, got {actual_pins}"
    )


def test_trace_pins_bare_busname_expands(vendored_picorv32_v):
    """Bare bus base name expands to all bit-level members as separate entries.

    Equivalent to passing `-pin mem_addr[0],mem_addr[1],...,mem_addr[31]`.
    Each bit gets its own key in the result dict (NOT grouped).
    """
    parser = NetlistParser(vendored_picorv32_v)
    tracer = BidirectionalTracer(parser)
    result = tracer.trace_pins("picorv32", pins=["mem_addr"])
    expected_keys = {f"mem_addr[{i}]" for i in range(32)}
    assert set(result.keys()) == expected_keys, (
        f"Bare bus name must expand to 32 indexed members; got {sorted(result.keys())}"
    )
    for key, paths in result.items():
        assert isinstance(paths, list), f"{key} must map to a list"


def test_trace_pins_mixed(synthetic_concat_alias_v):
    """Test trace_pins with a mix of valid and invalid pins."""
    parser = NetlistParser(synthetic_concat_alias_v)
    tracer = BidirectionalTracer(parser)
    result = tracer.trace_pins("concat_alias", pins=["y", "nonexistent"])
    assert "y" in result, "Valid pin 'y' should be in result"
    assert "nonexistent" in result, "Invalid pin should still be in result dict"
    assert isinstance(result["y"], list), "Valid pin should map to list of paths"
    assert result["nonexistent"] == [], "Invalid pin should map to empty list"


def test_trace_pins_unknown_pin(synthetic_concat_alias_v):
    """Test trace_pins with completely unknown pin name."""
    parser = NetlistParser(synthetic_concat_alias_v)
    tracer = BidirectionalTracer(parser)
    result = tracer.trace_pins("concat_alias", pins=["total_garbage_pin_name"])
    assert isinstance(result, dict), "Should return dict even with unknown pin"
    assert "total_garbage_pin_name" in result, "Unknown pin key should be in result"
    assert result["total_garbage_pin_name"] == [], "Unknown pin should map to empty list"


def test_tracer_flat_deck_up_walk_reveals_siblings(synthetic_spice_flat_deck_sp):
    """Test that tracer UP-walk from a flat-deck child reveals sibling cells.

    This verifies that tracing a pin through mac6_top at the deck level
    can surface paths that include ldo_aux (a sibling instance).
    """
    parser = NetlistParser(synthetic_spice_flat_deck_sp)
    tracer = BidirectionalTracer(parser)

    # Trace mac6_top pin 'd' (connected to vdd net at the deck level)
    # This should find a path that goes UP to the synthetic top,
    # then DOWN into ldo_aux (which also connects to vdd).
    paths = tracer.trace("mac6_top", "d")

    # Check that at least one path includes a TraceStep with ldo_aux
    found_sibling = False
    for path in paths:
        for step in path:
            if hasattr(step, "cell") and step.cell == "ldo_aux":
                found_sibling = True
                break
        if found_sibling:
            break

    assert found_sibling, (
        f"Expected tracer to find sibling cell 'ldo_aux', but it did not. "
        f"Paths: {[format_path(p) for p in paths]}"
    )
