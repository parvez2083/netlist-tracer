"""Local smoke tests for real-world netlist caches.

Gated by NETLIST_TRACER_LOCAL_CACHE environment variable pointing to a JSON cache file.
Skips if env var unset or file does not exist.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from netlist_tracer import BidirectionalTracer, NetlistParser

_LOCAL_CACHE = os.environ.get("NETLIST_TRACER_LOCAL_CACHE")

pytestmark = [
    pytest.mark.local,
    pytest.mark.skipif(
        not _LOCAL_CACHE or not Path(_LOCAL_CACHE).exists(),
        reason="NETLIST_TRACER_LOCAL_CACHE not set or file does not exist",
    ),
]


def test_local_cache_loads() -> None:
    """Local JSON cache loads without error and yields non-trivial state."""
    parser = NetlistParser(_LOCAL_CACHE)
    assert parser.format in {"verilog", "spice", "cdl", "spectre"}
    assert len(parser.subckts) > 0, "cache should contain at least one subckt"
    total_instances = sum(len(v) for v in parser.instances_by_parent.values())
    assert total_instances > 0, "cache should contain at least one instance"


def test_local_cache_has_pins() -> None:
    """First subckt in cache should have at least one pin."""
    parser = NetlistParser(_LOCAL_CACHE)
    first_cell = next(iter(parser.subckts.keys()))
    pins = parser.subckts[first_cell].pins
    assert len(pins) > 0, f"first subckt {first_cell!r} should have at least one pin"


def test_local_cache_deterministic_trace() -> None:
    """Trace from first subckt's first pin completes without raising."""
    parser = NetlistParser(_LOCAL_CACHE)
    tracer = BidirectionalTracer(parser)
    # Pick deterministic trace start
    first_cell = next(iter(parser.subckts.keys()))
    pins = parser.subckts[first_cell].pins
    if not pins:
        pytest.skip(f"first subckt {first_cell!r} has no pins")
    first_pin = pins[0]
    paths = tracer.trace(first_cell, first_pin)
    assert isinstance(paths, list), "trace() must return a list"


def test_local_cache_schema_version() -> None:
    """Cache loads successfully (v0 or v1 schema both supported)."""
    parser = NetlistParser(_LOCAL_CACHE)
    # If load succeeded without exception, schema version is compatible
    assert len(parser.subckts) > 0, "parser loaded cache successfully"
