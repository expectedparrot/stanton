"""Serializable scalar marginals with explicit interval and empirical-tail semantics."""

import math
from dataclasses import dataclass

import numpy as np
from scipy.special import expit, logit
from scipy.stats import norm

from .common import finite, require


@dataclass(frozen=True)
class Distribution:
    """Immutable specification; finite empirical tails are deliberately bounded."""

    family: str
    parameters: tuple

    def __post_init__(self):
        require(self.family in {"point", "normal", "lognormal", "logitnormal", "empirical", "quantiles"},
                "Unknown distribution family.")
        if self.family == "quantiles":
            rows = tuple((finite(p), finite(v)) for p, v in self.parameters)
            require(len(rows) >= 2 and 0 <= rows[0][0] < rows[-1][0] <= 1 and
                    all(a[0] < b[0] and a[1] <= b[1] for a, b in zip(rows, rows[1:])), "Invalid quantiles.")
            object.__setattr__(self, "parameters", rows)
        else:
            values = tuple(finite(v) for v in self.parameters)
            require(len(values) > 0, "Distribution parameters must not be empty.")
            if self.family == "point":
                require(len(values) == 1, "Point requires one value.")
            elif self.family != "empirical":
                require(len(values) == 2 and values[1] > 0, "Normal families require location and positive scale.")
            else:
                values = tuple(sorted(values))
            object.__setattr__(self, "parameters", values)

    @classmethod
    def from_point(cls, value):
        return cls("point", (finite(value),))

    @classmethod
    def from_interval(cls, low, high, p=0.8, shape="lognormal"):
        low, high, p = finite(low), finite(high), finite(p, "Coverage")
        require(low < high and 0 < p < 1, "Require low < high and 0 < coverage < 1.")
        require(shape in {"normal", "lognormal", "logitnormal"}, "Unsupported interval shape.")
        if shape == "lognormal":
            require(low > 0, "Lognormal interval endpoints must be positive.")
            a, b = math.log(low), math.log(high)
        elif shape == "logitnormal":
            require(0 < low < high < 1, "Logit-normal interval must lie strictly inside (0, 1).")
            a, b = float(logit(low)), float(logit(high))
        else:
            a, b = low, high
        z = norm.ppf((1 + p) / 2)
        require(np.isfinite(z) and z > 0, "Coverage is too close to zero or one.")
        return cls(shape, ((a + b) / 2, (b - a) / (2 * z)))

    @classmethod
    def from_samples(cls, samples):
        values = tuple(sorted(finite(x) for x in samples))
        require(len(values) > 0, "Samples must not be empty.")
        return cls("empirical", values)

    @classmethod
    def from_quantiles(cls, quantiles):
        """Probabilities use [0, 1]; linear inverse CDF, constant endpoint tails."""
        rows = sorted((finite(float(p)), finite(v)) for p, v in quantiles.items())
        require(len(rows) >= 2, "At least two quantiles are required.")
        ps, xs = zip(*rows)
        require(0 <= ps[0] < ps[-1] <= 1 and len(set(ps)) == len(ps), "Invalid quantile probabilities.")
        require(all(a <= b for a, b in zip(xs, xs[1:])), "Quantiles must be nondecreasing.")
        return cls("quantiles", tuple(rows))

    def ppf(self, probabilities):
        u = np.asarray(probabilities, dtype=float)
        require(np.all(np.isfinite(u) & (u >= 0) & (u <= 1)), "Invalid inverse-CDF probabilities.")
        if self.family == "point":
            return np.full_like(u, self.parameters[0])
        if self.family == "empirical":
            indices = np.minimum((u * len(self.parameters)).astype(int), len(self.parameters) - 1)
            return np.asarray(self.parameters)[indices]
        if self.family == "quantiles":
            ps, xs = zip(*self.parameters)
            return np.interp(u, ps, xs)
        mu, sigma = self.parameters
        z = mu + sigma * norm.ppf(u)
        if self.family == "normal":
            return z
        if self.family == "lognormal":
            return np.exp(z)
        return expit(z)

    def sample(self, rng, n):
        # Avoid endpoints of unbounded inverse CDFs.
        u = np.clip(rng.random(n), np.nextafter(0.0, 1.0), np.nextafter(1.0, 0.0))
        return self.ppf(u)

    def to_dict(self):
        return {"family": self.family, "parameters": list(self.parameters)}

    @classmethod
    def from_dict(cls, value):
        require(isinstance(value, dict) and set(value) == {"family", "parameters"},
                "Distribution requires family and parameters.")
        family, params = value["family"], value["parameters"]
        require(isinstance(params, (list, tuple)), "Distribution parameters must be an array.")
        if family == "point":
            require(len(params) == 1, "Point requires one value.")
            return cls.from_point(params[0])
        if family == "empirical":
            return cls.from_samples(params)
        if family == "quantiles":
            require(all(isinstance(row, (list, tuple)) and len(row) == 2 for row in params),
                    "Quantiles require probability/value pairs.")
            require(len({row[0] for row in params}) == len(params), "Duplicate quantile probabilities.")
            return cls.from_quantiles(dict(params))
        require(family in {"normal", "lognormal", "logitnormal"} and len(params) == 2,
                "Unknown distribution family or incorrect parameters.")
        mu, sigma = (finite(v) for v in params)
        require(sigma > 0, "Standard deviation must be positive.")
        return cls(family, (mu, sigma))
