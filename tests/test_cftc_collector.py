from datetime import date
import httpx
from collectors.cftc import CFTCCollector, scheduled_publication_date

def test_cftc_parsing_and_net():
    row={"report_date_as_yyyy_mm_dd":"2026-08-25T00:00:00.000","open_interest_all":"500",
         "m_money_positions_long_all":"120","m_money_positions_short_all":"40","m_money_positions_spread":"10"}
    transport=httpx.MockTransport(lambda request:httpx.Response(200,json=[row]))
    records=CFTCCollector("gold",client=httpx.Client(transport=transport)).fetch_history(date(2026,1,1),date(2026,9,1))
    mm=next(x for x in records if x["category"]=="managed_money")
    assert mm["net"]==80 and mm["open_interest"]==500 and mm["report_date"]==date(2026,8,25)

def test_position_and_scheduled_publication_dates_are_distinct():
    assert scheduled_publication_date(date(2026, 8, 25)) == date(2026, 8, 28)


def test_missing_and_invalid_positions_are_not_reported_as_ok():
    row = {"report_date_as_yyyy_mm_dd": "2026-08-25T00:00:00.000", "open_interest_all": "500",
           "m_money_positions_long_all": "NaN", "m_money_positions_short_all": "-40"}
    c = CFTCCollector("gold", client=httpx.Client(transport=httpx.MockTransport(
        lambda _: httpx.Response(200, json=[row]))))
    records = c.fetch_history(date(2026, 8, 1), date(2026, 9, 1))
    mm = next(record for record in records if record["category"] == "managed_money")
    assert mm["status"] == "MISSING" and mm["net"] is None
    assert mm["long"] is None and mm["short"] is None
    assert all(record["status"] == "MISSING" for record in records)


def test_wrong_contract_bad_dates_and_outside_range_are_ignored():
    rows = [{"report_date_as_yyyy_mm_dd": "2026-08-25", "cftc_contract_market_code": "084691"},
            {"report_date_as_yyyy_mm_dd": "2026-07-28", "cftc_contract_market_code": "088691"},
            {"report_date_as_yyyy_mm_dd": "not a date"}]
    c = CFTCCollector("gold", client=httpx.Client(transport=httpx.MockTransport(
        lambda _: httpx.Response(200, json=rows))))
    assert c.fetch_history(date(2026, 8, 1), date(2026, 9, 1)) == []


def test_api_error_object_cannot_be_a_successful_empty_table():
    import pytest
    c = CFTCCollector("gold", client=httpx.Client(transport=httpx.MockTransport(
        lambda _: httpx.Response(200, json={"error": "dataset unavailable"}))))
    with pytest.raises(ValueError, match="positions table"):
        c.fetch_history(date(2026, 8, 1), date(2026, 9, 1))
