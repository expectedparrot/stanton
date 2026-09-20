"""A local workbench for numerical estimates with provenance."""

from .common import StantonError
from .distributions import Distribution
from .session import Session

__version__ = "0.6.1"
__all__ = ["Distribution", "Session", "StantonError", "__version__"]
