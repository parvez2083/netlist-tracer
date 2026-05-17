"""Smoke tests for real DSPF parsing (env-gated via NETLIST_TRACER_SPF_SAMPLE)."""

from __future__ import annotations

import os
import time
from collections import Counter

import pytest

from netlist_tracer import BidirectionalTracer, NetlistParser


@pytest.mark.local
class TestRealDspfSmoke:
    """Tests using real DSPF file if NETLIST_TRACER_SPF_SAMPLE env var is set."""

    @pytest.fixture
    def spf_sample_path(self) -> str | None:
        """Get NETLIST_TRACER_SPF_SAMPLE env var or skip test."""
        path = os.getenv("NETLIST_TRACER_SPF_SAMPLE")
        if not path or not os.path.exists(path):
            pytest.skip("NETLIST_TRACER_SPF_SAMPLE not set or file not found")
        return path

    def test_real_dspf_parse_completes(self, spf_sample_path: str) -> None:
        """Real DSPF file parses without exception."""
        parser = NetlistParser(spf_sample_path)

        # Should have successfully parsed
        assert parser.subckts
        assert len(parser.subckts) > 0

    def test_real_dspf_has_instances(self, spf_sample_path: str) -> None:
        """Real DSPF file produces instances."""
        parser = NetlistParser(spf_sample_path)

        # Count instances across all parent cells
        total_insts = sum(len(insts) for insts in parser.instances_by_parent.values())
        assert total_insts > 0

    def test_real_dspf_format_marked(self, spf_sample_path: str) -> None:
        """Real DSPF file format is detected as 'spf'."""
        parser = NetlistParser(spf_sample_path)

        assert parser.format == "spf"

    def test_real_dspf_cell_type_breakdown(self, spf_sample_path: str) -> None:
        """Real DSPF cell_type breakdown shows real model names, not $-prefixed."""
        parser = NetlistParser(spf_sample_path)

        # Get the top-level subckt
        top = list(parser.subckts.keys())[0]
        insts = parser.instances_by_parent.get(top, [])

        # Build cell_type counter
        ctps = Counter(i.cell_type for i in insts)

        # Check: NO entries matching r'^\$'
        dllr_pfxd = {ct for ct in ctps.keys() if ct.startswith("$")}
        assert len(dllr_pfxd) == 0, f"Found {len(dllr_pfxd)} $-prefixed cell_types: {dllr_pfxd}"

        # Check: Should have real model names (nch_*, pch_*, or passive elements R, C, L, etc.)
        has_transistor_or_passive = any(
            ct.startswith(("nch_", "pch_", "r_", "c_")) or ct in ("R", "C", "L", "M")
            for ct in ctps.keys()
        )
        assert has_transistor_or_passive, (
            f"Expected at least one transistor or passive element; "
            f"got cell_types: {list(ctps.keys())}"
        )

    def test_real_dspf_tracer_ac7a_returns_paths(self, spf_sample_path: str) -> None:
        """AC7a: Real DSPF tracer returns >= 1 path (lateral walk through galvanic R/L only)."""
        parser = NetlistParser(spf_sample_path)

        # Get top-level subckt
        top = list(parser.subckts.keys())[0]
        top_subckt = parser.subckts[top]

        # Get the tracer
        tracer = BidirectionalTracer(parser)

        # AC7a: tracer.trace(top, pin, max_depth=3) should return >= 1 path
        # Cap removal reduces path count significantly; we verify R-walk works
        found_paths = False
        for pin in top_subckt.pins[:3]:
            paths = tracer.trace(top, pin, max_depth=3)
            assert isinstance(paths, list), "trace() should return a list"
            if len(paths) >= 1:
                found_paths = True
                break

        assert found_paths, (
            f"Expected at least one pin on {top} to trace to >= 1 path "
            f"(AC7a); tested pins: {top_subckt.pins[:3]}"
        )

    def test_real_dspf_tracer_ac7b_thru_steps(self, spf_sample_path: str) -> None:
        """AC7b: Traced paths should contain direction='thru' for R cell_type (not C)."""
        parser = NetlistParser(spf_sample_path)

        # Get top-level subckt
        top = list(parser.subckts.keys())[0]
        top_subckt = parser.subckts[top]

        # Get the tracer
        tracer = BidirectionalTracer(parser)

        # AC7b: Check that some paths contain TraceSteps with direction="thru"
        # referencing R (resistors) specifically (not caps)
        found_thru_r = False
        for pin in top_subckt.pins[:5]:
            paths = tracer.trace(top, pin, max_depth=5)
            for path in paths:
                for step in path:
                    if step.direction == "thru" and step.cell == "R":
                        found_thru_r = True
                        break
            if found_thru_r:
                break

        assert found_thru_r, (
            "Expected at least one path with direction='thru' and cell='R'; "
            "caps should emit direction='endpoint', not be walked through"
        )

    def test_real_dspf_tracer_ac7d_caps_skipped(self, spf_sample_path: str) -> None:
        """AC7d: Caps (C, K) are parasitic noise; no path step should reference them.

        Caps should be SKIPPED entirely during lateral walk (no thru, no endpoint).
        Only real circuit elements (R/L thru-walk, transistors/sources endpoint)
        should appear in trace paths.
        """
        parser = NetlistParser(spf_sample_path)
        top = list(parser.subckts.keys())[0]
        top_subckt = parser.subckts[top]
        tracer = BidirectionalTracer(parser)

        cap_steps_found: list[tuple[str, str, str]] = []
        for pin in top_subckt.pins[:5]:
            paths = tracer.trace(top, pin, max_depth=5)
            for path in paths:
                for step in path:
                    if step.cell in ("C", "K"):
                        cap_steps_found.append((pin, step.direction, str(step.instance_name)))

        assert not cap_steps_found, (
            f"Caps (C, K) should be SKIPPED during lateral walk (parasitic noise), "
            f"but found {len(cap_steps_found)} steps referencing them: {cap_steps_found[:5]}"
        )

    def test_real_dspf_r_count_reduces(self, spf_sample_path: str) -> None:
        """AC11: Real small DSPF R instance count drops by >= 30% post-reduction."""
        parser = NetlistParser(spf_sample_path)
        top = list(parser.subckts.keys())[0]
        insts = parser.instances_by_parent.get(top, [])

        # Count R instances post-reduction
        r_count_reduced = sum(1 for i in insts if i.cell_type == "R")

        # To estimate unreduced count, count instances with _merged_from > 1 entry
        merged_count = sum(
            len(i.params.get("_merged_from", [])) - 1
            for i in insts
            if i.cell_type == "R" and i.params.get("_merged_from")
        )
        r_count_unreduced_est = r_count_reduced + merged_count

        # Reduction should be >= 30%
        reduction_pct = (
            (r_count_unreduced_est - r_count_reduced) / r_count_unreduced_est * 100
            if r_count_unreduced_est > 0
            else 0
        )

        assert reduction_pct >= 30, (
            f"Expected R reduction >= 30%; got {reduction_pct:.1f}% "
            f"(post-reduction: {r_count_reduced}, estimated unreduced: {r_count_unreduced_est})"
        )

    def test_real_dspf_merged_names_present(self, spf_sample_path: str) -> None:
        """AC12: Real small DSPF has merged R names (_to_) and _merged_from populated."""
        parser = NetlistParser(spf_sample_path)
        top = list(parser.subckts.keys())[0]
        insts = parser.instances_by_parent.get(top, [])

        # Find R instances with '_to_' in name
        merged_names = [i for i in insts if i.cell_type == "R" and "_to_" in i.name]

        assert len(merged_names) > 0, "Expected at least one R instance with '_to_' in name"

        # At least one merged R should have _merged_from with > 1 entries
        merged_from_populated = [
            i
            for i in merged_names
            if i.params.get("_merged_from") and len(i.params.get("_merged_from", [])) > 1
        ]

        assert len(merged_from_populated) > 0, (
            "Expected at least one merged R to have _merged_from with > 1 entries"
        )

    def test_real_dspf_tracer_reaches_transistor_via_merged_chain(
        self, spf_sample_path: str
    ) -> None:
        """AC13: Real DSPF tracer reaches transistor endpoint through merged R chains.

        At least one path should contain a thru-step where instance_name contains '_to_'
        AND the path reaches a transistor endpoint.
        """
        parser = NetlistParser(spf_sample_path)
        top = list(parser.subckts.keys())[0]
        top_subckt = parser.subckts[top]
        tracer = BidirectionalTracer(parser)

        found_merged_to_transistor = False
        for pin in top_subckt.pins[:10]:
            paths = tracer.trace(top, pin, max_depth=5)
            for path in paths:
                has_merged_r = False
                has_transistor = False

                for step in path:
                    if step.direction == "thru" and "_to_" in (step.instance_name or ""):
                        has_merged_r = True
                    if (
                        step.direction == "endpoint"
                        and step.cell
                        and step.cell[0]
                        in (
                            "n",
                            "p",
                        )
                    ):
                        # Transistor (nch_*, pch_*, etc.)
                        has_transistor = True

                if has_merged_r and has_transistor:
                    found_merged_to_transistor = True
                    break

            if found_merged_to_transistor:
                break

        assert found_merged_to_transistor, (
            "Expected at least one path with merged R (name contains '_to_') "
            "reaching a transistor endpoint"
        )

    def test_reduction_perf_under_5s(self, spf_sample_path: str) -> None:
        """AC14: Performance - small DSPF reduction completes in < 5 seconds."""
        start_time = time.time()
        NetlistParser(spf_sample_path)  # Timed: parse + reduction
        elapsed = time.time() - start_time

        assert elapsed < 5.0, (
            f"Expected parse + reduction to complete in < 5.0 seconds; took {elapsed:.2f}s"
        )
