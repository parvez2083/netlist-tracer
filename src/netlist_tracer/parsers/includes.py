"""Shared include-file expansion and path resolution for SPICE/Spectre dialects."""

from __future__ import annotations

import os
import re
from typing import Optional, Union

from netlist_tracer._logging import get_logger
from netlist_tracer.exceptions import NetlistParseError

_logger = get_logger(__name__)


def expand_includes(
    top_file: str, dialect: str, include_paths: Optional[list[str]] = None
) -> list[tuple[str, str, int]]:
    """Recursively expand include statements and return flattened line stream.

    Args:
        top_file: Absolute path to the top netlist file.
        dialect: 'spice' (handles .include/.inc/.lib) or 'spectre'.
        include_paths: Optional list of additional search directories.

    Returns:
        List of (line_text, source_file_path, source_line_no) tuples with
        provenance preserved for error reporting.

    Raises:
        NetlistParseError: On cycle detection or unresolvable path.
    """
    if include_paths is None:
        include_paths = []

    expanded_lines: list[tuple[str, str, int]] = []
    include_stack: list[str] = []

    def _expand_recursive(
        filename: str, include_stack: list[str], current_lang: str = "spice"
    ) -> None:
        """Recursively expand a file, tracking include stack for cycle detection."""
        abs_path = os.path.abspath(filename)

        if abs_path in include_stack:
            chain_str = " -> ".join(include_stack + [abs_path])
            raise NetlistParseError(
                f"Include cycle detected: {chain_str} (cycle closes at {abs_path})"
            )

        include_stack.append(abs_path)

        try:
            with open(abs_path) as f:
                lines = f.readlines()
        except FileNotFoundError as e:
            raise NetlistParseError(f"Include file not found: {abs_path}") from e

        line_no = 1
        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()

            # Track language mode for Spectre
            if dialect == "spectre" and stripped.startswith("simulator lang="):
                if "spice" in stripped.lower():
                    current_lang = "spice"
                elif "spectre" in stripped.lower():
                    current_lang = "spectre"

            # Parse include directives based on current language
            include_info: Union[tuple[str, str], str, None] = None
            if dialect == "spectre" and current_lang == "spectre":
                include_info = _parse_spectre_include_directive(stripped)
            elif dialect in ("spice", "spectre") and current_lang == "spice":
                include_info = _parse_spice_include_directive(stripped)

            if include_info:
                raw_path: str
                if dialect == "spice" or (dialect == "spectre" and current_lang == "spice"):
                    if isinstance(include_info, tuple):
                        raw_path, libname = include_info
                        if libname:
                            _logger.warning(
                                f"Skipping .lib '{raw_path}' libname '{libname}' at "
                                f"{abs_path}:{line_no} — lib-section semantics unsupported"
                            )
                            line_no += 1
                            i += 1
                            continue
                    else:
                        raw_path = include_info
                else:
                    raw_path = include_info  # type: ignore[assignment]

                try:
                    resolved_path = _resolve_include_path(raw_path, abs_path, include_paths)
                except NetlistParseError:
                    raise

                _logger.info(f"Including: {resolved_path} (from {abs_path}:{line_no})")
                _expand_recursive(resolved_path, include_stack, current_lang)
            else:
                # Regular line — add to output with provenance
                expanded_lines.append((line.rstrip("\n\r"), abs_path, line_no))

            line_no += 1
            i += 1

        include_stack.pop()

    _expand_recursive(top_file, include_stack, current_lang=dialect)
    return expanded_lines


def _resolve_include_path(raw_path: str, including_file: str, include_paths: list[str]) -> str:
    """Resolve include path using tilde expansion and search paths.

    Args:
        raw_path: Raw include path from directive.
        including_file: Absolute path of the file doing the including.
        include_paths: List of additional search directories.

    Returns:
        Absolute resolved path.

    Raises:
        NetlistParseError: If path cannot be resolved.
    """
    # Guard against empty or whitespace-only paths
    if not raw_path or not raw_path.strip():
        raise NetlistParseError(f"Empty include path at {including_file}")

    # Tilde expansion
    expanded = os.path.expanduser(raw_path)

    # Absolute path — use as-is
    if os.path.isabs(expanded):
        if os.path.isfile(expanded):
            return expanded
        else:
            search_list = [expanded]
            raise NetlistParseError(
                f"Include path not found: {raw_path}\nSearched: {', '.join(search_list)}"
            )

    # Search relative to including file's directory
    includer_dir = os.path.dirname(including_file)
    candidate = os.path.join(includer_dir, expanded)
    if os.path.isfile(candidate):
        return os.path.abspath(candidate)

    # Search user-provided include paths
    search_list_items: list[str] = [candidate]
    for search_dir in include_paths:
        candidate = os.path.join(search_dir, expanded)
        if os.path.isfile(candidate):
            return os.path.abspath(candidate)
        search_list_items.append(candidate)

    raise NetlistParseError(
        f"Include path not found: {raw_path}\nSearched: {', '.join(search_list_items)}"
    )


def _parse_spice_include_directive(line: str) -> Optional[tuple[str, str] | str]:
    """Match SPICE include directive. Return (path, libname) for .lib, path for .include/.inc.

    Args:
        line: Stripped line text.

    Returns:
        (path, libname) tuple for .lib, path string for .include/.inc, or None.
    """
    # .include "path" or .include 'path' or .include path
    match = re.match(r"^\.include\s+['\"]?([^'\"]+)['\"]?\s*$", line, re.IGNORECASE)
    if match:
        path = match.group(1).strip()
        return path

    # .inc "path" or .inc 'path' or .inc path (alias for .include)
    match = re.match(r"^\.inc\s+['\"]?([^'\"]+)['\"]?\s*$", line, re.IGNORECASE)
    if match:
        path = match.group(1).strip()
        return path

    # .lib "path" libname or .lib path libname
    match = re.match(r"^\.lib\s+['\"]?([^'\"]+)['\"]?\s+(\S+)\s*$", line, re.IGNORECASE)
    if match:
        path = match.group(1).strip()
        libname = match.group(2).strip()
        return (path, libname)

    # .lib "path" (no libname — include entire file)
    match = re.match(r"^\.lib\s+['\"]?([^'\"]+)['\"]?\s*$", line, re.IGNORECASE)
    if match:
        path = match.group(1).strip()
        return (path, "")

    return None


def _parse_spectre_include_directive(line: str) -> Optional[str]:
    """Match Spectre include directive. Return path or None.

    Args:
        line: Stripped line text (case-sensitive).

    Returns:
        Path string or None.
    """
    # Spectre: include "path" (case-sensitive, quotes required per spec)
    match = re.match(r'^include\s+"([^"]+)"\s*$', line)
    if match:
        return match.group(1)

    return None
