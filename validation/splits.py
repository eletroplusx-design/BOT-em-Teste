from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import pandas as pd

from .errors import ValidationSplitError
from .models import SegmentView, ValidationSplitConfig, WindowBounds


def _ensure_chronological(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        raise ValidationSplitError("DataFrame is empty.")
    result = df.copy()
    if "open_time" in result.columns:
        times = pd.to_datetime(result["open_time"], utc=True, errors="coerce")
    else:
        times = pd.to_datetime(result.index, utc=True, errors="coerce")
    if times.isna().any():
        raise ValidationSplitError("Chronological timestamps are required.")
    if not times.is_monotonic_increasing:
        raise ValidationSplitError("Candles must be chronologically ordered.")
    if times.duplicated().any():
        raise ValidationSplitError("Duplicate timestamps are not allowed.")
    result = result.reset_index(drop=True)
    result["_validation_time"] = times.reset_index(drop=True)
    return result


def _build_windows(total: int, config: ValidationSplitConfig, *, expanding: bool) -> list[WindowBounds]:
    windows: list[WindowBounds] = []
    start = 0
    train_bars = int(config.train_bars)
    validation_bars = int(config.validation_bars)
    test_bars = int(config.test_bars)
    warmup_bars = int(config.warmup_bars)
    purge_bars = int(config.purge_bars)
    embargo_bars = int(config.embargo_bars)
    step = int(config.effective_step_bars)

    if total < train_bars + validation_bars + test_bars:
        raise ValidationSplitError("Not enough candles for the requested split.")

    while True:
        train_start = 0 if expanding else start
        train_end = train_start + train_bars if expanding else start + train_bars
        validation_start = train_end + purge_bars
        validation_end = validation_start + validation_bars
        test_start = validation_end + embargo_bars
        test_end = test_start + test_bars
        warmup_start = max(0, train_start - warmup_bars)

        if test_end > total:
            break

        windows.append(
            WindowBounds(
                warmup_start=warmup_start,
                train_start=train_start,
                train_end=train_end,
                validation_start=validation_start,
                validation_end=validation_end,
                test_start=test_start,
                test_end=test_end,
                mode="expanding" if expanding else "rolling",
            )
        )

        if expanding:
            train_bars += step
        else:
            start += step

        if expanding and train_bars + validation_bars + test_bars + purge_bars + embargo_bars > total:
            break
        if not expanding and start + train_bars + validation_bars + test_bars + purge_bars + embargo_bars > total:
            break

    if not windows:
        raise ValidationSplitError("No valid windows could be built.")
    return windows


def build_rolling_windows(df: pd.DataFrame, config: ValidationSplitConfig) -> list[WindowBounds]:
    frame = _ensure_chronological(df)
    return _build_windows(len(frame), config, expanding=False)


def build_expanding_windows(df: pd.DataFrame, config: ValidationSplitConfig) -> list[WindowBounds]:
    frame = _ensure_chronological(df)
    return _build_windows(len(frame), config, expanding=True)


def build_windows(df: pd.DataFrame, config: ValidationSplitConfig) -> list[WindowBounds]:
    if config.mode == "rolling":
        return build_rolling_windows(df, config)
    return build_expanding_windows(df, config)


def slice_window_frames(df: pd.DataFrame, window: WindowBounds) -> dict[str, pd.DataFrame]:
    frame = df.reset_index(drop=True)
    return {
        "warmup": frame.iloc[window.warmup_start:window.train_start].copy(),
        "train": frame.iloc[window.train_start:window.train_end].copy(),
        "validation": frame.iloc[window.validation_start:window.validation_end].copy(),
        "test": frame.iloc[window.test_start:window.test_end].copy(),
    }


def build_segment_view(df: pd.DataFrame, *, segment_start: int, segment_end: int, warmup_bars: int, name: str) -> SegmentView:
    frame = df.reset_index(drop=True)
    if segment_start < 0 or segment_end < 0:
        raise ValidationSplitError("segment bounds cannot be negative.")
    if segment_end <= segment_start:
        raise ValidationSplitError("segment_end must be greater than segment_start.")
    if segment_end > len(frame):
        raise ValidationSplitError("segment_end exceeds available candles.")
    warmup_start = max(0, segment_start - warmup_bars)
    segment_frame = frame.iloc[warmup_start:segment_end].copy()
    return SegmentView(
        name=name,
        frame=segment_frame,
        warmup_start=warmup_start,
        segment_start=segment_start,
        segment_end=segment_end,
        trade_start_index=segment_start - warmup_start,
        warmup_rows=segment_start - warmup_start,
        segment_rows=segment_end - segment_start,
    )


def build_window_segment_views(df: pd.DataFrame, window: WindowBounds, warmup_bars: int) -> dict[str, SegmentView]:
    return {
        "train": build_segment_view(df, segment_start=window.train_start, segment_end=window.train_end, warmup_bars=warmup_bars, name="train"),
        "validation": build_segment_view(df, segment_start=window.validation_start, segment_end=window.validation_end, warmup_bars=warmup_bars, name="validation"),
        "test": build_segment_view(df, segment_start=window.test_start, segment_end=window.test_end, warmup_bars=warmup_bars, name="test"),
    }
