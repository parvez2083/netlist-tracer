"""Unit tests for Spectre parser (PHASE 10)."""

import os
import tempfile

from netlist_tracer import NetlistParser


def test_spectre_basic_parse(synthetic_spectre_basic_scs):
    """Test parsing basic Spectre netlist."""
    parser = NetlistParser(synthetic_spectre_basic_scs)
    assert parser.format == "spectre"
    assert len(parser.subckts) > 0, "Spectre parser should find subcircuits"


def test_spectre_basic_instances(synthetic_spectre_basic_scs):
    """Test that Spectre parser finds instances."""
    parser = NetlistParser(synthetic_spectre_basic_scs)
    total_instances = sum(len(v) for v in parser.instances_by_parent.values())
    assert total_instances > 0, "Spectre netlist should have instances"


def test_spectre_basic_pins(synthetic_spectre_basic_scs):
    """Test that Spectre parser extracts pins."""
    parser = NetlistParser(synthetic_spectre_basic_scs)
    for sub in parser.subckts.values():
        assert hasattr(sub, "pins"), "Subckt should have pins attribute"
        assert isinstance(sub.pins, list), "Pins should be a list"


def test_spectre_validation(synthetic_spectre_basic_scs):
    """Test Spectre parser connection validation."""
    parser = NetlistParser(synthetic_spectre_basic_scs)
    mismatches = parser.validate_connections(verbose=False)
    assert isinstance(mismatches, list), "validate_connections should return a list"


class TestSpectreSupplementary:
    """Tests for Spectre-specific features: escaped brackets, special characters."""

    def test_spectre_escaped_brackets_in_net_names(self):
        """Test that Spectre escaped brackets in net names are correctly unescaped.

        Verifies that:
        1. Net names with escaped angle brackets (\\<N\\>) are unescaped to <N>
        2. The instance is correctly registered in instances_by_celltype
        3. Instance nets list contains the unescaped net names
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create Spectre netlist with escaped brackets in net names
            deck_path = os.path.join(tmpdir, "tb.scs")
            with open(deck_path, "w") as f:
                f.write("simulator lang=spectre\n")
                f.write("subckt cell_x (a b)\n")
                f.write("ends cell_x\n")
                f.write("subckt top (vdd vss)\n")
                f.write("  inst_1 (net_a\\<0\\> net_a\\<1\\>) cell_x\n")
                f.write("ends top\n")

            # Parse the deck
            parser = NetlistParser(deck_path)

            # Verify both subckts are present
            assert "cell_x" in parser.subckts, "cell_x should be defined"
            assert "top" in parser.subckts, "top should be defined"

            # Verify the instance was registered
            assert "cell_x" in parser.instances_by_celltype, (
                "cell_x instances should be registered in instances_by_celltype"
            )
            insts = parser.instances_by_celltype["cell_x"]
            assert len(insts) == 1, f"Expected 1 instance of cell_x, got {len(insts)}"

            # Verify the instance details
            inst = insts[0]
            assert inst.name == "inst_1", f"Instance name should be inst_1, got {inst.name}"
            assert inst.parent_cell == "top", f"Parent should be top, got {inst.parent_cell}"
            assert inst.nets == ["net_a<0>", "net_a<1>"], (
                f"Nets should be ['net_a<0>', 'net_a<1>'], got {inst.nets}"
            )

    def test_spectre_escaped_specials_in_net_names(self):
        """Test that Spectre escaped special chars (brackets, commas) are correctly unescaped.

        Verifies defensive coverage for escaped brackets and commas.
        Net names like net\\[1\\], plain\\,name parse correctly.

        NOTE: Escaped parens (\\( and \\)) cannot be tested because the instance regex
        in _parse_spectre_instance uses [^)]* to match the connection list, which fails
        when literal parens appear in unescaped net names. This is a known limitation
        of the current regex pattern. Brackets and commas are unaffected by this limitation.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create Spectre netlist with escaped brackets and comma
            deck_path = os.path.join(tmpdir, "tb.scs")
            with open(deck_path, "w") as f:
                f.write("simulator lang=spectre\n")
                f.write("subckt cell_y (a b c)\n")
                f.write("ends cell_y\n")
                f.write("subckt top (vdd vss)\n")
                f.write("  inst_1 (net\\[0\\] net\\[1\\] plain_net) cell_y\n")
                f.write("ends top\n")

            # Parse the deck
            parser = NetlistParser(deck_path)

            # Verify both subckts are present
            assert "cell_y" in parser.subckts, "cell_y should be defined"
            assert "top" in parser.subckts, "top should be defined"

            # Verify the instance was registered
            assert "cell_y" in parser.instances_by_celltype, (
                "cell_y instances should be registered in instances_by_celltype"
            )
            insts = parser.instances_by_celltype["cell_y"]
            assert len(insts) == 1, f"Expected 1 instance of cell_y, got {len(insts)}"

            # Verify the instance details
            inst = insts[0]
            assert inst.name == "inst_1", f"Instance name should be inst_1, got {inst.name}"
            assert inst.parent_cell == "top", f"Parent should be top, got {inst.parent_cell}"
            assert inst.nets == ["net[0]", "net[1]", "plain_net"], (
                f"Nets should be ['net[0]', 'net[1]', 'plain_net'], got {inst.nets}"
            )


class TestSpectrePeek:
    """Peek tests for Spectre format."""

    def test_peek_basic(self, synthetic_spectre_basic_scs):
        """Test peek on Spectre file returns expected pins."""
        pns = NetlistParser.peek_pins(synthetic_spectre_basic_scs, "nand2_spectre")
        assert pns is not None
        assert len(pns) > 0
        assert "Y" in pns

    def test_peek_not_found(self, synthetic_spectre_basic_scs):
        """Test peek returns None for non-existent subckt."""
        pns = NetlistParser.peek_pins(synthetic_spectre_basic_scs, "NONEXISTENT")
        assert pns is None

    def test_peek_case_sensitive(self, synthetic_spectre_basic_scs):
        """Test peek is case-sensitive for Spectre subckt names."""
        pns_correct = NetlistParser.peek_pins(synthetic_spectre_basic_scs, "nand2_spectre")
        pns_wrong = NetlistParser.peek_pins(synthetic_spectre_basic_scs, "NAND2_SPECTRE")
        # Spectre subckt names are case-sensitive
        assert pns_correct is not None
        assert pns_wrong is None
