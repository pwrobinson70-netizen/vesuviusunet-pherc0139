"""phantom_e2e scoring helpers (no torch needed: only numpy / sklearn)."""
import numpy as np
import pytest

pytest.importorskip("sklearn")
pytest.importorskip("PIL")
import phantom_e2e as pe  # noqa: E402


def test_f_beta_known_values():
    assert pe.f_beta(10, 10, 10) == pytest.approx(1.0)
    assert pe.f_beta(0, 10, 10) == 0.0
    # precision 0.5, recall 1.0 -> F0.5 = 1.25*0.5*1/(0.25*0.5+1) = 0.5556
    assert pe.f_beta(10, 20, 10) == pytest.approx(1.25 * 0.5 / (0.125 + 1.0))
    assert pe.f_beta(0, 0, 0) == 0.0


def test_auc_and_best_threshold_on_a_perfect_and_a_random_map():
    rng = np.random.default_rng(0)
    lab = np.zeros((40, 40), np.uint8)
    lab[10:20, 10:20] = 1
    valid = np.ones_like(lab, bool)
    perfect = lab.astype(np.float32) * 0.8 + 0.1
    assert pe.auc(perfect, lab, valid) == 1.0
    thr, f = pe.best_f05(perfect, lab, valid)
    assert f == pytest.approx(1.0) and 0.1 < thr <= 0.8
    noise = rng.random(lab.shape).astype(np.float32)
    assert 0.35 < pe.auc(noise, lab, valid) < 0.65


def test_scores_ignore_invalid_pixels():
    lab = np.zeros((20, 20), np.uint8)
    lab[:, :10] = 1
    prob = lab.astype(np.float32)
    valid = np.ones_like(lab, bool)
    prob[:, 15:] = 1.0                      # wrong, but invalid
    valid[:, 15:] = False
    assert pe.auc(prob, lab, valid) == 1.0
    assert pe.f05_at(prob, lab, valid, 0.5) == pytest.approx(1.0)
