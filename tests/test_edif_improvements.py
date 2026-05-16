"""Tests for EDIF parser improvements: rename, properties, libraries, bus_order."""

from __future__ import annotations

import os

import pytest

from netlist_tracer import NetlistParser
from netlist_tracer.exceptions import NetlistParseError

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "synthetic")


class TestEDIFRename:
    """Test EDIF rename preservation."""

    def test_edif_rename_preserves_original(self) -> None:
        """Parse EDIF cell with (rename safe \"original\") and verify original name captured."""
        fixture = os.path.join(FIXTURES_DIR, "edif_with_rename.edif")
        parser = NetlistParser(fixture)

        # Check cell-level rename
        assert "SAFE_NAME" in parser.subckts
        safe_nm = parser.subckts["SAFE_NAME"]
        assert safe_nm.params.get("_edif_original_name") == "orig[7:0]"

    def test_edif_no_rename_no_original_name_key(self) -> None:
        """Parse EDIF cell without rename; _edif_original_name key absent."""
        fixture = os.path.join(FIXTURES_DIR, "edif_multi_library.edif")
        parser = NetlistParser(fixture)

        # INV and BUF cells have no rename
        inv = parser.subckts.get("INV")
        assert inv is not None
        assert "_edif_original_name" not in inv.params

        buf = parser.subckts.get("BUF")
        assert buf is not None
        assert "_edif_original_name" not in buf.params

    def test_edif_instance_rename_preserved(self) -> None:
        """Parse EDIF instance with (rename safe \"original\") and verify captured."""
        fixture = os.path.join(FIXTURES_DIR, "edif_with_rename.edif")
        parser = NetlistParser(fixture)

        # Find instance u1_safe
        instances = parser.instances_by_name.get("u1_safe", [])
        assert len(instances) > 0
        inst = instances[0]
        assert inst.params.get("_edif_original_name") == "u1[0]"


class TestEDIFProperties:
    """Test EDIF property preservation."""

    def test_edif_property_string(self) -> None:
        """Parse EDIF property with string value."""
        fixture = os.path.join(FIXTURES_DIR, "edif_with_properties.edif")
        parser = NetlistParser(fixture)

        cell = parser.subckts.get("PROP_TEST")
        assert cell is not None
        prp_dct = cell.params.get("_edif_properties", {})
        assert prp_dct.get("author") == "ACME"

    def test_edif_property_integer(self) -> None:
        """Parse EDIF property with integer value."""
        fixture = os.path.join(FIXTURES_DIR, "edif_with_properties.edif")
        parser = NetlistParser(fixture)

        cell = parser.subckts.get("PROP_TEST")
        assert cell is not None
        prp_dct = cell.params.get("_edif_properties", {})
        assert prp_dct.get("width") == 8
        assert isinstance(prp_dct.get("width"), int)

    def test_edif_property_real(self) -> None:
        """Parse EDIF property with real value."""
        fixture = os.path.join(FIXTURES_DIR, "edif_with_properties.edif")
        parser = NetlistParser(fixture)

        cell = parser.subckts.get("PROP_TEST")
        assert cell is not None
        prp_dct = cell.params.get("_edif_properties", {})
        assert prp_dct.get("pi") == pytest.approx(3.14)

    def test_edif_property_boolean(self) -> None:
        """Parse EDIF property with boolean value."""
        fixture = os.path.join(FIXTURES_DIR, "edif_with_properties.edif")
        parser = NetlistParser(fixture)

        cell = parser.subckts.get("PROP_TEST")
        assert cell is not None
        prp_dct = cell.params.get("_edif_properties", {})
        assert prp_dct.get("enabled") is True
        assert isinstance(prp_dct.get("enabled"), bool)

    def test_edif_instance_properties(self) -> None:
        """Parse EDIF instance properties."""
        fixture = os.path.join(FIXTURES_DIR, "edif_with_properties.edif")
        parser = NetlistParser(fixture)

        instances = parser.instances_by_name.get("I1", [])
        assert len(instances) > 0
        inst = instances[0]
        prp_dct = inst.params.get("_edif_properties", {})
        assert prp_dct.get("depth") == 16
        assert isinstance(prp_dct.get("depth"), int)


class TestEDIFLibrary:
    """Test EDIF library tracking and collision handling."""

    def test_edif_library_recorded(self) -> None:
        """Parse EDIF and verify _edif_library param recorded."""
        fixture = os.path.join(FIXTURES_DIR, "edif_multi_library.edif")
        parser = NetlistParser(fixture)

        inv = parser.subckts.get("INV")
        assert inv is not None
        assert inv.params.get("_edif_library") == "tech_lib"

        top = parser.subckts.get("TOP")
        assert top is not None
        assert top.params.get("_edif_library") == "design_lib"

    def test_edif_multi_library_collision_warns(self, caplog) -> None:
        """Parse EDIF with same cell in multiple libraries; warning logged, first-encountered wins."""
        fixture = os.path.join(FIXTURES_DIR, "edif_multi_library_collision.edif")

        # Capture log output
        import logging

        with caplog.at_level(logging.WARNING):
            parser = NetlistParser(fixture)

        # First-encountered INV should be from tech_lib
        inv = parser.subckts.get("INV")
        assert inv is not None
        assert inv.params.get("_edif_library") == "tech_lib"

        # Warning should mention both libraries
        warning_found = any(
            "tech_lib" in record.message and "design_lib" in record.message
            for record in caplog.records
            if record.levelname == "WARNING"
        )
        assert warning_found, "Expected warning about collision not found"


class TestEDIFBusOrder:
    """Test bus_order parameter for port arrays."""

    def test_edif_bus_order_default_msb_first(self) -> None:
        """Parse EDIF bus array with default bus_order='msb_first'."""
        fixture = os.path.join(FIXTURES_DIR, "edif_bus_array.edif")
        parser = NetlistParser(fixture)

        cell = parser.subckts.get("BUS_TEST")
        assert cell is not None

        # MSB-first order: [7], [6], [5], [4], [3], [2], [1], [0]
        expected_pins = [
            "data[7]",
            "data[6]",
            "data[5]",
            "data[4]",
            "data[3]",
            "data[2]",
            "data[1]",
            "data[0]",
            "single",
        ]
        assert cell.pins == expected_pins

    def test_edif_bus_order_lsb_first(self) -> None:
        """Parse EDIF bus array with bus_order='lsb_first'."""
        fixture = os.path.join(FIXTURES_DIR, "edif_bus_array.edif")
        parser = NetlistParser(fixture, bus_order="lsb_first")

        cell = parser.subckts.get("BUS_TEST")
        assert cell is not None

        # LSB-first order: [0], [1], [2], [3], [4], [5], [6], [7]
        expected_pins = [
            "data[0]",
            "data[1]",
            "data[2]",
            "data[3]",
            "data[4]",
            "data[5]",
            "data[6]",
            "data[7]",
            "single",
        ]
        assert cell.pins == expected_pins

    def test_edif_bus_order_invalid_raises(self) -> None:
        """Parse with invalid bus_order value raises NetlistParseError."""
        fixture = os.path.join(FIXTURES_DIR, "edif_bus_array.edif")

        with pytest.raises(NetlistParseError, match="Invalid bus_order"):
            NetlistParser(fixture, bus_order="invalid_order")

    def test_netlist_parser_bus_order_kwarg(self) -> None:
        """NetlistParser accepts bus_order kwarg and threads it to EDIF parser."""
        fixture = os.path.join(FIXTURES_DIR, "edif_bus_array.edif")
        parser_msb = NetlistParser(fixture, bus_order="msb_first")
        parser_lsb = NetlistParser(fixture, bus_order="lsb_first")

        cell_msb = parser_msb.subckts.get("BUS_TEST")
        cell_lsb = parser_lsb.subckts.get("BUS_TEST")

        # Verify they produce different pin orders
        assert cell_msb.pins != cell_lsb.pins
        # MSB-first should start with [7]
        assert cell_msb.pins[0] == "data[7]"
        # LSB-first should start with [0]
        assert cell_lsb.pins[0] == "data[0]"

    def test_netlist_parser_bus_order_ignored_for_non_edif(self) -> None:
        """bus_order kwarg silently ignored for non-EDIF files."""
        # Use a Verilog fixture (should not raise)
        fixture = os.path.join(FIXTURES_DIR, "simple.spf")
        # Should not raise even with bus_order kwarg
        parser = NetlistParser(fixture, bus_order="lsb_first")
        assert parser is not None
