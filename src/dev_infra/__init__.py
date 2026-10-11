"""One controller for a shared Docker backend."""

from pathlib import Path

__version__ = "0.3.0"
ROOT = Path(__file__).resolve().parents[2]


class InfraError(ValueError):
    """A configuration or operational error suitable for CLI presentation."""
