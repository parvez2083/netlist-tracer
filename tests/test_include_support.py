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

    def test_include_env_var_expansion(self, monkeypatch) -> None:
        """`.include` with `$VAR/...` form resolves via os.path.expandvars.

        v0.3.1 added environment variable expansion to _resolve_include_path so
        PDK-style paths like `.include '$PDK_ROOT/models.lib'` resolve at parse
        time using the current process environment.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            child_dir = os.path.join(tmpdir, "child_dir")
            os.makedirs(child_dir)
            child_file = os.path.join(child_dir, "child.sp")
            with open(child_file, "w") as f:
                f.write(".subckt CHILD a b\n")
                f.write("R1 a b 1k\n")
                f.write(".ends CHILD\n")

            parent_file = os.path.join(tmpdir, "parent.sp")
            with open(parent_file, "w") as f:
                f.write(".include '$NETTRACE_TEST_DIR/child.sp'\n")
                f.write(".subckt TOP a b\n")
                f.write("X1 a b CHILD\n")
                f.write(".ends TOP\n")

            monkeypatch.setenv("NETTRACE_TEST_DIR", child_dir)
            parser = NetlistParser(parent_file)
            assert "TOP" in parser.subckts
            assert "CHILD" in parser.subckts, "Env-var-expanded include path should have resolved"

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

    def test_lib_directive_named_section_resolvable_inlines(self, caplog) -> None:
        """`.lib path SECTION` resolves and emits ONLY the matched section (v0.3.1).

        v0.3.1 (J): section-aware loading. The resolver scans the inlined file
        for `.lib SECTION ... .endl SECTION` markers and emits only the lines
        between them. Other sections in the file are ignored.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            # Multi-section .lib: TT corner has Q_TT, FF corner has Q_FF.
            lib_file = os.path.join(tmpdir, "transistor_lib.lib")
            with open(lib_file, "w") as f:
                f.write(".lib TT_CORNER\n")
                f.write(".subckt Q_TT c b e\n")
                f.write("Q1 c b e transistor_model\n")
                f.write(".ends Q_TT\n")
                f.write(".endl TT_CORNER\n")
                f.write(".lib FF_CORNER\n")
                f.write(".subckt Q_FF c b e\n")
                f.write("Q1 c b e transistor_model\n")
                f.write(".ends Q_FF\n")
                f.write(".endl FF_CORNER\n")

            parent_file = os.path.join(tmpdir, "parent.sp")
            with open(parent_file, "w") as f:
                f.write(".lib 'transistor_lib.lib' TT_CORNER\n")
                f.write(".subckt TOP a b c\n")
                f.write("X1 a b c Q_TT\n")
                f.write(".ends TOP\n")

            parser = NetlistParser(parent_file)
            assert "TOP" in parser.subckts
            assert "Q_TT" in parser.subckts, (
                "Requested section TT_CORNER's content should be emitted"
            )
            assert "Q_FF" not in parser.subckts, (
                "Non-requested section FF_CORNER's content must NOT be emitted (v0.3.1)"
            )

    def test_lib_directive_named_section_section_not_found(self, caplog) -> None:
        """.lib path SECTION resolves but SECTION absent in file -> WARN + skip (v0.3.1).

        v0.3.1 (J): when the path resolves but the requested section name is
        not found inside the file, the include is skipped with a warning so
        the parent parse can continue.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            lib_file = os.path.join(tmpdir, "transistor_lib.lib")
            with open(lib_file, "w") as f:
                f.write(".lib TT_CORNER\n")
                f.write(".subckt Q_TT c b e\n")
                f.write("Q1 c b e transistor_model\n")
                f.write(".ends Q_TT\n")
                f.write(".endl TT_CORNER\n")

            parent_file = os.path.join(tmpdir, "parent.sp")
            with open(parent_file, "w") as f:
                f.write(".lib 'transistor_lib.lib' NONEXISTENT_SECTION\n")
                f.write(".subckt TOP a b c\n")
                f.write("R1 a b 1k\n")
                f.write(".ends TOP\n")

            with caplog.at_level("WARNING"):
                parser = NetlistParser(parent_file)
            assert "TOP" in parser.subckts, (
                "Parent must remain visible after section-not-found WARN+skip"
            )
            assert "Q_TT" not in parser.subckts, (
                "Section not requested -> nothing should be emitted"
            )
            assert any("section not found" in r.message.lower() for r in caplog.records), (
                f"Expected 'section not found' warning; got: {[r.message for r in caplog.records]}"
            )

    def test_lib_directive_named_section_unresolvable(self, caplog) -> None:
        """.lib path section with unresolvable path -> WARNING + skip, no raise."""
        with tempfile.TemporaryDirectory() as tmpdir:
            parent_file = os.path.join(tmpdir, "parent.sp")
            missing_path = os.path.join(tmpdir, "definitely_missing.lib")
            with open(parent_file, "w") as f:
                f.write(f".lib '{missing_path}' SOME_SECTION\n")
                f.write(".subckt TOP a b c\n")
                f.write("R1 a b 1k\n")
                f.write(".ends TOP\n")

            with caplog.at_level("WARNING"):
                parser = NetlistParser(parent_file)
            assert "TOP" in parser.subckts
            assert any("unresolvable" in r.message.lower() for r in caplog.records), (
                f"Expected unresolvable warning; got: {[r.message for r in caplog.records]}"
            )

    def test_lib_directive_bare_include(self) -> None:
        """`.lib path` (no section) inlines the entire file like `.include`."""
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

    def test_lib_directive_bare_unresolvable(self, caplog) -> None:
        """Bare `.lib path` with unresolvable path -> WARNING + skip, no raise (v0.3.1).

        HSPICE files commonly contain intra-file `.lib SECTION_NAME` markers
        that open a section block. These are syntactically identical to a
        bare-form .lib path include directive. v0.3.1 extends the
        try-and-degrade pattern (already used for `.lib path section`) to
        the bare form so the parser doesn't abort on these markers.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            parent_file = os.path.join(tmpdir, "parent.sp")
            # 'tt_allDevices_post' is a typical HSPICE intra-file section
            # marker name; with no resolvable file, it should warn+skip.
            with open(parent_file, "w") as f:
                f.write(".lib tt_allDevices_post\n")
                f.write(".subckt TOP a b c\n")
                f.write("R1 a b 1k\n")
                f.write(".ends TOP\n")

            with caplog.at_level("WARNING"):
                parser = NetlistParser(parent_file)
            assert "TOP" in parser.subckts, (
                "Parent subckt must remain visible after bare .lib WARN+skip"
            )
            assert any("unresolvable" in r.message.lower() for r in caplog.records), (
                f"Expected unresolvable warning; got: {[r.message for r in caplog.records]}"
            )

    def test_include_directive_unresolvable_still_raises(self) -> None:
        """`.include` (NOT `.lib`) with unresolvable path STILL raises (v0.3.1).

        Confirms that v0.3.1's try-and-degrade scope is intentionally limited
        to `.lib` (best-effort PDK overlay) and does NOT extend to `.include`
        / `.inc` (explicit dependencies). This is the inverse-direction
        regression for deliverable H.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            parent_file = os.path.join(tmpdir, "parent.sp")
            missing_path = os.path.join(tmpdir, "definitely_missing.sp")
            with open(parent_file, "w") as f:
                f.write(f".include '{missing_path}'\n")
                f.write(".subckt TOP a b c\n")
                f.write("R1 a b 1k\n")
                f.write(".ends TOP\n")

            with pytest.raises(NetlistParseError, match="Include path not found"):
                NetlistParser(parent_file)

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
                f.write('include "child.scs"\n')
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

            expanded = expand_includes(parent_file, "spectre")
            expanded_text = "\n".join([line[0] for line in expanded])

            # The .subckt bar should be expanded from child.sp
            assert ".subckt bar" in expanded_text, (
                "SPICE .include should expand child SPICE content"
            )
            assert ".ends bar" in expanded_text, (
                "Expanded content should include complete subckt definition"
            )

    def test_spectre_include_section_resolvable_inlines(self, caplog) -> None:
        """Spectre `include "path" section=NAME` emits only the matched library (v0.3.1).

        v0.3.1 (J): Spectre section-aware loading scans the inlined file for
        `library NAME ... endlibrary NAME` markers and emits only the lines
        between them.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            child_file = os.path.join(tmpdir, "child.scs")
            with open(child_file, "w") as f:
                f.write("library SSG_PRE\n")
                f.write("subckt foo a b\n")
                f.write("  r1 a b resistor r=1k\n")
                f.write("ends foo\n")
                f.write("endlibrary SSG_PRE\n")
                f.write("library FFG_PRE\n")
                f.write("subckt bar a b\n")
                f.write("  r1 a b resistor r=2k\n")
                f.write("ends bar\n")
                f.write("endlibrary FFG_PRE\n")

            parent_file = os.path.join(tmpdir, "parent.scs")
            with open(parent_file, "w") as f:
                f.write('include "child.scs" section=SSG_PRE\n')
                f.write("subckt top x y\n")
                f.write("  x1 x y foo\n")
                f.write("ends top\n")

            parser = NetlistParser(parent_file)
            assert "top" in parser.subckts
            assert "foo" in parser.subckts, (
                "Requested library SSG_PRE's content should be emitted (v0.3.1)"
            )
            assert "bar" not in parser.subckts, (
                "Non-requested library FFG_PRE's content must NOT be emitted"
            )

    def test_spectre_include_section_unresolvable(self, monkeypatch, caplog) -> None:
        """Spectre `include "path" section=NAME` with unresolvable path -> WARNING + skip, no raise."""
        # Ensure the env var is NOT set in case the host shell has it.
        monkeypatch.delenv("NETTRACE_TEST_NONEXISTENT_VAR", raising=False)
        with tempfile.TemporaryDirectory() as tmpdir:
            parent_file = os.path.join(tmpdir, "parent.scs")
            with open(parent_file, "w") as f:
                f.write('include "$NETTRACE_TEST_NONEXISTENT_VAR/missing.slib" section=foo\n')
                f.write("subckt top x y\n")
                f.write("  r1 x y resistor r=1k\n")
                f.write("ends top\n")

            with caplog.at_level("WARNING"):
                parser = NetlistParser(parent_file)
            assert "top" in parser.subckts
            assert any("unresolvable" in r.message.lower() for r in caplog.records), (
                f"Expected unresolvable warning; got: {[r.message for r in caplog.records]}"
            )

    def test_lib_directive_same_file_two_sections_no_false_cycle(self) -> None:
        """L fix: .lib path SECTION_A and .lib path SECTION_B from same file must NOT trigger false cycle.

        v0.3.1 (L): cycle detection now keys on (path, section_filter) tuple, not just path.
        Two `.lib path SECTION_A` and `.lib path SECTION_B` calls into the same file are
        distinct logical include units and do not form a cycle.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            # Multi-section .lib: two corners with different subckts
            lib_file = os.path.join(tmpdir, "multi_corner.lib")
            with open(lib_file, "w") as f:
                f.write(".lib CORNER_FF\n")
                f.write(".subckt Q_FF c b e\n")
                f.write("Q1 c b e nmos_ff\n")
                f.write(".ends Q_FF\n")
                f.write(".endl CORNER_FF\n")
                f.write(".lib CORNER_SS\n")
                f.write(".subckt Q_SS c b e\n")
                f.write("Q1 c b e nmos_ss\n")
                f.write(".ends Q_SS\n")
                f.write(".endl CORNER_SS\n")

            parent_file = os.path.join(tmpdir, "parent.sp")
            with open(parent_file, "w") as f:
                # Include same file with different sections
                f.write(".lib 'multi_corner.lib' CORNER_FF\n")
                f.write(".lib 'multi_corner.lib' CORNER_SS\n")
                f.write(".subckt TOP a b c\n")
                f.write("X1 a b c Q_FF\n")
                f.write("X2 a b c Q_SS\n")
                f.write(".ends TOP\n")

            # This must parse successfully (no false cycle error)
            parser = NetlistParser(parent_file)
            assert "TOP" in parser.subckts
            assert "Q_FF" in parser.subckts
            assert "Q_SS" in parser.subckts

    def test_lib_directive_cycle_inside_file_hard_failure(self) -> None:
        """M fix: real cycle inside .lib file must propagate and exit 1, not degrade to WARNING.

        v0.3.1 (M): try-and-degrade now discriminates exception types. Only
        IncludePathNotFoundError (unresolvable paths) triggers degradation.
        Cycle-detection errors raise NetlistParseError and propagate, causing
        CLI exit code 1.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a cycle: a.lib includes b.lib, b.lib includes a.lib
            a_lib = os.path.join(tmpdir, "a.lib")
            b_lib = os.path.join(tmpdir, "b.lib")

            with open(a_lib, "w") as f:
                f.write(".lib CORNER_A\n")
                f.write(".subckt QA c b e\n")
                f.write("Q1 c b e nmos\n")
                f.write(".ends QA\n")
                f.write(f".include '{b_lib}'\n")
                f.write(".endl CORNER_A\n")

            with open(b_lib, "w") as f:
                f.write(".lib CORNER_B\n")
                f.write(".subckt QB c b e\n")
                f.write("Q1 c b e nmos\n")
                f.write(".ends QB\n")
                f.write(f".include '{a_lib}'\n")
                f.write(".endl CORNER_B\n")

            parent_file = os.path.join(tmpdir, "parent.sp")
            with open(parent_file, "w") as f:
                f.write(f".include '{a_lib}'\n")
                f.write(".subckt TOP a b c\n")
                f.write("X1 a b c QA\n")
                f.write(".ends TOP\n")

            # This must raise NetlistParseError (cycle detection), not degrade to warning
            with pytest.raises(NetlistParseError) as exc_info:
                NetlistParser(parent_file)

            error_msg = str(exc_info.value)
            assert "cycle" in error_msg.lower()
