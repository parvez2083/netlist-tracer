"""Regression tests for sky130 SPICE cell."""

import json
import os

import pytest

from netlist_tracer import BidirectionalTracer, NetlistParser, format_path


def _parser_snapshot(parser):
    """Build parser snapshot in same schema as _capture_baseline.parser_snapshot()."""
    subckts_view = {}
    for name in sorted(parser.subckts.keys()):
        sub = parser.subckts[name]
        subckts_view[name] = {
            "pins": list(sub.pins),  # preserve order (positional)
            "pin_count": len(sub.pins),
            "alias_count": len(sub.aliases),
            "child_instance_count": len(parser.instances_by_parent.get(name, [])),
        }
    total_instances = sum(len(v) for v in parser.instances_by_parent.values())
    return {
        "format": parser.format,
        "subckt_count": len(parser.subckts),
        "total_instance_count": total_instances,
        "subckt_names_sorted": sorted(parser.subckts.keys()),
        "subckts": subckts_view,
    }


def _trace_snapshot(tracer, start_cell, start_pin, max_depth=None):
    """Build trace snapshot in same schema as _capture_baseline.trace_snapshot()."""
    paths = tracer.trace(start_cell, start_pin, max_depth=max_depth)
    seen = set()
    unique_formatted = []
    for path in paths:
        sig = format_path(path)
        if sig in seen:
            continue
        seen.add(sig)
        unique_formatted.append(sig)
    return {
        "start_cell": start_cell,
        "start_pin": start_pin,
        "max_depth": max_depth,
        "raw_path_count": len(paths),
        "unique_path_count": len(unique_formatted),
        "paths": unique_formatted,
    }


@pytest.mark.slow
def test_sky130_parsing_regression():
    """Parse sky130 SPICE cell and verify parser snapshot matches baseline.

    This is the AC9 behavior preservation gate for SPICE format.
    """
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sky130_path = os.path.join(repo_root, "tests/fixtures/vendored/sky130_fd_sc_hd__inv_1.spice")
    baseline_path = os.path.join(
        repo_root, "tests/fixtures/golden/sky130_fd_sc_hd__inv_1_baseline.json"
    )

    assert os.path.exists(sky130_path), f"Fixture not found: {sky130_path}"
    assert os.path.exists(baseline_path), f"Baseline not found: {baseline_path}"

    # Parse with new implementation
    parser = NetlistParser(sky130_path)

    # Build parser snapshot using same schema as baseline
    parser_output = _parser_snapshot(parser)

    # Load baseline and extract only the parser sub-dict
    with open(baseline_path) as f:
        baseline = json.load(f)
    baseline_parser = baseline["parser"]

    # Verify parser output matches baseline parser sub-dict
    parser_json = json.dumps(parser_output, indent=2, sort_keys=True)
    baseline_json = json.dumps(baseline_parser, indent=2, sort_keys=True)

    assert parser_json == baseline_json, "Parser output does not match baseline"


@pytest.mark.slow
def test_sky130_tracing_regression():
    """Trace a signal path in sky130 and verify trace snapshot matches baseline.

    This test verifies that the tracer output matches the baseline capture for SPICE format.
    """
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sky130_path = os.path.join(repo_root, "tests/fixtures/vendored/sky130_fd_sc_hd__inv_1.spice")
    baseline_path = os.path.join(
        repo_root, "tests/fixtures/golden/sky130_fd_sc_hd__inv_1_baseline.json"
    )

    assert os.path.exists(baseline_path), f"Baseline not found: {baseline_path}"

    parser = NetlistParser(sky130_path)
    tracer = BidirectionalTracer(parser)

    # Build trace snapshot using same schema as baseline
    trace_output = _trace_snapshot(tracer, start_cell="sky130_fd_sc_hd__inv_1", start_pin="A")

    # Load baseline and extract only the trace sub-dict
    with open(baseline_path) as f:
        baseline = json.load(f)
    baseline_trace = baseline["trace"]

    # Verify trace output matches baseline trace sub-dict
    trace_json = json.dumps(trace_output, indent=2, sort_keys=True)
    baseline_json = json.dumps(baseline_trace, indent=2, sort_keys=True)

    assert trace_json == baseline_json, "Trace output does not match baseline"
