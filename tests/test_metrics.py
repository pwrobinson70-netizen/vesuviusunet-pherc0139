import math

import numpy as np
import pytest

from vesuvius_unet.metrics import binary_metrics, fbeta


def test_fbeta_zero_when_both_zero():
    assert fbeta(0.0, 0.0) == 0.0


def test_fbeta_equal_pr_returns_same_value():
    assert fbeta(0.6, 0.6) == pytest.approx(0.6)
    assert fbeta(0.6, 0.6, beta=2.0) == pytest.approx(0.6)


def test_fbeta_beta1_is_harmonic_mean():
    assert fbeta(0.5, 1.0, beta=1.0) == pytest.approx(2 * 0.5 * 1.0 / 1.5)


def test_fbeta_half_weights_precision_more_than_recall():
    assert fbeta(0.9, 0.3, beta=0.5) > fbeta(0.3, 0.9, beta=0.5)


def test_fbeta_known_value():
    # (1+0.25)*0.8*0.4 / (0.25*0.8 + 0.4) = 0.4 / 0.6
    assert fbeta(0.8, 0.4) == pytest.approx(0.4 / 0.6)


def test_binary_metrics_perfect():
    t = np.array([0, 0, 1, 1], dtype=float)
    p = np.array([0.1, 0.2, 0.8, 0.9])
    m = binary_metrics(p, t)
    assert m["precision"] == 1.0
    assert m["recall"] == 1.0
    assert m["f05"] == pytest.approx(1.0)
    assert m["auc"] == pytest.approx(1.0)


def test_binary_metrics_counts():
    # tp=2, fp=1, fn=1
    t = np.array([1, 1, 1, 0, 0, 0], dtype=float)
    p = np.array([0.9, 0.8, 0.1, 0.7, 0.2, 0.1])
    m = binary_metrics(p, t)
    assert m["precision"] == pytest.approx(2 / 3)
    assert m["recall"] == pytest.approx(2 / 3)
    assert m["f05"] == pytest.approx(2 / 3)


def test_binary_metrics_threshold_is_inclusive():
    t = np.array([1.0, 0.0])
    p = np.array([0.5, 0.5])
    m = binary_metrics(p, t, threshold=0.5)
    assert m["precision"] == pytest.approx(0.5)
    assert m["recall"] == 1.0
    m = binary_metrics(p, t, threshold=0.51)
    assert m["precision"] == 0.0 and m["recall"] == 0.0 and m["f05"] == 0.0


def test_binary_metrics_no_predicted_positives():
    t = np.array([1.0, 0.0, 1.0])
    p = np.array([0.1, 0.1, 0.1])
    m = binary_metrics(p, t)
    assert m["precision"] == 0.0
    assert m["recall"] == 0.0
    assert m["f05"] == 0.0


def test_binary_metrics_no_positive_targets():
    t = np.zeros(4)
    p = np.array([0.9, 0.1, 0.2, 0.3])
    m = binary_metrics(p, t)
    assert m["recall"] == 0.0
    assert m["precision"] == 0.0
    assert math.isnan(m["auc"])


def test_binary_metrics_auc_inverted_is_zero():
    t = np.array([0.0, 0.0, 1.0, 1.0])
    p = np.array([0.9, 0.8, 0.2, 0.1])
    assert binary_metrics(p, t)["auc"] == pytest.approx(0.0)


def test_binary_metrics_random_synthetic_in_range():
    rng = np.random.default_rng(0)
    t = (rng.random(2000) < 0.3).astype(float)
    p = np.clip(t * 0.3 + rng.random(2000) * 0.7, 0, 1)
    m = binary_metrics(p, t)
    for k in ("precision", "recall", "f05", "auc"):
        assert 0.0 <= m[k] <= 1.0
    assert m["auc"] > 0.5
