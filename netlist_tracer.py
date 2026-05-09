#!/usr/bin/env python3
"""DEPRECATED: netlist_tracer module has been moved to the nettrace package.

This shim provides backward compatibility. All functionality is now in:
    from nettrace import BidirectionalTracer, TraceStep, format_path
    from nettrace.cli.trace import main

New code should import from nettrace directly.
"""

import sys
import warnings

# Issue deprecation warning on import
warnings.warn(
    "netlist_tracer is deprecated; use 'from nettrace import ...' instead",
    DeprecationWarning,
    stacklevel=2,
)

# Re-export from nettrace for compatibility
from nettrace import BidirectionalTracer, TraceStep, format_path  # noqa: E402
from nettrace.cli.trace import main  # noqa: E402

__all__ = [
    "BidirectionalTracer",
    "TraceStep",
    "format_path",
    "main",
]

if __name__ == "__main__":
    print(
        "DeprecationWarning: netlist_tracer.py is a backward-compat shim; "
        "use the installed 'nettrace' command instead.",
        file=sys.stderr,
    )
    sys.exit(main())
