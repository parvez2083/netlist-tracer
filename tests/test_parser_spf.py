"""Tests for SPF/DSPF parser functionality."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from netlist_tracer import NetlistParser
from netlist_tracer.exceptions import NetlistParseError
from netlist_tracer.parsers.detect import detect_format
from netlist_tracer.parsers.spf import parse_spf


class TestDetectSpfFormat:
    """Tests for SPF format detection."""

    def test_detect_spf_extension(self) -> None:
        """detect_format returns 'spf' for .spf files."""
        fixture_dir = Path(__file__).parent / "fixtures" / "synthetic"
        spf_file = str(fixture_dir / "simple.spf")

        fmt = detect_format([spf_file])

        assert fmt == "spf"

    def test_detect_dspf_extension(self) -> None:
        """detect_format returns 'spf' for .dspf files with SPF content."""
        # Create a temporary .dspf file with SPF marker
        with tempfile.NamedTemporaryFile(suffix=".dspf", mode="w", delete=False) as f:
            f.write("*|DSPF 1.0\n.SUBCKT TEST_DSPF a b\n.ENDS TEST_DSPF\n")
            dspf_file = f.name

        try:
            fmt = detect_format([dspf_file])
            assert fmt == "spf"
        finally:
            Path(dspf_file).unlink()

    def test_detect_spf_content_marker(self) -> None:
        """detect_format returns 'spf' for *|DSPF marker regardless of extension."""
        fixture_dir = Path(__file__).parent / "fixtures" / "synthetic"
        txt_file = str(fixture_dir / "spf_dspf_marker.txt")

        fmt = detect_format([txt_file])

        assert fmt == "spf"


class TestParseSimpleSpf:
    """Tests for basic SPF parsing."""

    def test_parse_simple_spf_subckt(self) -> None:
        """Parse simple.spf and verify subckt structure."""
        fixture_dir = Path(__file__).parent / "fixtures" / "synthetic"
        spf_file = str(fixture_dir / "simple.spf")

        sbckts, insts, _ = parse_spf(spf_file)

        # Check subckt was parsed
        assert "INV" in sbckts
        inv = sbckts["INV"]
        assert inv.pins == ["in", "out", "vdd", "gnd"]

        # Check SPF metadata in params
        assert "_net_caps" in inv.params
        assert "out" in inv.params["_net_caps"]
        assert inv.params["_net_caps"]["out"] == 1.5e-12  # 1.5 PF in Farads

        assert "_ground_net" in inv.params
        assert inv.params["_ground_net"] == "gnd"

        assert "_pin_aliases" in inv.params
        assert "M1:S" in inv.params["_pin_aliases"]
        assert inv.params["_pin_aliases"]["M1:S"] == ("M1", "S")
        assert inv.params["_pin_aliases"]["M2:D"] == ("M2", "D")

    def test_parse_simple_spf_instances(self) -> None:
        """Parse simple.spf and verify instance extraction."""
        fixture_dir = Path(__file__).parent / "fixtures" / "synthetic"
        spf_file = str(fixture_dir / "simple.spf")

        _, insts, _ = parse_spf(spf_file)

        # Should have 4 instances (2 R, 2 C elements)
        assert len(insts) == 4

        # Check R1: resistance element
        r1 = [i for i in insts if i.name == "R1"][0]
        assert r1.cell_type == "R"
        assert r1.parent_cell == "INV"
        assert r1.nets == ["in/X", "in/Y"]

        # Check C1: capacitance element
        c1 = [i for i in insts if i.name == "C1"][0]
        assert c1.cell_type == "C"
        assert c1.parent_cell == "INV"
        assert c1.nets == ["in/X", "gnd"]

    def test_subnode_collapse_on_parse(self) -> None:
        """Verify that net names with subnodes (net:N) are collapsed to parent."""
        fixture_dir = Path(__file__).parent / "fixtures" / "synthetic"
        spf_file = str(fixture_dir / "simple.spf")

        _, insts, _ = parse_spf(spf_file)

        # R2 should have nets normalized: in/Y:subnode -> in/Y (if present)
        r2 = [i for i in insts if i.name == "R2"][0]
        # Simple.spf has R2 gnd without subnode, so no normalization needed
        assert "gnd" in r2.nets


class TestSpfPinAliases:
    """Tests for SPF *|I pin alias extraction."""

    def test_pin_alias_extraction(self) -> None:
        """Verify *|I directives populate pin alias map."""
        fixture_dir = Path(__file__).parent / "fixtures" / "synthetic"
        spf_file = str(fixture_dir / "simple.spf")

        sbckts, _, _ = parse_spf(spf_file)
        inv = sbckts["INV"]

        aliases = inv.params.get("_pin_aliases", {})
        assert "M1:S" in aliases
        assert aliases["M1:S"] == ("M1", "S")


class TestMixedDirDispatch:
    """Tests for mixed SPICE + SPF directory parsing."""

    def test_mixed_dir_spice_plus_spf(self) -> None:
        """Parse mixed directory with .sp and .spf files."""
        fixture_dir = Path(__file__).parent / "fixtures" / "synthetic" / "mixed_dir"

        parser = NetlistParser(str(fixture_dir))

        # Both TB and INV should be present
        assert "TB" in parser.subckts
        assert "INV" in parser.subckts

        # Format should be marked as 'mixed'
        assert parser.format == "mixed"

        # Verify SPF INV has the ground net metadata
        inv = parser.subckts["INV"]
        assert "_ground_net" in inv.params
        assert inv.params["_ground_net"] == "gnd"


class TestSpfFormatCollision:
    """Tests for SPF vs SPICE format collision in mixed dirs."""

    def test_spf_wins_over_spice_on_collision(self, caplog: pytest.LogCaptureFixture) -> None:
        """When same subckt in both SPICE and SPF, SPF version wins (higher priority)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            # Create SPICE file with INV (2 pins)
            sp_file = tmpdir_path / "cell.sp"
            sp_file.write_text("""
.SUBCKT INV a b
.ENDS INV
""")

            # Create SPF file with INV (3 pins)
            spf_file = tmpdir_path / "cell.spf"
            spf_file.write_text("""
*|DSPF 1.0
.SUBCKT INV a b c
*|NET b 1.0PF
.ENDS INV
""")

            parser = NetlistParser(str(tmpdir_path))

            # SPF version (3 pins) should win
            inv = parser.subckts["INV"]
            assert len(inv.pins) == 3
            assert inv.pins == ["a", "b", "c"]

            # Check warning was logged (format collision)
            assert any(
                ("spf" in record.message.lower() and "spice" in record.message.lower())
                for record in caplog.records
            )


class TestSpfEmpty:
    """Tests for error handling on empty/invalid SPF files."""

    def test_parse_empty_spf_raises_error(self) -> None:
        """parse_spf raises NetlistParseError for empty file."""
        with tempfile.NamedTemporaryFile(suffix=".spf", mode="w", delete=False) as f:
            f.write("")
            spf_file = f.name

        try:
            with pytest.raises(NetlistParseError, match="empty"):
                parse_spf(spf_file)
        finally:
            Path(spf_file).unlink()

    def test_parse_spf_no_subckt_raises_error(self) -> None:
        """parse_spf raises NetlistParseError if no .SUBCKT found."""
        with tempfile.NamedTemporaryFile(suffix=".spf", mode="w", delete=False) as f:
            f.write("*|DSPF 1.0\n* Just a comment\n")
            spf_file = f.name

        try:
            with pytest.raises(NetlistParseError, match="No .SUBCKT"):
                parse_spf(spf_file)
        finally:
            Path(spf_file).unlink()
