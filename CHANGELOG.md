# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.3.0] - 2026-05-10

### Added

- EDIF 2.0.0 and 3.0/4.0 parser with s-expression parsing, MSB-first bus expansion, and hierarchical cell/instance/net resolution.
- Recursive include-statement support for SPICE/CDL (`.include`, `.inc`, `.lib` directives) and Spectre (`include` and `simulator lang=spice` blocks) with cycle detection, tilde expansion, and absolute path support.
- New `-I <dir>` / `--include-path <dir>` CLI flag (repeatable on both `netlist-tracer` and `netlist-parser` commands); new `include_paths=[...]` library API kwarg on `NetlistParser.__init__()`.
- Vendored test fixtures: 3 EDIF designs from SpyDrNet (BSD-3 licensed) and 1 NGSpice analog SPICE example with include directives (GPL-2.0-or-later, separate work).
- Comprehensive test suite: EDIF parser and tracer regression tests with byte-identical golden baselines, NGSpice SPICE regression tests, cache roundtrip parity across all 3 formats, and 12+ include-statement tests covering cycle detection, search-path resolution, and Spectre-specific cases.
- CLI auto-detection for `.edif` and `.edn` file extensions.
- "Did you mean" suggestions extended to EDIF parser cell and pin lookup errors.
- SPICE/CDL flat-deck top synthesis: testbench files with instance lines at file scope (no enclosing `.subckt`) now have a synthetic top-level cell auto-generated with the name `__<filename_stem>__`, making those instances visible to the tracer. This enables UP-walk traces to surface sibling instances and shared nets at the testbench level. Hierarchical netlists with explicit `.subckt` wrappers are unaffected. Primitive devices (R, C, V, M) at file scope remain out of scope for hierarchy traversal.

### Changed

- `NetlistParser.__init__()` now accepts optional `include_paths: list[str] | None = None` kwarg for include search directories (backward-compatible).
- SPICE and Spectre parsers no longer raise on multi-file inputs when includes are involved; included files are inlined transparently.
- Spectre flat-deck top-level synthesis now uses the `__<filename_stem>__` naming convention to match SPICE behavior and reduce collision risk with real cell names. Previously, the synthetic top used the bare filename stem.
- JSON cache schema remains v2 (no migration required for existing caches).

### Fixed

- Include cycle detection now correctly distinguishes cycles from diamond-shaped dependencies.
- Ruff UP007 rule suppressed for Python 3.9 compatibility (Union[X, Y] syntax).

## [0.2.0] - 2026-05-09

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
- JSON cache schema versioning. Loaders accept v0 (legacy, no field), v1 (aliases as list of pairs, indented), and v2 (aliases as dict, compact encoding) and raise `NetlistParseError` for unknown future versions. Existing caches load without modification.
- JSON cache write is now ~2-3× faster on large designs and produces ~25% smaller files (compact encoding, dict-form aliases, removed redundant defensive list copies). Sample workload (1,728-module SystemVerilog cache): write 1.8 s → 0.6 s, file 36 MB → 27 MB.
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
