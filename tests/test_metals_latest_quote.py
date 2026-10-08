"""Weekend handling of the GC=F/SI=F latest quote (CME pause Friday 17:00 - Sunday 18:00 New York time)."""
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
import pytest

import collectors.metals_price as metals_module
from collectors.base import MetricStatus
from collectors.metals_price import MetalsPriceCollector, comex_weekend_closure_start
from services.health_service import build_diagnostics

UTC = timezone.utc
NEW_YORK = ZoneInfo("America/New_York")
FRIDAY_LAST_TRADE = datetime(2026, 10, 9, 20, 59, tzinfo=UTC)  # Fri 16:59 EDT, just before the pause


def _freeze(monkeypatch, now):
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz) if tz else now.replace(tzinfo=None)

    monkeypatch.setattr(metals_module, "datetime", FrozenDateTime)


def _latest(monkeypatch, now, observed, market_state, asset="gold"):
    _freeze(monkeypatch, now)
    epoch = int(observed.timestamp())
    payload = {"chart": {"result": [{
        "meta": {"regularMarketPrice": 40.0, "regularMarketTime": epoch, "marketState": market_state,
                 "chartPreviousClose": 39.5},
        "timestamp": [epoch], "indicators": {"quote": [{"close": [40.0]}]}}], "error": None}}
    client = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload)))
    return MetalsPriceCollector(asset, client=client).fetch_latest()[0]


@pytest.mark.parametrize("now", [
    datetime(2026, 10, 10, 1, 17, tzinfo=UTC),   # Fri 21:17 EDT (Sat 10:17 JST)
    datetime(2026, 10, 10, 6, 17, tzinfo=UTC),   # Sat 02:17 EDT (Sat 15:17 JST)
    datetime(2026, 10, 11, 6, 17, tzinfo=UTC),   # Sun 02:17 EDT (Sun 15:17 JST)
    datetime(2026, 10, 11, 21, 59, tzinfo=UTC),  # Sun 17:59 EDT, one minute before the reopen
])
@pytest.mark.parametrize("state", ["REGULAR", "PRE", "UNKNOWN"])
def test_weekend_friday_quote_is_closed_last_quote_whatever_yahoo_reports(monkeypatch, now, state):
    point = _latest(monkeypatch, now, FRIDAY_LAST_TRADE, state)
    assert point.status == MetricStatus.OK
    assert point.metadata["freshness"] == "CLOSED_LAST_QUOTE"
    assert point.metadata["market_state"] == state  # the provider's value is kept as reported


def test_weekend_quote_older_than_the_friday_session_stays_stale(monkeypatch):
    point = _latest(monkeypatch, datetime(2026, 10, 10, 1, 17, tzinfo=UTC),
                    datetime(2026, 10, 9, 16, 0, tzinfo=UTC), "REGULAR", asset="silver")  # Fri 12:00 EDT
    assert point.metadata["freshness"] == "STALE"
    assert point.status == MetricStatus.STALE


@pytest.mark.parametrize("now", [
    datetime(2026, 10, 12, 1, 17, tzinfo=UTC),   # Sun 21:17 EDT (Mon 10:17 JST)
    datetime(2026, 10, 12, 6, 17, tzinfo=UTC),   # Mon 02:17 EDT (Mon 15:17 JST)
])
def test_after_the_sunday_reopen_a_friday_quote_is_stale(monkeypatch, now):
    # Trading resumed on Sunday at 18:00 New York time, so Friday's quote is no longer current.
    point = _latest(monkeypatch, now, FRIDAY_LAST_TRADE, "REGULAR")
    assert point.metadata["freshness"] == "STALE"


@pytest.mark.parametrize("now", [
    datetime(2026, 10, 7, 1, 17, tzinfo=UTC),    # Tue 21:17 EDT (Wed 10:17 JST), market open
    datetime(2026, 10, 7, 6, 17, tzinfo=UTC),    # Wed 02:17 EDT (Wed 15:17 JST), market open
])
def test_weekday_rules_are_unchanged(monkeypatch, now):
    assert _latest(monkeypatch, now, now - timedelta(minutes=3), "REGULAR").metadata["freshness"] == "FRESH"
    assert _latest(monkeypatch, now, now - timedelta(minutes=30), "REGULAR").metadata["freshness"] == "DELAYED"
    assert _latest(monkeypatch, now, now - timedelta(hours=2), "REGULAR").metadata["freshness"] == "STALE"
    assert _latest(monkeypatch, now, now - timedelta(hours=2), "CLOSED").metadata["freshness"] == "CLOSED_LAST_QUOTE"


@pytest.mark.parametrize("local, closed", [
    (datetime(2026, 10, 9, 16, 59), False), (datetime(2026, 10, 9, 17, 0), True),
    (datetime(2026, 10, 10, 12, 0), True), (datetime(2026, 10, 11, 17, 59), True),
    (datetime(2026, 10, 11, 18, 0), False), (datetime(2026, 10, 7, 12, 0), False),
    # US daylight saving time ends on Sunday 2026-11-01: the reopen is 18:00 EST (23:00 UTC).
    (datetime(2026, 10, 30, 17, 0), True), (datetime(2026, 11, 1, 17, 59), True),
    (datetime(2026, 11, 1, 18, 0), False),
])
def test_weekend_pause_bounds_follow_new_york_time(local, closed):
    start = comex_weekend_closure_start(local.replace(tzinfo=NEW_YORK).astimezone(UTC))
    assert (start is not None) is closed
    if closed:
        assert start.astimezone(NEW_YORK).weekday() == 4 and start.astimezone(NEW_YORK).hour == 17


def test_closed_weekend_quote_passes_the_required_price_check_and_is_visible():
    as_of = date(2026, 10, 10)
    observed = FRIDAY_LAST_TRADE

    def row(asset, freshness, status="OK", market_state="REGULAR"):
        return dict(metric_name=f"{asset}_price_latest", value=1.0, status=status, timestamp=observed,
                    date=observed.date(), source=f"{asset} test feed", price_type="FUTURES_PROXY",
                    freshness=freshness, market_state=market_state)

    rows = [row("btc", "FRESH", market_state="OPEN"), row("gold", "CLOSED_LAST_QUOTE"),
            row("silver", "STALE", status="STALE")]
    result = build_diagnostics(rows, [], [], as_of=as_of)
    assert result["essential_failures"] == ["SILVER: fresh measured price unavailable"]
    assert result["sources"]["gold_price_latest"]["status"] == "OK"
    assert result["sources"]["gold_price_latest"]["freshness"] == "CLOSED_LAST_QUOTE"
    assert result["sources"]["gold_price_latest"]["market_state"] == "REGULAR"
    assert result["sources"]["silver_price_usd"]["freshness"] == "STALE"
