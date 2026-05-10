from __future__ import annotations

import re


def detect_format(filepaths: list[str]) -> str:
    """Detect netlist format from file content syntax.

    Distinguishing markers:
    - EDIF:     '(edif ' prefix or .edif/.edn/.edf extension
    - Verilog:  'module <name>' keyword
    - Spectre:  'subckt <name>' (no dot) or 'simulator lang=spectre'
    - CDL:      '*.PININFO' comment lines (auCdl-specific)
    - SPICE:    '.subckt/.ends' without CDL markers

    Args:
        filepaths: List of file paths to scan for format markers.

    Returns:
        Format string: 'edif', 'verilog', 'spectre', 'cdl', or 'spice'.
    """
    has_dotsubckt = False
    has_pininfo = False

    for filepath in filepaths:
        # Fast path: check extension
        if filepath.lower().endswith((".edif", ".edn", ".edf")):
            return "edif"

        with open(filepath) as f:
            # Check first 4 KB for EDIF marker
            content_start = f.read(4096)
            if re.search(r"\(edif\s", content_start, re.IGNORECASE):
                return "edif"
            f.seek(0)

            for line in f:
                stripped = line.strip()
                if not stripped:
                    continue

                # Verilog: 'module <name>'
                if re.match(r"^module\s+\w+", stripped):
                    return "verilog"

                # Spectre: 'simulator lang=spectre' or bare 'subckt' (no dot)
                if stripped.startswith("simulator lang=spectre"):
                    return "spectre"
                if re.match(r"^subckt\s", stripped):
                    return "spectre"

                # CDL marker: *.PININFO is auCdl-specific, never in HSPICE
                if stripped.startswith("*.PININFO"):
                    has_pininfo = True

                # SPICE-family: .SUBCKT present
                if re.match(r"^\.subckt\s", stripped, re.IGNORECASE):
                    has_dotsubckt = True

                # Early exit once we have enough info
                if has_dotsubckt and has_pininfo:
                    return "cdl"

    if has_dotsubckt:
        return "cdl" if has_pininfo else "spice"

    return "spice"
