from datetime import date
import httpx
from collectors.cftc import CFTCCollector

def test_cftc_parsing_and_net():
    row={"report_date_as_yyyy_mm_dd":"2026-08-25T00:00:00.000","open_interest_all":"500",
         "m_money_positions_long_all":"120","m_money_positions_short_all":"40","m_money_positions_spread":"10"}
    transport=httpx.MockTransport(lambda request:httpx.Response(200,json=[row]))
    records=CFTCCollector("gold",client=httpx.Client(transport=transport)).fetch_history(date(2026,1,1),date(2026,9,1))
    mm=next(x for x in records if x["category"]=="managed_money")
    assert mm["net"]==80 and mm["open_interest"]==500 and mm["report_date"]==date(2026,8,25)
