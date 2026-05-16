"""Smoke tests for real DSPF parsing (env-gated via NETLIST_TRACER_SPF_SAMPLE)."""

from __future__ import annotations

import os

import pytest

from netlist_tracer import NetlistParser


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
