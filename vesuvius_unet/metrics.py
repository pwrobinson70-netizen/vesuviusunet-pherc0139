"""Evaluation metrics matching the original Kaggle Vesuvius Ink Detection
competition's scoring (precision-weighted F-beta=0.5), so results here are
directly comparable to the RandomForest starter notebook and to public
leaderboard scores."""
from __future__ import annotations

import numpy as np


def fbeta(precision: float, recall: float, beta: float = 0.5) -> float:
    if precision + recall == 0:
        return 0.0
    b2 = beta ** 2
    return (1 + b2) * precision * recall / (b2 * precision + recall)


def binary_metrics(probs: np.ndarray, targets: np.ndarray, threshold: float = 0.5) -> dict:
    """probs, targets: flat float arrays (targets in {0,1}). Returns precision/recall/F0.5/AUC."""
    preds = (probs >= threshold).astype(np.uint8)
    targets = targets.astype(np.uint8)

    tp = int(((preds == 1) & (targets == 1)).sum())
    fp = int(((preds == 1) & (targets == 0)).sum())
    fn = int(((preds == 0) & (targets == 1)).sum())

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f05 = fbeta(precision, recall, beta=0.5)

    try:
        from sklearn.metrics import roc_auc_score
        auc = roc_auc_score(targets, probs) if len(np.unique(targets)) > 1 else float("nan")
    except ImportError:
        auc = float("nan")

    return {"precision": precision, "recall": recall, "f05": f05, "auc": auc}
