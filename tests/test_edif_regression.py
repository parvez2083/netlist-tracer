"""Regression tests for EDIF parser against golden baselines."""

from __future__ import annotations

import json
import os
from typing import Any

import pytest

from netlist_tracer import NetlistParser

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "vendored")
GOLDEN_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "golden")


def parser_snapshot(parser: NetlistParser) -> dict[str, Any]:
    """Serialize a deterministic, comparable view of parser state."""
    subckts_view: dict[str, dict[str, Any]] = {}
    for name in sorted(parser.subckts.keys()):
        sub = parser.subckts[name]
        subckts_view[name] = {
            "pins": list(sub.pins),
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


@pytest.mark.slow
class TestEDIFRegression:
    """EDIF parsing regression tests against golden baselines."""

    def test_AND_gate_parsing_regression(self) -> None:
        """Parse AND_gate.edf and match golden baseline snapshot."""
        fixture = os.path.join(FIXTURES_DIR, "AND_gate.edf")
        parser = NetlistParser(fixture)
        snapshot = parser_snapshot(parser)

        golden_file = os.path.join(GOLDEN_DIR, "AND_gate_baseline.json")
        with open(golden_file) as f:
            golden = json.load(f)

        assert snapshot == golden["parser"]

    def test_AND_gate_tracing_regression(self) -> None:
        """Trace AND_gate.edf and match golden baseline."""
        from netlist_tracer import BidirectionalTracer, format_path

        fixture = os.path.join(FIXTURES_DIR, "AND_gate.edf")
        parser = NetlistParser(fixture)
        tracer = BidirectionalTracer(parser)

        paths = tracer.trace("logic_gate", "a")
        seen = set()
        unique_formatted: list[str] = []
        for path in paths:
            sig = format_path(path)
            if sig in seen:
                continue
            seen.add(sig)
            unique_formatted.append(sig)

        golden_file = os.path.join(GOLDEN_DIR, "AND_gate_baseline.json")
        with open(golden_file) as f:
            golden = json.load(f)

        assert unique_formatted == golden["trace"]["paths"]

    def test_n_bit_counter_parsing_regression(self) -> None:
        """Parse n_bit_counter.edf and match golden baseline."""
        fixture = os.path.join(FIXTURES_DIR, "n_bit_counter.edf")
        parser = NetlistParser(fixture)
        snapshot = parser_snapshot(parser)

        golden_file = os.path.join(GOLDEN_DIR, "n_bit_counter_baseline.json")
        with open(golden_file) as f:
            golden = json.load(f)

        assert snapshot == golden["parser"]

    def test_n_bit_counter_tracing_regression(self) -> None:
        """Trace n_bit_counter.edf and match golden baseline."""
        from netlist_tracer import BidirectionalTracer, format_path

        fixture = os.path.join(FIXTURES_DIR, "n_bit_counter.edf")
        parser = NetlistParser(fixture)
        tracer = BidirectionalTracer(parser)

        paths = tracer.trace("n_bit_counter", "clk")
        seen = set()
        unique_formatted: list[str] = []
        for path in paths:
            sig = format_path(path)
            if sig in seen:
                continue
            seen.add(sig)
            unique_formatted.append(sig)

        golden_file = os.path.join(GOLDEN_DIR, "n_bit_counter_baseline.json")
        with open(golden_file) as f:
            golden = json.load(f)

        assert unique_formatted == golden["trace"]["paths"]

    def test_one_counter_parsing_regression(self) -> None:
        """Parse one_counter.edf and match golden baseline."""
        fixture = os.path.join(FIXTURES_DIR, "one_counter.edf")
        parser = NetlistParser(fixture)
        snapshot = parser_snapshot(parser)

        golden_file = os.path.join(GOLDEN_DIR, "one_counter_baseline.json")
        with open(golden_file) as f:
            golden = json.load(f)

        assert snapshot == golden["parser"]

    def test_one_counter_tracing_regression(self) -> None:
        """Trace one_counter.edf and match golden baseline."""
        from netlist_tracer import BidirectionalTracer, format_path

        fixture = os.path.join(FIXTURES_DIR, "one_counter.edf")
        parser = NetlistParser(fixture)
        tracer = BidirectionalTracer(parser)

        paths = tracer.trace("one_counter", "XP_PCLK")
        seen = set()
        unique_formatted: list[str] = []
        for path in paths:
            sig = format_path(path)
            if sig in seen:
                continue
            seen.add(sig)
            unique_formatted.append(sig)

        golden_file = os.path.join(GOLDEN_DIR, "one_counter_baseline.json")
        with open(golden_file) as f:
            golden = json.load(f)

        assert unique_formatted == golden["trace"]["paths"]
