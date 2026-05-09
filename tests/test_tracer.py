"""Unit tests for the bidirectional tracer (PHASE 10)."""

from nettrace import BidirectionalTracer, NetlistParser, format_path


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
