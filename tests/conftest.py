"""Pytest configuration and fixtures for netlist_tracer tests."""

import os

import pytest


@pytest.fixture
def fixtures_synthetic_dir():
    """Return path to synthetic fixtures directory."""
    return os.path.join(os.path.dirname(__file__), "fixtures", "synthetic")


@pytest.fixture
def synthetic_concat_alias_v(fixtures_synthetic_dir):
    """Path to synthetic concat_alias.v fixture."""
    return os.path.join(fixtures_synthetic_dir, "concat_alias.v")


@pytest.fixture
def synthetic_generate_loop_v(fixtures_synthetic_dir):
    """Path to synthetic generate_loop.v fixture."""
    return os.path.join(fixtures_synthetic_dir, "generate_loop.v")


@pytest.fixture
def synthetic_param_specialize_v(fixtures_synthetic_dir):
    """Path to synthetic param_specialize.v fixture."""
    return os.path.join(fixtures_synthetic_dir, "param_specialize.v")


@pytest.fixture
def synthetic_supply_constant_cdl(fixtures_synthetic_dir):
    """Path to synthetic supply_constant.cdl fixture."""
    return os.path.join(fixtures_synthetic_dir, "supply_constant.cdl")


@pytest.fixture
def synthetic_spice_basic_sp(fixtures_synthetic_dir):
    """Path to synthetic spice_basic.sp fixture."""
    return os.path.join(fixtures_synthetic_dir, "spice_basic.sp")


@pytest.fixture
def synthetic_cdl_basic_cdl(fixtures_synthetic_dir):
    """Path to synthetic cdl_basic.cdl fixture."""
    return os.path.join(fixtures_synthetic_dir, "cdl_basic.cdl")


@pytest.fixture
def synthetic_spectre_basic_scs(fixtures_synthetic_dir):
    """Path to synthetic spectre_basic.scs fixture."""
    return os.path.join(fixtures_synthetic_dir, "spectre_basic.scs")


@pytest.fixture
def synthetic_nested_generate_v(fixtures_synthetic_dir):
    """Path to synthetic nested_generate.v fixture (2-level nested generate-for)."""
    return os.path.join(fixtures_synthetic_dir, "nested_generate.v")


@pytest.fixture
def fixtures_vendored_dir():
    """Return path to vendored fixtures directory."""
    return os.path.join(os.path.dirname(__file__), "fixtures", "vendored")


@pytest.fixture
def vendored_picorv32_v(fixtures_vendored_dir):
    """Path to vendored picorv32.v fixture."""
    return os.path.join(fixtures_vendored_dir, "picorv32.v")
