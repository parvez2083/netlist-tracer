# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Initial public extraction of the netlist parser and bidirectional tracer.
- Multi-format support: CDL, SPICE, Spectre, Verilog/SystemVerilog with automatic format detection.
- Bidirectional hierarchical signal tracing (`BidirectionalTracer`) with per-bit alias resolution.
- CLI commands: `nettrace` (trace signals) and `netparse` (build JSON cache).
- Parameter specialization: expand parameterized instances with mangled cell variants.
- Concat-form per-bit decomposition for multi-bit vector assignment tracking.
- Supply-net and constant-tie detection for connectivity safety.
- Backward-compat shims at repo root for `netlist_parser` and `netlist_tracer` imports (emit DeprecationWarning).
- Custom exception hierarchy: `NetlistError`, `NetlistParseError`, `TraceError`.
- JSON cache fast-path: serialize and reload parsed netlists without re-parsing.
- Test suite with 30 tests covering synthetic fixtures and real-world netlists (picorv32, sky130).
- Byte-identical behavior preservation: regression tests against vendored picorv32 and sky130 baselines.
- Type hints on public API; `mypy --strict` clean (permissive carve-out for SystemVerilog elaboration helpers).
- Ruff linting and formatting; 0 issues on final pass.
- Examples: `01_parse_and_inspect.py`, `02_trace_signal.py`, `03_build_and_load_cache.py`.
- Comprehensive README with feature highlights, quickstart, CLI reference, and library API tour.
- CONTRIBUTING.md guide for development setup, testing, and style.
- LICENSE file (MIT) with copyright 2026 Parvez Ahmmed.

### Fixed

- Verilog parser: alias pairs from `assign` statements inside `generate-for` blocks are now expanded per-iteration with concrete indices (e.g. `out[0]->in[0]`) instead of the literal loop-variable form (`out[i]->in[i]`). This mirrors the loop-variable expansion already performed for instance extraction. Vendored picorv32 baseline is unaffected (does not contain `generate-for` blocks with assigns).
