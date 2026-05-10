"""Tests for the netlist-tracer CLI."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


def test_cli_single_pin_byte_identical() -> None:
    """Verify single-pin CLI output is byte-identical to baseline."""
    repo_root = Path(__file__).parent.parent
    netlist_path = repo_root / "tests/fixtures/vendored/picorv32.v"
    baseline_path = repo_root / "tests/fixtures/golden/cli_picorv32_clk_baseline.txt"

    # Run the CLI command
    result = subprocess.run(
        [
            "netlist-tracer",
            "-netlist",
            str(netlist_path),
            "-cell",
            "picorv32",
            "-pin",
            "clk",
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, f"CLI failed: {result.stderr}"

    # Read baseline
    with open(baseline_path) as f:
        baseline = f.read()

    # Compare byte-for-byte
    assert result.stdout == baseline, "Single-pin CLI output differs from baseline"


def test_cli_multipin_sectioned() -> None:
    """Verify multi-pin CLI output is sectioned correctly."""
    repo_root = Path(__file__).parent.parent
    netlist_path = repo_root / "tests/fixtures/vendored/picorv32.v"

    # Run the CLI with multiple pins
    result = subprocess.run(
        [
            "netlist-tracer",
            "-netlist",
            str(netlist_path),
            "-cell",
            "picorv32",
            "-pin",
            "clk",
            "-pin",
            "resetn",
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, f"CLI failed: {result.stderr}"
    output = result.stdout

    # Check for sectioning headers
    assert "== Pin: clk" in output, "Missing section header for 'clk'"
    assert "== Pin: resetn" in output, "Missing section header for 'resetn'"
    assert "Tracing: picorv32.<2 pins>" in output, "Missing multi-pin tracing header"


def test_cli_trace_format_json() -> None:
    """Verify -trace_format json produces valid JSON output."""
    repo_root = Path(__file__).parent.parent
    netlist_path = repo_root / "tests/fixtures/vendored/picorv32.v"

    # Run the CLI with JSON format
    result = subprocess.run(
        [
            "netlist-tracer",
            "-netlist",
            str(netlist_path),
            "-cell",
            "picorv32",
            "-trace_format",
            "json",
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, f"CLI failed: {result.stderr}"

    # Parse JSON output
    data = json.loads(result.stdout)

    # Verify schema keys
    assert data["tool"] == "netlist-tracer", "Tool field is incorrect"
    assert data["version"] == "0.1.0", "Version field is incorrect"
    assert data["cell"] == "picorv32", "Cell field is incorrect"
    assert data["target"] is None, "Target field should be None"
    assert isinstance(data["pins"], dict), "Pins should be a dict"

    # In omit-mode, pins dict should be non-empty (all bit-level pins)
    assert len(data["pins"]) > 0, "No pins traced in omit-mode"

    # Check structure of first pin
    first_pin = next(iter(data["pins"].values()))
    assert isinstance(first_pin["paths"], list), "Paths should be a list"
    if first_pin["paths"]:
        first_path = first_pin["paths"][0]
        assert "formatted" in first_path, "Missing 'formatted' in path"
        assert "steps" in first_path, "Missing 'steps' in path"
        if first_path["steps"]:
            first_step = first_path["steps"][0]
            assert "cell" in first_step, "Missing 'cell' in step"
            assert "pin_or_net" in first_step, "Missing 'pin_or_net' in step"
            assert "direction" in first_step, "Missing 'direction' in step"
