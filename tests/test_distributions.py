import numpy as np
import pytest

from stanton import Distribution, StantonError


@pytest.mark.parametrize("shape,low,high", [("normal", -5, 8), ("lognormal", 2, 20), ("logitnormal", .1, .7)])
def test_interval_is_equal_tailed(shape, low, high):
    dist = Distribution.from_interval(low, high, .8, shape)
    assert np.allclose(dist.ppf([.1, .9]), [low, high])
    assert Distribution.from_dict(dist.to_dict()) == dist
    samples = dist.sample(np.random.default_rng(19), 100000)
    assert np.mean((samples >= low) & (samples <= high)) == pytest.approx(.8, abs=.004)


def test_empirical_is_resampling_and_quantile_tails_are_bounded():
    empirical = Distribution.from_samples([1, 1, 10])
    assert empirical.ppf([0, .4, .8, 1]).tolist() == [1, 1, 10, 10]
    quantiles = Distribution.from_quantiles({.1: 10, .5: 20, .9: 40})
    assert quantiles.ppf([0, .1, .3, .5, .9, 1]).tolist() == [10, 10, 15, 20, 40, 40]
    assert Distribution.from_dict(quantiles.to_dict()) == quantiles


@pytest.mark.parametrize("low,high,p,shape", [(1, 1, .8, "normal"), (0, 2, .8, "lognormal"),
    (-1, 2, .8, "logitnormal"), (1, 2, 1, "normal"), (1, float('inf'), .8, "normal")])
def test_invalid_distribution_inputs(low, high, p, shape):
    with pytest.raises(StantonError):
        Distribution.from_interval(low, high, p, shape)
