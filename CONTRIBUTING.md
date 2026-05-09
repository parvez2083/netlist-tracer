# Contributing to nettrace

## Development Setup

### Install dev dependencies

```bash
cd /path/to/netlistTracer
pip install -e '.[dev]'
```

This installs the package in editable mode plus `pytest`, `ruff`, and `mypy`.

## Testing

### Run all tests

```bash
pytest
```

Expected output: **30 passed** (all tests pass in ~0.4 seconds).

### Run fast tests only

```bash
pytest -m "not slow"
```

Skips regression tests (`test_*_regression.py`) for quick iteration.

### Run a specific test file

```bash
pytest tests/test_parser_verilog.py -v
```

## Linting and Formatting

### Check for style issues

```bash
ruff check .
```

Expected: **All checks passed!**

### Auto-fix formatting

```bash
ruff format .
```

Then verify no new issues:

```bash
ruff check .
```

## Type Checking

### Check type hints

```bash
mypy src/
```

Expected: **Success: no issues found in 13 source files**

The configuration enforces `--strict` on public API modules. The SystemVerilog elaboration helpers (`parsers/verilog/*`) have a permissive carve-out to allow dynamic argument handling.

## Code Style

### Naming Conventions

- **Functions / Methods**: `snake_case` — `parse_spice()`, `trace_signal()`
- **Classes**: `PascalCase` — `NetlistParser`, `BidirectionalTracer`
- **Constants**: `UPPER_SNAKE_CASE` — `_RE_MODULE`, `_KEYWORDS`
- **Private methods**: prefix with `_` — `_parse_verilog()`, `_add_instance()`

### Type Hints

- Public API: full type hints required
- Internal helpers: type hints encouraged
- Dataclasses: all fields must have type annotations

### Imports

- Standard library first, then third-party, then local
- Use absolute imports within the package
- Group imports with blank lines: stdlib, third-party, local

## Adding New Tests

### Synthetic fixtures

Add minimal test cases under `tests/fixtures/synthetic/`:

- `concat_alias.v` — SystemVerilog concat alias expansion
- `generate_loop.v` — Verilog generate block elaboration
- `param_specialize.v` — Parameter specialization
- `supply_constant.cdl` — Supply net and constant-tie detection
- `spice_basic.sp`, `cdl_basic.cdl`, `spectre_basic.scs` — Format basics

### Test modules

Follow naming: `test_parser_<format>.py` for parser tests, `test_tracer.py` for tracer.

Example:

```python
import pytest
from nettrace import NetlistParser

def test_parse_spice_basic():
    parser = NetlistParser("tests/fixtures/synthetic/spice_basic.sp")
    assert parser.format == "spice"
    assert len(parser.subckts) > 0
```

### Regression tests

Mark slow tests with `@pytest.mark.slow`:

```python
@pytest.mark.slow
def test_picorv32_regression():
    ...
```

Run only regression tests:

```bash
pytest -m slow
```

## Debugging

### Enable verbose output

```bash
pytest -vv
```

### Show print statements

```bash
pytest -s
```

### Drop into pdb on failure

```bash
pytest --pdb
```

## Pre-commit (Optional)

If using pre-commit hooks, configure `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.4.2
    hooks:
      - id: ruff
      - id: ruff-format
```

Then:

```bash
pre-commit install
pre-commit run --all-files
```

## Architecture Notes

### Module Layout

```
src/nettrace/
├── __init__.py           # Public API re-exports
├── model.py              # SubcktDef, Instance, merge_aliases_into_subckt
├── parser.py             # NetlistParser orchestrator
├── tracer.py             # BidirectionalTracer, TraceStep, format_path
├── exceptions.py         # Custom exception hierarchy
├── _logging.py           # Logging factory
├── cli/
│   ├── trace.py          # nettrace CLI
│   └── parse.py          # netparse CLI
└── parsers/
    ├── detect.py         # Format auto-detection
    ├── spice.py          # SPICE/CDL parser
    ├── spectre.py        # Spectre parser
    └── verilog/          # SV elaboration (5 modules)
        ├── preprocess.py
        ├── structure.py
        ├── instances.py
        ├── specialize.py
        └── orchestrate.py
```

### Key Abstractions

- **SubcktDef**: cell definition with pins, aliases (union-find), and child indices
- **Instance**: instantiation record with name, cell_type, nets, params
- **TraceStep**: one hop in a path (cell, pin/net, direction, hierarchy stack)
- **BidirectionalTracer**: DFS-based path finder resolving aliases at each step

## Questions?

Refer to the README for feature documentation, or inspect the test suite for usage patterns.
