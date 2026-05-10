# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Multi-format netlist parsing with automatic format detection: CDL, SPICE, Spectre, Verilog, SystemVerilog.
- Bidirectional hierarchical signal tracing (`BidirectionalTracer`) with per-bit alias resolution.
- Two CLI commands:
  - `netlist-tracer` — trace signals through a netlist (file, directory, or JSON cache).
  - `netlist-parser` — parse a netlist and dump it to a JSON cache for fast re-loads.
- `BidirectionalTracer.trace_pins(start_name, pins=None, target_name=None, max_depth=None)` library API. Returns `{pin_name: [paths]}`. When `pins=None`, traces every bit-level pin of the cell.
- `expand_pin(subckt, name)` helper: returns `[name]` for an exact pin, all indexed members for a bare bus base name, or `[]` for an unknown name.
- `-pin` CLI flag accepts:
  - exact bit-level names (`-pin clk` or `-pin data[3]`)
  - comma-separated lists (`-pin clk,resetn`)
  - repeated flags (`-pin clk -pin resetn`)
  - bare bus base names (`-pin mem_addr` expands to all `mem_addr[0..N]` bits as separate output sections)
  - omitted entirely (traces every bit-level pin of the cell)
- `-trace_format json` produces machine-readable output. Schema:
  ```
  {tool, version, netlist, cell, target, max_depth,
   pins: {name: {paths: [{formatted, steps: [{cell, pin_or_net, direction, instance_name, inst_stack}]}]}}}
  ```
  Info-level logs are suppressed in this mode so stdout is pure JSON.
- JSON cache schema versioning: caches now carry `"schema_version": 1`. Loaders treat missing fields as legacy v0 (still supported) and raise `NetlistParseError` for newer-than-supported versions. Existing caches load without modification.
- Nested `generate-for` blocks: alias unrolling now iterates to fixed-point (max depth 8) so loop variables are correctly substituted in 2-level nested blocks.
- Custom exception hierarchy: `NetlistError`, `NetlistParseError`, `TraceError`.
- `"Did you mean: [...]"` suggestion list when a pin or cell name is not found, including bare-bus-name suggestions when an indexed bus exists.
- Parameter specialization for parameterized modules (mangled cell variants).
- Concat-form per-bit decomposition for multi-bit vector assignments.
- Supply-net and constant-tie detection.
- Test suite with 40 always-on tests plus 4 optional local-cache smoke tests gated by the `NETLIST_TRACER_LOCAL_CACHE` environment variable.
- Regression baselines for the vendored picorv32 fixture (ISC) and sky130 inverter fixture (Apache-2.0) covering both parser output and CLI output.
- Type hints on the public API; mypy strict on public modules with a permissive override for the SystemVerilog elaboration helpers.
- Ruff lint + format configuration; clean on initial release.
- GitHub Actions CI on push and PR: matrix lint + test on Python 3.9, 3.10, 3.11, 3.12, 3.13.
- PyPI release workflow that triggers on `v*` tag push. Supports trusted publishing (preferred) or `PYPI_API_TOKEN` fallback. The workflow is in place but does not run until a tag is pushed and PyPI publishing is configured.
- Issue and pull-request templates plus a `CODEOWNERS` file under `.github/`.
- README badges: CI status, license, supported Python versions, last commit.
- Four runnable example scripts under `examples/` covering parse + inspect, single-signal trace, JSON cache build/reload, and multi-pin tracing with bus expansion.
- README, CONTRIBUTING, LICENSE (MIT), and `.gitattributes`.

### Changed

- Error and warning messages use `ERROR:` / `WARNING:` (all caps) prefix and route to `stderr` so JSON output remains parseable when piped.
- The CLI exits with status 1 on resolution failure (bad cell, bad pin, bus name with no members) instead of 0 with a misleading "no paths found" message.
- Multi-pin output section headers display the deduplicated path count.
- `python_version = "3.10"` in mypy config (mypy 2.0+ requires 3.10+ as a target). The project still runs on Python 3.9 at runtime — every annotation file uses `from __future__ import annotations`, and the CI matrix runs the full test suite on 3.9.
- Suppressed ruff `UP045` (the `Optional[X]` → `X | None` suggestion) since the project supports Python 3.9, where the pipe syntax is invalid as a runtime annotation.

### Fixed

- Verilog parser: `assign` statements inside `generate-for` blocks now produce one alias per loop iteration with concrete integer indices (e.g. `out[0] -> in[0]`, `out[1] -> in[1]`), rather than a single literal-`i` alias (`out[i] -> in[i]`). The loop variable substitution now runs before alias extraction, mirroring what was already done for instance extraction.
