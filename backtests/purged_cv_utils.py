"""
PURGED CV UTILS
===============

Utilidades de validacion temporal para research financiero.

Objetivo:
  - evitar leakage temporal simple en labels de horizonte corto
  - estandarizar folds temporales para auditar modelos ML fuera del scanner core
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class TimeFold:
    fold_id: int
    train_dates: tuple[pd.Timestamp, ...]
    test_dates: tuple[pd.Timestamp, ...]
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp
    purge_days: int
    embargo_days: int


def _normalize_dates(dates: list[pd.Timestamp] | np.ndarray | pd.Series) -> list[pd.Timestamp]:
    out = sorted(pd.to_datetime(pd.Index(dates).unique()))
    return [pd.Timestamp(ts) for ts in out]


def build_purged_kfold_splits(
    dates: list[pd.Timestamp] | np.ndarray | pd.Series,
    n_splits: int = 5,
    purge_days: int = 1,
    embargo_days: int = 1,
    min_train_days: int = 120,
) -> list[TimeFold]:
    """
    K-fold temporal contiguo con purge y embargo.

    - test = bloque contiguo de fechas
    - train = todas las fechas fuera de la zona [test_start - purge, test_end + embargo]
    """
    all_dates = _normalize_dates(dates)
    if len(all_dates) < max(min_train_days + purge_days + embargo_days + 5, n_splits * 5):
        return []

    index_splits = np.array_split(np.arange(len(all_dates)), n_splits)
    folds: list[TimeFold] = []

    for fold_id, split_idx in enumerate(index_splits, start=1):
        if len(split_idx) == 0:
            continue
        test_start_idx = int(split_idx[0])
        test_end_idx = int(split_idx[-1])

        left_keep = max(0, test_start_idx - purge_days)
        right_keep = min(len(all_dates), test_end_idx + embargo_days + 1)

        train_idx = list(range(0, left_keep)) + list(range(right_keep, len(all_dates)))
        if len(train_idx) < min_train_days:
            continue

        train_dates = tuple(all_dates[i] for i in train_idx)
        test_dates = tuple(all_dates[i] for i in split_idx.tolist())
        folds.append(
            TimeFold(
                fold_id=fold_id,
                train_dates=train_dates,
                test_dates=test_dates,
                train_start=train_dates[0],
                train_end=train_dates[-1],
                test_start=test_dates[0],
                test_end=test_dates[-1],
                purge_days=purge_days,
                embargo_days=embargo_days,
            )
        )
    return folds


def build_purged_expanding_splits(
    dates: list[pd.Timestamp] | np.ndarray | pd.Series,
    n_splits: int = 5,
    test_days: int = 20,
    purge_days: int = 1,
    min_train_days: int = 160,
) -> list[TimeFold]:
    """
    Walk-forward expanding con purge.

    - train = solo pasado
    - test = bloque contiguo
    - purge = elimina los ultimos `purge_days` del train antes del bloque test
    """
    all_dates = _normalize_dates(dates)
    min_required = min_train_days + purge_days + test_days
    if len(all_dates) < min_required:
        return []

    last_test_start = len(all_dates) - test_days
    start_positions = np.linspace(
        min_train_days + purge_days,
        last_test_start,
        num=n_splits,
        dtype=int,
    )
    unique_positions = []
    for pos in start_positions.tolist():
        if pos not in unique_positions:
            unique_positions.append(pos)

    folds: list[TimeFold] = []
    for fold_id, test_start_idx in enumerate(unique_positions, start=1):
        train_end_idx = test_start_idx - purge_days - 1
        test_end_idx = min(len(all_dates) - 1, test_start_idx + test_days - 1)
        if train_end_idx + 1 < min_train_days:
            continue

        train_dates = tuple(all_dates[: train_end_idx + 1])
        test_dates = tuple(all_dates[test_start_idx : test_end_idx + 1])
        folds.append(
            TimeFold(
                fold_id=fold_id,
                train_dates=train_dates,
                test_dates=test_dates,
                train_start=train_dates[0],
                train_end=train_dates[-1],
                test_start=test_dates[0],
                test_end=test_dates[-1],
                purge_days=purge_days,
                embargo_days=0,
            )
        )
    return folds
