from datetime import date

import httpx
import pytest

from collectors.base import MetricStatus
from collectors.etf_flow import ETFFlowCollector


def collect(body, start=date(2026, 9, 1), end=date(2026, 9, 7)):
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, text=body)))
    with client:
        return ETFFlowCollector("https://example.test/approved.csv", client=client).fetch_history(start, end)


def test_components_form_one_signed_daily_total():
    points = collect("date,flow_usd,fund\n2026-09-04,100,IBIT\n2026-09-04,-40,FBTC\n")
    assert len(points) == 1
    assert points[0].value == 60
    assert points[0].status == MetricStatus.OK
    assert points[0].metadata["fund"] == "TOTAL"
    assert points[0].metadata["effective_date"] == "2026-09-04"


def test_explicit_total_is_never_double_counted_with_components():
    points = collect("date,flow_usd,fund\n2026-09-04,60,total\n2026-09-04,100,IBIT\n2026-09-04,,FBTC\n")
    assert len(points) == 1
    assert points[0].value == 60 and points[0].status == MetricStatus.OK


@pytest.mark.parametrize("value", ["", "NaN", "inf", "-inf", "not-a-number"])
def test_missing_or_nonfinite_constituent_prevents_partial_sum(value):
    points = collect(f"date,flow_usd,fund\n2026-09-04,100,IBIT\n2026-09-04,{value},FBTC\n")
    assert points[0].value is None and points[0].status == MetricStatus.MISSING


def test_missing_known_constituent_row_is_not_zero():
    points = collect("date,flow_usd,fund\n2026-09-03,10,IBIT\n2026-09-03,20,FBTC\n2026-09-04,50,IBIT\n")
    assert [p.value for p in points] == [30, None]
    assert points[1].status == MetricStatus.MISSING


@pytest.mark.parametrize("body", [
    "date,flow_usd,fund\n2026-09-04,10,TOTAL\n2026-09-04,10,total\n",
    "date,flow_usd,fund\n2026-09-04,10,IBIT\n2026-09-04,10,ibit\n",
    "date,flow_usd\n2026-09-04,10\n2026-09-04,20\n",
    "date,flow_usd,fund\n2026-09-04,10,\n2026-09-04,20,IBIT\n",
])
def test_ambiguous_duplicates_are_rejected(body):
    points = collect(body)
    assert len(points) == 1
    assert points[0].value is None and points[0].status == MetricStatus.ERROR


def test_single_daily_totals_preserve_signed_zero_values_and_date_bounds():
    points = collect("date,flow_usd\n2026-08-31,999\n2026-09-01,0\n2026-09-02,-25\n2026-09-08,999\n")
    assert [p.timestamp.date() for p in points] == [date(2026, 9, 1), date(2026, 9, 2)]
    assert [p.value for p in points] == [0, -25]
    assert all(p.status == MetricStatus.OK for p in points)


def test_intraday_rows_share_utc_day_and_do_not_create_duplicate_db_keys():
    points = collect("date,flow_usd,fund\n2026-09-04T01:00:00Z,10,IBIT\n2026-09-04T23:00:00Z,20,FBTC\n")
    assert len(points) == 1 and points[0].value == 30
    assert points[0].timestamp.hour == 0


def test_undated_observation_is_not_assigned_a_measured_date():
    points = collect("date,flow_usd\n,100\n")
    assert points[0].value is None and points[0].status == MetricStatus.ERROR
