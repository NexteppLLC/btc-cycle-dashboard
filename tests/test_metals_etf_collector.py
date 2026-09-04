from datetime import date
import httpx

from collectors.metals_etf import MetalsETFCollector
from database.repository import Repository
from database.session import create_schema, session_scope


GLD = '''metadata\nDate,Shares Outstanding as of,Total Gold in Trust in Ounces,Total Gold in Trust in Tonnes,Total Net Asset Value in the Trust\n01-Sep-2026,"10,000","2,000",62.2,"$3,000"\n'''
ISHARES = '''Fund Holdings as of,"Sep 01, 2026"\nShares Outstanding,"12,000"\nTicker,Name,Asset Class,Market Value,Quantity\n{ticker},{name},Commodity,"$4,000","3,000"\n'''


def collector(): return MetalsETFCollector()


def test_gld_api_parse_and_column_variant():
    rows = collector()._parse("GLD", "GOLD", "official", GLD, date(2026,9,1), date(2026,9,2))
    assert rows[0]["shares_outstanding"] == 10000 and rows[0]["ounces"] == 2000
    assert rows[0]["tonnes"] == 62.2 and rows[0]["nav"] == 3000


def test_iau_csv_parse():
    rows = collector()._parse("IAU", "GOLD", "official", ISHARES.format(ticker="GOLD", name="Gold Trust"), date(2026,9,1), date(2026,9,2))
    assert rows[0]["effective_date"] == date(2026,9,1) and rows[0]["ounces"] == 3000
    assert rows[0]["flow"] is None and rows[0]["flow_status"] == "UNAVAILABLE"


def test_slv_csv_parse():
    rows = collector()._parse("SLV", "SILVER", "official", ISHARES.format(ticker="SLV", name="Silver Trust"), date(2026,9,1), date(2026,9,2))
    assert rows[0]["shares_outstanding"] == 12000 and rows[0]["ounces"] == 3000


def test_all_provider_records_are_saved(tmp_path):
    def handler(request):
        text = GLD if "spdr" in str(request.url) else ISHARES.format(ticker="SLV" if "SLV" in str(request.url) else "GOLD", name="Silver Trust" if "SLV" in str(request.url) else "Gold Trust")
        return httpx.Response(200, text=text)
    c = MetalsETFCollector(client=httpx.Client(transport=httpx.MockTransport(handler)))
    records = c.fetch_history(date(2026,9,1), date(2026,9,2))
    url = f"sqlite:///{tmp_path/'etf.db'}"; create_schema(url)
    with session_scope(url) as session: Repository(session).upsert_etf_holdings(records)
    with session_scope(url) as session:
        saved = Repository(session).etf_holdings()
        assert len(saved) == 3 and {x.fund for x in saved} == {"GLD", "IAU", "SLV"}
