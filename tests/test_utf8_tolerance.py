"""Tests for UTF-8 encoding tolerance in file reading."""

from __future__ import annotations

import tempfile
from pathlib import Path

from netlist_tracer.parsers.detect import detect_format
from netlist_tracer.parsers.edif import parse_edif
from netlist_tracer.parsers.includes import expand_includes
from netlist_tracer.parsers.verilog.instances import _sv_parse_file


def test_utf8_latin1_in_comment_parses() -> None:
    """Test that Verilog files with Latin-1 bytes in comments parse successfully."""
    with tempfile.TemporaryDirectory() as tmpdir:
        fpath = Path(tmpdir) / "latin1_test.v"
        # Write file with raw non-UTF-8 byte (0xa9, which is not valid UTF-8)
        content = b"// Copyright notice: \xa9 2024\nmodule test (input clk, output ready);\n    reg valid;\nendmodule\n"
        fpath.write_bytes(content)

        # Parse should succeed without UnicodeDecodeError
        mdls = _sv_parse_file((str(fpath), {}, set(), {}))
        assert len(mdls) > 0
        assert mdls[0]["name"] == "test"


def test_utf8_latin1_in_string_literal_parses() -> None:
    """Test that files with Latin-1 bytes in string literals parse successfully."""
    with tempfile.TemporaryDirectory() as tmpdir:
        fpath = Path(tmpdir) / "latin1_string.v"
        # Create a file with a Latin-1 byte sequence
        content = b"""module test_str (input clk, output ready);
    // String with high byte
    reg [31:0] msg;
endmodule
"""
        fpath.write_bytes(content)

        # Parse should succeed
        mdls = _sv_parse_file((str(fpath), {}, set(), {}))
        assert len(mdls) > 0


def test_detect_format_handles_latin1() -> None:
    """Test that detect_format handles Latin-1 bytes in first 4 KB."""
    with tempfile.TemporaryDirectory() as tmpdir:
        fpath = Path(tmpdir) / "latin1_detect.v"
        # Write with raw non-UTF-8 byte
        content = b"module test (input clk); endmodule \x81\n"
        fpath.write_bytes(content)

        # Detect format should succeed without UnicodeDecodeError
        fmt = detect_format([str(fpath)])
        assert fmt in ("verilog", "spice")


def test_edif_handles_latin1() -> None:
    """Test that EDIF parser handles Latin-1 bytes in comments."""
    with tempfile.TemporaryDirectory() as tmpdir:
        fpath = Path(tmpdir) / "test.edf"
        # Write with raw non-UTF-8 byte
        content = b"""(edif test
  (edifVersion 2 0 0)
  (edifLevel 0)
  (keywordMap (keywordLevel 0))
  (status
    (written (timeStamp 2024 1 1 0 0 0)
      (author "Test \xa9")
      (program "test")))
  (library test
    (edifLevel 0)
    (technology (numberDefinition))
    (cell test (cellType GENERIC)
      (view test (viewType NETLIST))
    )
  )
)
"""
        fpath.write_bytes(content)

        # Parse should succeed
        subckts, insts = parse_edif(str(fpath))
        # Should not raise UnicodeDecodeError


def test_includes_handles_latin1() -> None:
    """Test that include file expansion handles Latin-1 bytes."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)

        # Create included file with raw non-UTF-8 byte
        inc_fpath = tmpdir_path / "lib.sp"
        inc_content = b".lib typical \xa9\n.endl typical\n"
        inc_fpath.write_bytes(inc_content)

        # Create main file
        main_fpath = tmpdir_path / "main.sp"
        main_content = f".include {str(inc_fpath)}\n".encode()
        main_fpath.write_bytes(main_content)

        # Expand includes should succeed
        expanded, ahdl_paths = expand_includes(str(main_fpath), "spice")
        assert len(expanded) > 0
        assert ahdl_paths == []
