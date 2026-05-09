"""Exception hierarchy for the netlist_tracer package."""


class NetlistError(Exception):
    """Base exception for all netlist_tracer errors."""

    pass


class NetlistParseError(NetlistError):
    """Raised when a netlist file cannot be parsed."""

    pass


class TraceError(NetlistError):
    """Reserved for future strict=True mode in the tracer.

    Currently defined but not raised in v0.1.
    """

    pass
