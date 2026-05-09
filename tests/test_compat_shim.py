"""Tests for backward-compatibility shims."""

import warnings


def test_netlist_parser_shim():
    """Test that netlist_parser shim works and imports are identical."""
    # Import from shim
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        from netlist_parser import Instance, NetlistParser, SubcktDef, merge_aliases_into_subckt

        # Verify DeprecationWarning was issued
        assert len(w) == 1
        assert issubclass(w[0].category, DeprecationWarning)
        assert "deprecated" in str(w[0].message).lower()

    # Import from nettrace directly
    from nettrace import (
        Instance as NInstance,
    )
    from nettrace import (
        NetlistParser as NNetlistParser,
    )
    from nettrace import (
        SubcktDef as NSubcktDef,
    )
    from nettrace import (
        merge_aliases_into_subckt as Nmerge_aliases_into_subckt,
    )

    # Verify they are the same objects (identity check)
    assert NetlistParser is NNetlistParser, "NetlistParser should be the same object"
    assert SubcktDef is NSubcktDef, "SubcktDef should be the same object"
    assert Instance is NInstance, "Instance should be the same object"
    assert merge_aliases_into_subckt is Nmerge_aliases_into_subckt, (
        "merge_aliases_into_subckt should be the same object"
    )


def test_netlist_tracer_shim():
    """Test that netlist_tracer shim works and imports are identical."""
    # Import from shim
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        from netlist_tracer import BidirectionalTracer, TraceStep, format_path

        # Verify DeprecationWarning was issued
        assert len(w) == 1
        assert issubclass(w[0].category, DeprecationWarning)
        assert "deprecated" in str(w[0].message).lower()

    # Import from nettrace directly
    from nettrace import (
        BidirectionalTracer as NBidirectionalTracer,
    )
    from nettrace import (
        TraceStep as NTraceStep,
    )
    from nettrace import (
        format_path as Nformat_path,
    )

    # Verify they are the same objects (identity check)
    assert BidirectionalTracer is NBidirectionalTracer, (
        "BidirectionalTracer should be the same object"
    )
    assert TraceStep is NTraceStep, "TraceStep should be the same object"
    assert format_path is Nformat_path, "format_path should be the same object"
