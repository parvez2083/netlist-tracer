"""Parity tests: direct-parse == reload-from-cache-parse."""

from __future__ import annotations

import os
import tempfile

import pytest

from netlist_tracer import BidirectionalTracer, NetlistParser, format_path

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "vendored")


class TestCacheRoundtrip:
    """Parametrized cache roundtrip validation across SPICE, Verilog, EDIF."""

    @pytest.mark.parametrize(
        "fixture_path,format_name,start_cell,start_pin",
        [
            (
                os.path.join(FIXTURES_DIR, "sky130_fd_sc_hd__inv_1.spice"),
                "spice",
                "sky130_fd_sc_hd__inv_1",
                "A",
            ),
            (
                os.path.join(FIXTURES_DIR, "picorv32.v"),
                "verilog",
                "picorv32",
                "clk",
            ),
            (
                os.path.join(FIXTURES_DIR, "AND_gate.edf"),
                "edif",
                "logic_gate",
                "a",
            ),
        ],
    )
    def test_cache_roundtrip_parity(
        self,
        fixture_path: str,
        format_name: str,
        start_cell: str,
        start_pin: str,
    ) -> None:
        """Direct parse and reload-from-cache parse must produce identical traces."""
        # Direct parse
        parser1 = NetlistParser(fixture_path)
        tracer1 = BidirectionalTracer(parser1)
        paths1 = tracer1.trace(start_cell, start_pin)
        formatted1 = sorted(set(format_path(p) for p in paths1))

        # Cache roundtrip
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_file = os.path.join(tmpdir, "cache.json")

            # Dump to cache
            parser1.dump_json(cache_file)

            # Reload from cache
            parser2 = NetlistParser(cache_file)
            tracer2 = BidirectionalTracer(parser2)
            paths2 = tracer2.trace(start_cell, start_pin)
            formatted2 = sorted(set(format_path(p) for p in paths2))

        # Must match
        assert formatted2 == formatted1, f"Cache roundtrip mismatch for {format_name}"
