"""Tests for include statement support in SPICE/Spectre parsing."""

from __future__ import annotations

import os
import tempfile

import pytest

from netlist_tracer import NetlistParser
from netlist_tracer.exceptions import NetlistParseError

SYNTHETIC_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "synthetic")


class TestIncludeSupport:
    """Tests for nested includes, cycle detection, and search paths."""

    def test_nested_include_2_levels(self) -> None:
        """Parse top.sp which includes mid.sp which includes leaf.sp."""
        top_file = os.path.join(SYNTHETIC_DIR, "include_2level_top.sp")
        parser = NetlistParser(top_file)

        # All three subckts should be visible: TOP, MID, LEAF
        assert "TOP" in parser.subckts
        assert "MID" in parser.subckts
        assert "LEAF" in parser.subckts

    def test_include_cycle_3_files_raises(self) -> None:
        """Parse a.sp -> b.sp -> c.sp -> a.sp cycle; must raise NetlistParseError."""
        cycle_file = os.path.join(SYNTHETIC_DIR, "include_cycle_a.sp")

        with pytest.raises(NetlistParseError) as exc_info:
            NetlistParser(cycle_file)

        error_msg = str(exc_info.value)
        assert "cycle" in error_msg.lower()

    def test_include_search_path_relative_to_includer(self) -> None:
        """Parent.sp in tmpdir/ includes child.sp in tmpdir/sub/.
        Should resolve relative-path includes without needing -I flag.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create child.sp in tmpdir/sub/
            sub_dir = os.path.join(tmpdir, "sub")
            os.makedirs(sub_dir)
            child_file = os.path.join(sub_dir, "child.sp")
            with open(child_file, "w") as f:
                f.write(".subckt CHILD a b\n")
                f.write("R1 a b res=1k\n")
                f.write(".ends CHILD\n")

            # Create parent.sp in tmpdir/
            parent_file = os.path.join(tmpdir, "parent.sp")
            with open(parent_file, "w") as f:
                f.write(".include 'sub/child.sp'\n")
                f.write(".subckt PARENT a b\n")
                f.write("X1 a b CHILD\n")
                f.write(".ends PARENT\n")

            # Resolve should succeed via relative path from parent's directory
            parser = NetlistParser(parent_file)
            assert "PARENT" in parser.subckts
            assert "CHILD" in parser.subckts

    def test_include_search_path_via_include_paths(self) -> None:
        """Parent.sp includes child.sp. With include_paths=[dir2],
        should resolve child.sp from dir2.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create parent.sp in tmpdir
            parent_file = os.path.join(tmpdir, "parent.sp")
            with open(parent_file, "w") as f:
                f.write(".subckt PARENT a b\n")
                f.write(".include 'child.sp'\n")
                f.write("X1 a b CHILD\n")
                f.write(".ends PARENT\n")

            # Create a separate directory with child.sp
            child_dir = os.path.join(tmpdir, "child_dir")
            os.makedirs(child_dir)
            child_file = os.path.join(child_dir, "child.sp")
            with open(child_file, "w") as f:
                f.write(".subckt CHILD a b\n")
                f.write("R1 a b res=1k\n")
                f.write(".ends CHILD\n")

            # Parse parent.sp with include_paths=[child_dir]
            parser = NetlistParser(parent_file, include_paths=[child_dir])
            assert "PARENT" in parser.subckts
            assert "CHILD" in parser.subckts

    def test_include_unresolvable_raises(self) -> None:
        """Parent.sp includes non-existent file. Must raise NetlistParseError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            parent_file = os.path.join(tmpdir, "parent.sp")
            with open(parent_file, "w") as f:
                f.write(".subckt PARENT a b\n")
                f.write(".include 'does_not_exist.sp'\n")
                f.write(".ends PARENT\n")

            with pytest.raises(NetlistParseError) as exc_info:
                NetlistParser(parent_file)

            error_msg = str(exc_info.value)
            assert "does_not_exist.sp" in error_msg or "not found" in error_msg.lower()

    def test_include_diamond_not_cycle(self) -> None:
        """a.sp includes b.sp and c.sp; b.sp includes d.sp; c.sp includes d.sp.
        This is NOT a cycle (d.sp appears in only one branch's stack at a time).
        Parsing must succeed.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create d.sp
            d_file = os.path.join(tmpdir, "d.sp")
            with open(d_file, "w") as f:
                f.write(".subckt D a b\n")
                f.write("R1 a b res=1k\n")
                f.write(".ends D\n")

            # Create b.sp (includes d)
            b_file = os.path.join(tmpdir, "b.sp")
            with open(b_file, "w") as f:
                f.write(".include 'd.sp'\n")
                f.write(".subckt B a b\n")
                f.write("X1 a b D\n")
                f.write(".ends B\n")

            # Create c.sp (includes d)
            c_file = os.path.join(tmpdir, "c.sp")
            with open(c_file, "w") as f:
                f.write(".include 'd.sp'\n")
                f.write(".subckt C a b\n")
                f.write("X1 a b D\n")
                f.write(".ends C\n")

            # Create a.sp (includes b and c)
            a_file = os.path.join(tmpdir, "a.sp")
            with open(a_file, "w") as f:
                f.write(".include 'b.sp'\n")
                f.write(".include 'c.sp'\n")
                f.write(".subckt A a b c d\n")
                f.write("X1 a b B\n")
                f.write("X2 c d C\n")
                f.write(".ends A\n")

            # This should parse successfully
            parser = NetlistParser(a_file)
            assert "A" in parser.subckts
            assert "B" in parser.subckts
            assert "C" in parser.subckts
            assert "D" in parser.subckts

    def test_include_quoted_and_bare_paths(self) -> None:
        """Variants `.include "path"`, `.include 'path'`, `.include path` all work."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create child.sp
            child_file = os.path.join(tmpdir, "child.sp")
            with open(child_file, "w") as f:
                f.write(".subckt CHILD a b\n")
                f.write("R1 a b res=1k\n")
                f.write(".ends CHILD\n")

            # Test double-quoted
            parent1 = os.path.join(tmpdir, "parent1.sp")
            with open(parent1, "w") as f:
                f.write('.include "child.sp"\n')
                f.write(".subckt PARENT1 a b\n")
                f.write("X1 a b CHILD\n")
                f.write(".ends PARENT1\n")

            parser1 = NetlistParser(parent1)
            assert "CHILD" in parser1.subckts

            # Test single-quoted
            parent2 = os.path.join(tmpdir, "parent2.sp")
            with open(parent2, "w") as f:
                f.write(".include 'child.sp'\n")
                f.write(".subckt PARENT2 a b\n")
                f.write("X1 a b CHILD\n")
                f.write(".ends PARENT2\n")

            parser2 = NetlistParser(parent2)
            assert "CHILD" in parser2.subckts

            # Test bare path
            parent3 = os.path.join(tmpdir, "parent3.sp")
            with open(parent3, "w") as f:
                f.write(".include child.sp\n")
                f.write(".subckt PARENT3 a b\n")
                f.write("X1 a b CHILD\n")
                f.write(".ends PARENT3\n")

            parser3 = NetlistParser(parent3)
            assert "CHILD" in parser3.subckts

    def test_include_inc_alias(self) -> None:
        """`.inc path` is an alias for `.include path`. Must resolve."""
        with tempfile.TemporaryDirectory() as tmpdir:
            child_file = os.path.join(tmpdir, "child.sp")
            with open(child_file, "w") as f:
                f.write(".subckt CHILD a b\n")
                f.write("R1 a b res=1k\n")
                f.write(".ends CHILD\n")

            parent_file = os.path.join(tmpdir, "parent.sp")
            with open(parent_file, "w") as f:
                f.write(".inc 'child.sp'\n")
                f.write(".subckt PARENT a b\n")
                f.write("X1 a b CHILD\n")
                f.write(".ends PARENT\n")

            parser = NetlistParser(parent_file)
            assert "CHILD" in parser.subckts

    def test_include_self_cycle(self) -> None:
        """Self-referential file include. Must raise NetlistParseError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self_file = os.path.join(tmpdir, "self.sp")
            with open(self_file, "w") as f:
                f.write(".include 'self.sp'\n")
                f.write(".subckt SELF a b\n")
                f.write("R1 a b res=1k\n")
                f.write(".ends SELF\n")

            with pytest.raises(NetlistParseError) as exc_info:
                NetlistParser(self_file)

            error_msg = str(exc_info.value)
            assert "cycle" in error_msg.lower()

    def test_lib_directive_named_section_skipped(self, caplog) -> None:
        """`.lib path libname` (named-section form) is skipped entirely with a warning.

        Lib-section semantics aren't supported; the file at `path` is NOT included.
        Parsing of the rest of the parent file proceeds normally.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            lib_file = os.path.join(tmpdir, "transistor_lib.lib")
            with open(lib_file, "w") as f:
                f.write(".subckt Q_NPNX c b e\n")
                f.write("Q1 c b e transistor_model\n")
                f.write(".ends Q_NPNX\n")

            parent_file = os.path.join(tmpdir, "parent.sp")
            with open(parent_file, "w") as f:
                f.write(".lib 'transistor_lib.lib' LIB_SECTION\n")
                f.write(".subckt TOP a b c\n")
                f.write("X1 a b c Q_NPNX\n")
                f.write(".ends TOP\n")

            with caplog.at_level("WARNING"):
                parser = NetlistParser(parent_file)
            assert "TOP" in parser.subckts
            assert "Q_NPNX" not in parser.subckts
            assert any("lib-section semantics unsupported" in r.message for r in caplog.records)

    def test_lib_directive_bare_include(self) -> None:
        """`.lib path` (no libname) inlines the entire file like `.include`."""
        with tempfile.TemporaryDirectory() as tmpdir:
            lib_file = os.path.join(tmpdir, "transistor_lib.lib")
            with open(lib_file, "w") as f:
                f.write(".subckt Q_NPNX c b e\n")
                f.write("Q1 c b e transistor_model\n")
                f.write(".ends Q_NPNX\n")

            parent_file = os.path.join(tmpdir, "parent.sp")
            with open(parent_file, "w") as f:
                f.write(".lib 'transistor_lib.lib'\n")
                f.write(".subckt TOP a b c\n")
                f.write("X1 a b c Q_NPNX\n")
                f.write(".ends TOP\n")

            parser = NetlistParser(parent_file)
            assert "TOP" in parser.subckts
            assert "Q_NPNX" in parser.subckts

    def test_spectre_include(self) -> None:
        """Spectre include directive: `include "child.scs"` expands child subckt."""
        with tempfile.TemporaryDirectory() as tmpdir:
            child_file = os.path.join(tmpdir, "child.scs")
            with open(child_file, "w") as f:
                f.write("subckt foo a b\n")
                f.write("  r1 a b resistor r=1k\n")
                f.write("ends foo\n")

            parent_file = os.path.join(tmpdir, "parent.scs")
            with open(parent_file, "w") as f:
                f.write("include \"child.scs\"\n")
                f.write("subckt top x y\n")
                f.write("  x1 x y foo\n")
                f.write("ends top\n")

            # Should parse Spectre file and expand includes
            parser = NetlistParser(parent_file)
            assert "foo" in parser.subckts, "Child subckt should be parsed from include"
            assert "top" in parser.subckts

    def test_spectre_simulator_lang_spice_include(self) -> None:
        """Spectre `simulator lang=spice` block with SPICE .include directive expands correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Child SPICE file with SPICE syntax
            child_file = os.path.join(tmpdir, "child.sp")
            with open(child_file, "w") as f:
                f.write(".subckt bar a b\n")
                f.write("R1 a b 1k\n")
                f.write(".ends bar\n")

            # Parent Spectre file with simulator lang=spice block containing SPICE .include
            parent_file = os.path.join(tmpdir, "parent.scs")
            with open(parent_file, "w") as f:
                f.write("simulator lang=spice\n")
                f.write(".include 'child.sp'\n")  # SPICE include syntax (correct in spice mode)
                f.write("endsimulator\n")
                f.write("subckt top x y\n")
                f.write("  x1 x y bar\n")
                f.write("ends top\n")

            # Verify include expansion recognizes .include in spice mode
            from netlist_tracer.parsers.includes import expand_includes
            expanded = expand_includes(parent_file, 'spectre')
            expanded_text = '\n'.join([line[0] for line in expanded])

            # The .subckt bar should be expanded from child.sp
            assert '.subckt bar' in expanded_text, "SPICE .include should expand child SPICE content"
            assert '.ends bar' in expanded_text, "Expanded content should include complete subckt definition"

