from datetime import date, datetime, timezone
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


def test_gld_realistic_response_parse():
    content = '''SPDR Gold Shares\nDate,GLD Close,Total Net Asset Value in the Trust,Total Gold in Trust in Ounces,Total Gold in Trust in Tonnes,Shares Outstanding\n04-Sep-26,220.1,"$98,123,456","32,123,456.70","999.12","310,000,000"\n'''
    rows = collector()._parse("GLD", "GOLD", "official", content, date(2026, 9, 4), date(2026, 9, 4))
    assert rows[0]["effective_date"] == date(2026, 9, 4)
    assert rows[0]["physical_holdings"] == 32123456.70 and rows[0]["holdings_unit"] == "OUNCES"


def test_gld_current_schema():
    """The official daily archive is a summary table, not a bar-weight sum."""
    rows = collector()._parse("GLD", "GOLD", "official", GLD, date(2026, 9, 1), date(2026, 9, 2))
    assert len(rows) == 1 and rows[0]["status"] == "OK"


def test_iau_csv_parse():
    rows = collector()._parse("IAU", "GOLD", "official", ISHARES.format(ticker="GOLD", name="Gold Trust"), date(2026,9,1), date(2026,9,2))
    assert rows[0]["effective_date"] == date(2026,9,1) and rows[0]["ounces"] == 3000
    assert rows[0]["flow"] is None and rows[0]["flow_status"] == "UNAVAILABLE"


def test_iau_realistic_csv_parse():
    content = '\ufeffiShares Gold Trust\nFund Holdings as of,"September 04, 2026"\nShares Outstanding,"1,234,567"\nTicker,Name,Sector,Asset Class,Market Value,Weight (%),Quantity\nXAU,GOLD,,Commodity,"$7,654,321",100,"15,320.45"\n'
    rows = collector()._parse("IAU", "GOLD", "official", content, date(2026, 9, 1), date(2026, 9, 5))
    assert rows[0]["shares_outstanding"] == 1234567
    assert rows[0]["physical_holdings"] == 15320.45


def test_iau_current_schema():
    content = '''iShares Gold Trust\nFund Holdings as of,Shares Outstanding,Net Assets\nSep 04 2026,"1,234,567","$7,654,321"\nTicker,Name,Asset Class,Quantity\nXAU,GOLD,Commodity,"15,320.45"\n'''
    rows = collector()._parse("IAU", "GOLD", "official", content, date(2026, 9, 1), date(2026, 9, 5))
    assert len(rows) == 1 and rows[0]["shares_outstanding"] == 1234567


def test_slv_csv_parse():
    rows = collector()._parse("SLV", "SILVER", "official", ISHARES.format(ticker="SLV", name="Silver Trust"), date(2026,9,1), date(2026,9,2))
    assert rows[0]["shares_outstanding"] == 12000 and rows[0]["ounces"] == 3000


def test_slv_realistic_csv_parse():
    content = 'iShares Silver Trust\nHoldings as of,09/04/2026\nShares Outstanding,"500,000,000"\nOunces in Trust,"492,500,000 oz"\nNet Assets of Fund,"$12,345,678"\n'
    rows = collector()._parse("SLV", "SILVER", "official", content, date(2026, 9, 1), date(2026, 9, 5))
    assert rows[0]["physical_holdings"] == 492500000
    assert rows[0]["net_assets"] == 12345678


def test_slv_current_schema():
    content = '''iShares Silver Trust\nAs of,Shares Outstanding,Ounces in Trust,Net Assets\n09/04/2026,"500,000,000","492,500,000 oz","$12,345,678"\n'''
    rows = collector()._parse("SLV", "SILVER", "official", content, date(2026, 9, 1), date(2026, 9, 5))
    assert len(rows) == 1 and rows[0]["physical_holdings"] == 492500000


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


def test_etf_repository_save(tmp_path):
    url = f"sqlite:///{tmp_path/'save.db'}"; create_schema(url)
    record = collector()._parse("GLD", "GOLD", "official", GLD, date(2026, 9, 1), date(2026, 9, 2))[0]
    with session_scope(url) as session:
        assert Repository(session).upsert_etf_holdings([record]) == 1
    with session_scope(url) as session:
        assert len(Repository(session).etf_holdings("gold")) == 1


def test_etf_upsert(tmp_path):
    url = f"sqlite:///{tmp_path/'upsert.db'}"; create_schema(url)
    record = collector()._parse("GLD", "GOLD", "official", GLD, date(2026, 9, 1), date(2026, 9, 2))[0]
    with session_scope(url) as session:
        repo = Repository(session); repo.upsert_etf_holdings([record]); record["shares_outstanding"] = 99; repo.upsert_etf_holdings([record])
    with session_scope(url) as session:
        saved = Repository(session).etf_holdings(); assert len(saved) == 1 and saved[0].shares_outstanding == 99


def test_repository_rejects_diagnostic_as_holding(tmp_path):
    url = f"sqlite:///{tmp_path/'diagnostic.db'}"; create_schema(url)
    fetched = datetime(2026, 9, 4, tzinfo=timezone.utc)
    diagnostic = collector()._diagnostic_record("GLD", "GOLD", "official", fetched,
                                                "SCHEMA_UNEXPECTED", "no summary")
    with session_scope(url) as session:
        assert Repository(session).upsert_etf_holdings([diagnostic]) == 0


def test_http_200_parse_empty_status():
    def handler(request): return httpx.Response(200, text="<html>consent page</html>")
    c = MetalsETFCollector(client=httpx.Client(transport=httpx.MockTransport(handler)))
    records = c.fetch_history(date(2026, 9, 1), date(2026, 9, 2))
    assert records == []
    assert all(x["status"] == "HTTP_OK_SCHEMA_UNEXPECTED" for x in c.diagnostics.values())


def test_missing_effective_date():
    content = 'Shares Outstanding,"12,000"\nOunces in Trust,"3,000"\n'
    fetched = datetime(2026, 9, 4, tzinfo=timezone.utc)
    rows = collector()._parse("IAU", "GOLD", "official", content, date(2026, 9, 1), date(2026, 9, 5), fetched)
    assert rows[0]["effective_date"] is None and rows[0]["date"] == fetched.date()


def test_numeric_normalization():
    from collectors.metals_etf import _num
    assert [_num(x) for x in ('1,234,567', '$123,456,789', '15,320.45', '492,500,000 oz')] == [1234567, 123456789, 15320.45, 492500000]
    assert _num('N/A') is None and _num('-') is None and _num('not 12 units') is None


def test_schema_diagnostics_are_bounded_and_do_not_log_values():
    shape = collector()._shape('As of,09/04/2026\nShares Outstanding,"500,000,000"\n')
    assert shape["row_count"] == 2
    assert shape["candidate_rows"][0]["fields"] == ["as of"]
    assert "500 000 000" not in str(shape)


def test_gld_bar_json_is_not_guessed_or_summed():
    content = '{"bars":[{"barNumber":"A1","weight":400.1,"date":"2026-09-04"},{"barNumber":"A2","weight":399.9,"date":"2026-09-04"}]}'
    assert collector()._parse("GLD", "GOLD", "official", content,
                              date(2026, 9, 1), date(2026, 9, 5)) == []
    shape = collector()._shape(content)
    assert shape["top_level_keys"] == ["bars"] and shape["weight_fields"] == ["weight"]
