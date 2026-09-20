"""Strict serialization, identifiers, and public errors."""

import hashlib
import json
import math
import re
import uuid
from datetime import datetime, timezone
from numbers import Real


class StantonError(ValueError):
    def __init__(self, message, code="invalid_input"):
        super().__init__(message)
        self.code = code


def require(condition, message, code="invalid_input"):
    if not condition:
        raise StantonError(message, code)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def identifier(prefix):
    return prefix + "_" + uuid.uuid4().hex


def name(value):
    require(isinstance(value, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", value),
            "Names must start with a letter and contain only letters, digits, and underscores.")
    require(value not in {"abs", "sqrt", "log", "exp", "minimum", "maximum"},
            "Name is reserved for an expression function.")
    return value


def nonblank(value, label):
    require(isinstance(value, str) and bool(value.strip()), f"{label} must not be blank.")
    return value.strip()


def finite(value, label="Value"):
    require(isinstance(value, Real) and not isinstance(value, bool) and math.isfinite(value), f"{label} must be a finite number.")
    return float(value)


def read_json(path):
    import sys
    from pathlib import Path

    def reject(value):
        raise StantonError(f"Nonfinite JSON constant: {value}")

    return json.loads(sys.stdin.read() if str(path) == "-" else Path(path).read_text(),
                      parse_constant=reject)
