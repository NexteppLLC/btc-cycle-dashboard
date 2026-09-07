"""Calendar-labelled flow totals use calendar intervals and complete weekdays."""
from datetime import date

import numpy as np
import pandas as pd

from indicators.etf import etf_aggregates
from services.update_service import build_btc_inputs


def test_seven_calendar_days_sum_five_weekday_observations():
    flows = pd.Series(100.0, index=pd.bdate_range("2026-08-27", "2026-09-04"))
    result = etf_aggregates(flows)
    assert result["7d"] == 500  # Aug 29..Sep 4, not seven trading observations.
    assert result["3d"] == 300 and result["avg_7d"] == 100


def test_thirty_calendar_days_exclude_older_observations():
    flows = pd.Series(10.0, index=pd.bdate_range("2026-07-01", "2026-09-04"))
    result = etf_aggregates(flows)
    assert result["30d"] == 220  # Aug 6..Sep 4 contains twenty-two weekdays.
    assert result["avg_30d"] == 10


def test_missing_weekday_is_unknown_even_when_older_rows_are_available():
    flows = pd.Series(100.0, index=pd.bdate_range("2026-08-01", "2026-09-04"))
    flows = flows.drop(pd.Timestamp("2026-09-01"))
    result = etf_aggregates(flows)
    assert result["7d"] is None and result["30d"] is None
    assert result["today"] == 100 and result["3d"] == 300


def test_unverified_holiday_does_not_become_zero_flow():
    flows = pd.Series(100.0, index=pd.bdate_range("2026-09-01", "2026-09-08"))
    flows = flows.drop(pd.Timestamp("2026-09-07"))
    assert etf_aggregates(flows)["7d"] is None


def test_explicit_missing_observation_and_duplicate_day_block_window():
    dates = pd.bdate_range("2026-08-27", "2026-09-04")
    flows = pd.Series(100.0, index=dates)
    flows.iloc[-1] = np.nan
    assert all(value is None for value in etf_aggregates(flows).values())
    flows.iloc[-1] = 100
    flows = pd.concat([flows, flows.iloc[-1:]])
    assert etf_aggregates(flows)["7d"] is None


def test_update_pipeline_uses_latest_observation_for_calendar_window_anchor():
    rows = [{"date": day.date(), "metric_name": "etf_flow_usd", "source": "configured",
             "status": "OK", "value": 100, "fetched_at": "2026-09-07"}
            for day in pd.bdate_range("2026-08-27", "2026-09-04")]
    _, flow, _ = build_btc_inputs(rows, date(2026, 9, 7))
    assert flow["today"] == 100 and flow["7d"] == 500


def test_short_calendar_window_includes_weekend_without_invented_observations():
    flows = pd.Series([0.0], index=pd.to_datetime(["2026-09-07"]))
    assert etf_aggregates(flows)["3d"] == 0
    assert etf_aggregates(flows)["7d"] is None
