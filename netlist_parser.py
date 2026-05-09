#!/usr/bin/env python3
"""DEPRECATED: netlist_parser module has been moved to the nettrace package.

This shim provides backward compatibility. All functionality is now in:
    from nettrace import NetlistParser, SubcktDef, Instance, merge_aliases_into_subckt

New code should import from nettrace directly.
"""

import warnings

# Issue deprecation warning on import
warnings.warn(
    "netlist_parser is deprecated; use 'from nettrace import ...' instead",
    DeprecationWarning,
    stacklevel=2,
)

# Re-export from nettrace for compatibility
from nettrace import (  # noqa: E402
    Instance,
    NetlistParser,
    SubcktDef,
    merge_aliases_into_subckt,
)

__all__ = [
    "NetlistParser",
    "SubcktDef",
    "Instance",
    "merge_aliases_into_subckt",
]
