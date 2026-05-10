"""Tests for JSON cache schema versioning (backward compatibility with v0 caches)."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from netlist_tracer import NetlistParser
from netlist_tracer.exceptions import NetlistParseError


def test_dump_includes_schema_version() -> None:
    """Verify that dump_json() includes a current schema_version field."""
    from netlist_tracer.parser import _CACHE_SCHEMA_VERSION

    with tempfile.TemporaryDirectory() as tmpdir:
        # Parse a minimal fixture (using spice_basic.sp)
        fixture_path = Path(__file__).parent / "fixtures" / "synthetic" / "spice_basic.sp"
        if not fixture_path.exists():
            pytest.skip(f"Fixture {fixture_path} not found")
        parser = NetlistParser(str(fixture_path))

        # Dump to JSON
        out_path = Path(tmpdir) / "cache.json"
        parser.dump_json(str(out_path))

        # Load JSON and verify schema_version field matches current version
        with open(out_path) as f:
            data = json.load(f)
        assert "schema_version" in data, "schema_version field missing from dumped JSON"
        assert data["schema_version"] == _CACHE_SCHEMA_VERSION, (
            f"Expected schema_version={_CACHE_SCHEMA_VERSION}, got {data['schema_version']}"
        )


def test_load_v0_cache() -> None:
    """Verify backward compatibility: v0 cache (without schema_version field) loads cleanly."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a synthetic v0 JSON cache (no schema_version field)
        v0_cache = {
            "format": "spice",
            "source": "/tmp/test.sp",
            "subckts": {
                "nand2": ["A", "B", "Y", "VDD", "GND"],
                "inv": ["IN", "OUT", "VDD", "GND"],
            },
            "instances": [
                {
                    "name": "x_nand",
                    "cell_type": "nand2",
                    "nets": ["n1", "n2", "n3", "VDD", "GND"],
                    "parent_cell": "top",
                },
                {
                    "name": "x_inv",
                    "cell_type": "inv",
                    "nets": ["n3", "n4", "VDD", "GND"],
                    "parent_cell": "top",
                },
            ],
            "aliases": {},
        }
        cache_path = Path(tmpdir) / "v0_cache.json"
        with open(cache_path, "w") as f:
            json.dump(v0_cache, f)

        # Load the v0 cache — should succeed
        parser = NetlistParser(str(cache_path))

        # Verify the data was loaded correctly
        assert "nand2" in parser.subckts, "nand2 subckt not loaded"
        assert "inv" in parser.subckts, "inv subckt not loaded"
        assert parser.subckts["nand2"].pins == ["A", "B", "Y", "VDD", "GND"]
        assert parser.subckts["inv"].pins == ["IN", "OUT", "VDD", "GND"]
        assert len(parser.instances_by_parent["top"]) == 2, "Expected 2 instances under top"


def test_unsupported_schema_version_raises() -> None:
    """Verify that future schema versions raise NetlistParseError."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a cache with a future unsupported schema version
        future_cache = {
            "schema_version": 99,  # Much newer than supported v1
            "format": "spice",
            "source": "/tmp/test.sp",
            "subckts": {"dummy": ["a", "b"]},
            "instances": [],
            "aliases": {},
        }
        cache_path = Path(tmpdir) / "future_cache.json"
        with open(cache_path, "w") as f:
            json.dump(future_cache, f)

        # Attempt to load the future cache — should raise NetlistParseError
        with pytest.raises(NetlistParseError) as exc_info:
            NetlistParser(str(cache_path))
        assert "newer than supported" in str(exc_info.value).lower()
        assert "99" in str(exc_info.value), "Error message should mention version 99"
        assert "update netlist-tracer" in str(exc_info.value).lower()
