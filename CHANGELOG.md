# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- **Renamed package from `nettrace` to `netlist-tracer` (PyPI) / `netlist_tracer` (Python module).** CLI commands renamed: `nettrace` → `netlist-tracer`, `netparse` → `netlist-parser`. Compat shims at repo root removed. **Breaking change.**
- **`-pin` accepts bare bus base names** as shorthand for all indexed members. `-pin mem_addr` is now equivalent to `-pin mem_addr[0],mem_addr[1],...,mem_addr[N]` and produces one trace section per bit. Library: same behavior in `BidirectionalTracer.trace_pins(pins=['mem_addr'])` via the new `expand_pin()` helper. Unknown pin names still error with exit 1.

### Removed

- Backward-compat shims `netlist_parser.py` / `netlist_tracer.py` at repo root (no longer needed since module name is now `netlist_tracer`).
- `tests/test_compat_shim.py` (compat shim tests removed).

### Added

- Initial public extraction of the netlist parser and bidirectional tracer.
- Multi-format support: CDL, SPICE, Spectre, Verilog/SystemVerilog with automatic format detection.
- Bidirectional hierarchical signal tracing (`BidirectionalTracer`) with per-bit alias resolution.
- CLI commands: `netlist-tracer` (trace signals) and `netlist-parser` (build JSON cache).
- Parameter specialization: expand parameterized instances with mangled cell variants.
- Concat-form per-bit decomposition for multi-bit vector assignment tracking.
- Supply-net and constant-tie detection for connectivity safety.
- Custom exception hierarchy: `NetlistError`, `NetlistParseError`, `TraceError`.
- JSON cache fast-path: serialize and reload parsed netlists without re-parsing.
- Test suite with 28 tests covering synthetic fixtures and real-world netlists (picorv32, sky130).
- Byte-identical behavior preservation: regression tests against vendored picorv32 and sky130 baselines.
- Type hints on public API; `mypy --strict` clean (permissive carve-out for SystemVerilog elaboration helpers).
- Ruff linting and formatting; 0 issues on final pass.
- Examples: `01_parse_and_inspect.py`, `02_trace_signal.py`, `03_build_and_load_cache.py`.
- Comprehensive README with feature highlights, quickstart, CLI reference, and library API tour.
- CONTRIBUTING.md guide for development setup, testing, and style.
- LICENSE file (MIT) with copyright 2026 Parvez Ahmmed.

### Fixed

- Verilog parser: alias pairs from `assign` statements inside `generate-for` blocks are now expanded per-iteration with concrete indices (e.g. `out[0]->in[0]`) instead of the literal loop-variable form (`out[i]->in[i]`). This mirrors the loop-variable expansion already performed for instance extraction. Vendored picorv32 baseline is unaffected (does not contain `generate-for` blocks with assigns).
