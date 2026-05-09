# Vendored Third-Party Fixtures

The files in this directory are **verbatim third-party netlists** vendored
into this repository for use as regression-test inputs. They are NOT part of
the `netlist-tracer` package and are NOT redistributed under the
`netlist-tracer` MIT license. Each file retains its upstream license; this
NOTICE.md records the provenance and license obligations.

The `netlist-tracer` project (MIT-licensed) does not modify these files and does
not assert any rights over them. Removing or modifying any vendored file's
embedded copyright/license header is prohibited.

---

## picorv32.v

- **Source**: https://github.com/cliffordwolf/picorv32 (now redirects to
  https://github.com/YosysHQ/picorv32)
- **Upstream path**: `/picorv32.v`
- **Branch**: `main`
- **Commit SHA at vendor time**: `87c89acc18994c8cf9a2311e871818e87d304568`
- **Vendored on**: 2026-05-09
- **License**: ISC (see embedded header in `picorv32.v`)
- **Copyright**: Copyright (C) 2015 Claire Xenia Wolf <claire@yosyshq.com>
- **MIT compatibility**: ISC is permissive and MIT-compatible; vendoring with
  attribution preserved is sufficient.

## sky130_fd_sc_hd__inv_1.spice

- **Source**: https://github.com/google/skywater-pdk-libs-sky130_fd_sc_hd
- **Upstream path**: `/cells/inv/sky130_fd_sc_hd__inv_1.spice`
- **Branch**: `main`
- **Commit SHA at vendor time**: `ac7fb61f06e6470b94e8afdf7c25268f62fbd7b1`
- **Vendored on**: 2026-05-09
- **License**: Apache-2.0 (SPDX-License-Identifier in file; full text at
  https://www.apache.org/licenses/LICENSE-2.0)
- **Copyright**: Copyright 2020 The SkyWater PDK Authors
- **MIT compatibility**: Apache-2.0 is one-way compatible with MIT —
  MIT-licensed projects may include Apache-2.0 files provided the upstream
  license header and NOTICE attribution are preserved (which we do here and
  in the file itself). The `netlist-tracer` package proper remains MIT-licensed;
  this single vendored test fixture is Apache-2.0.

---

## Refresh procedure

To refresh either fixture to a newer upstream commit:

1. Download the file from the upstream URL listed above.
2. Update the corresponding `Commit SHA at vendor time` and `Vendored on`
   fields in this NOTICE.md.
3. Re-run the baseline-capture script (see project root or
   `tests/_capture_baseline.py`) to regenerate the matching golden file in
   `../golden/`.
4. Inspect the diff — non-empty deltas indicate either upstream change or
   a parser regression. Investigate before committing.
