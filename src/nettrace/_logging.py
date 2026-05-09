"""Logging configuration for the nettrace package."""

import logging


def get_logger(name: str) -> logging.Logger:
    """Get a logger for a module.

    Args:
        name: Logger name, typically __name__ of the calling module.

    Returns:
        logging.Logger instance with NullHandler configured at the package root.

    Notes:
        Does NOT install handlers or set level. Handler configuration is the
        application's responsibility; the library only emits log records.
    """
    logger = logging.getLogger(name)

    # Attach NullHandler at the package root to prevent 'no handlers' warnings.
    root_logger = logging.getLogger("nettrace")
    if not root_logger.handlers:
        root_logger.addHandler(logging.NullHandler())

    return logger
