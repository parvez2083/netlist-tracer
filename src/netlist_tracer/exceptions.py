"""Exception hierarchy for the netlist_tracer package."""


class NetlistError(Exception):
    """Base exception for all netlist_tracer errors."""

    pass


class NetlistParseError(NetlistError):
    """Raised when a netlist file cannot be parsed."""

    pass


class IncludePathNotFoundError(NetlistParseError):
    """Raised when an include path cannot be resolved (subclass of NetlistParseError).

    Used by try-and-degrade logic to distinguish unresolvable paths from other
    parse errors (e.g. cycle detection, which must propagate).
    """

    pass


class TraceError(NetlistError):
    """Reserved for future strict=True mode in the tracer.

    Currently defined but not raised in v0.1.
    """

    pass
