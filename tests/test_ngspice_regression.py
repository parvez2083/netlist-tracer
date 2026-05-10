"""Regression tests for NGSpice netlist parsing."""

from __future__ import annotations

import json
import os

import pytest

from netlist_tracer import BidirectionalTracer, NetlistParser, format_path


def _parser_snapshot(parser: object) -> dict:
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


def _trace_snapshot(tracer: object, start_cell: str, start_pin: str, max_depth: int | None = None) -> dict:
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
def test_ngspice_parsing_regression() -> None:
    """Parse NGSpice hic2_ft.sp and verify parser snapshot matches baseline.

    This test verifies that the NGSpice parser correctly extracts subckts,
    instances, and aliases from simulation netlists.
    """
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ngspice_path = os.path.join(repo_root, "tests/fixtures/vendored/ngspice/hic2_ft.sp")
    baseline_path = os.path.join(repo_root, "tests/fixtures/golden/hic2_ft_baseline.json")

    assert os.path.exists(ngspice_path), f"Fixture not found: {ngspice_path}"
    assert os.path.exists(baseline_path), f"Baseline not found: {baseline_path}"

    # Parse with new implementation
    parser = NetlistParser(ngspice_path)

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
def test_ngspice_tracing_regression() -> None:
    """Trace a signal path in NGSpice hic2_ft.sp and verify trace snapshot matches baseline.

    This test verifies that the tracer can navigate hierarchical SPICE netlists.
    """
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ngspice_path = os.path.join(repo_root, "tests/fixtures/vendored/ngspice/hic2_ft.sp")
    baseline_path = os.path.join(repo_root, "tests/fixtures/golden/hic2_ft_baseline.json")

    assert os.path.exists(baseline_path), f"Baseline not found: {baseline_path}"

    parser = NetlistParser(ngspice_path)
    tracer = BidirectionalTracer(parser)

    # Load baseline to get the top-level cell and pin names
    with open(baseline_path) as f:
        baseline = json.load(f)
    baseline_data = baseline.get("trace", {})

    # Use start_cell and start_pin from baseline, or default to first available
    start_cell = baseline_data.get("start_cell")
    start_pin = baseline_data.get("start_pin")

    if not start_cell or not start_pin:
        # Fallback: use first subckt and first pin
        subckts = parser.subckts
        if not subckts:
            pytest.skip("No subckts to trace in NGSpice fixture")
        start_cell = next(iter(subckts.keys()))
        start_pin = subckts[start_cell].pins[0] if subckts[start_cell].pins else None
        if not start_pin:
            pytest.skip(f"No pins to trace in {start_cell}")

    # Build trace snapshot using same schema as baseline
    trace_output = _trace_snapshot(tracer, start_cell=start_cell, start_pin=start_pin)

    # Load baseline trace section
    baseline_trace = baseline.get("trace", {})

    # Verify trace output matches baseline trace sub-dict
    trace_json = json.dumps(trace_output, indent=2, sort_keys=True)
    baseline_json = json.dumps(baseline_trace, indent=2, sort_keys=True)

    assert trace_json == baseline_json, "Trace output does not match baseline"
