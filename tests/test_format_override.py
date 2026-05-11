"""Unit tests for format detection and override (content-first detection refactor)."""

import os
import tempfile

import pytest

from netlist_tracer.exceptions import NetlistParseError
from netlist_tracer.parser import NetlistParser
from netlist_tracer.parsers.detect import detect_format


def test_content_beats_extension_v_with_spectre_content():
    """Content-first: .v file with Spectre content detects as spectre."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".v", delete=False) as f:
        f.write("simulator lang=spectre\nsubckt foo a b c\nends foo\n")
        path = f.name

    try:
        fmt = detect_format([path])
        assert fmt == "spectre", f"Expected spectre, got {fmt}"
    finally:
        os.unlink(path)


def test_unknown_extension_with_verilog_content():
    """Content-first: .unknown file with Verilog content detects as verilog."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".unknown", delete=False) as f:
        f.write("module foo(a, b, c);\nendmodule\n")
        path = f.name

    try:
        fmt = detect_format([path])
        assert fmt == "verilog", f"Expected verilog, got {fmt}"
    finally:
        os.unlink(path)


def test_no_content_signal_falls_back_to_extension():
    """Extension tiebreaker: .scs file with no format markers detects as spectre."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".scs", delete=False) as f:
        f.write("* this is a blank-ish file\n")
        path = f.name

    try:
        fmt = detect_format([path])
        assert fmt == "spectre", f"Expected spectre (extension hint), got {fmt}"
    finally:
        os.unlink(path)


def test_no_content_no_extension_defaults_to_spice():
    """Final fallback: .xyz file with no markers defaults to spice."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".xyz", delete=False) as f:
        f.write("* comment only\n")
        path = f.name

    try:
        fmt = detect_format([path])
        assert fmt == "spice", f"Expected spice (default), got {fmt}"
    finally:
        os.unlink(path)


def test_netlist_parser_format_override_kwarg_spectre():
    """NetlistParser format kwarg: explicit format='spectre' overrides auto-detect."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".scs", delete=False) as f:
        f.write("subckt foo a b\nends foo\n")
        path = f.name

    try:
        parser = NetlistParser(path, format="spectre")
        assert parser.format == "spectre", f"format kwarg not respected: {parser.format}"
    finally:
        os.unlink(path)


def test_netlist_parser_format_override_kwarg_verilog():
    """NetlistParser format kwarg: explicit format='verilog' overrides auto-detect."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".v", delete=False) as f:
        f.write("module bar(a, b);\nendmodule\n")
        path = f.name

    try:
        parser = NetlistParser(path, format="verilog")
        assert parser.format == "verilog", f"format kwarg not respected: {parser.format}"
    finally:
        os.unlink(path)


def test_netlist_parser_format_invalid_raises():
    """NetlistParser validation: invalid format value raises NetlistParseError."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".v", delete=False) as f:
        f.write("module dummy(a);\nendmodule\n")
        path = f.name

    try:
        with pytest.raises(NetlistParseError) as exc_info:
            NetlistParser(path, format="vhdl")
        assert "Invalid format" in str(exc_info.value)
    finally:
        os.unlink(path)


def test_cli_format_override_parse_with_spice():
    """CLI format override: format='spice' on a .sp file with _format override works."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".sp", delete=False) as f:
        f.write(".subckt foo a b\nr1 a b 1k\n.ends foo\n")
        sp_path = f.name

    try:
        # Test via NetlistParser API (equivalent to CLI invocation)
        # This validates that the format parameter flows through the API
        import sys
        from unittest.mock import patch

        from netlist_tracer.cli.parse import main

        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = os.path.join(tmpdir, "out.json")
            with patch.object(
                sys,
                "argv",
                [
                    "netlist-parser",
                    "-netlist",
                    sp_path,
                    "-output",
                    out_path,
                    "-format",
                    "spice",
                ],
            ):
                result = main()
            assert result == 0, f"CLI returned non-zero exit code: {result}"
            assert os.path.exists(out_path), f"Output JSON not created at {out_path}"
    finally:
        os.unlink(sp_path)
