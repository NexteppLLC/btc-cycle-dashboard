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


def test_dated_summary_json_respects_requested_history():
    content = '{"summary":{"date":"2026-09-04","shares outstanding":12000,"ounces in trust":3000}}'
    assert collector()._parse("IAU", "GOLD", "official", content,
                              date(2026, 8, 1), date(2026, 8, 31)) == []


def test_json_bar_market_values_are_not_fund_assets():
    content = '{"bars":[{"date":"2026-09-04","fine ounces":400,"market value":1500000}]}'
    assert collector()._parse("GLD", "GOLD", "official", content,
                              date(2026, 9, 1), date(2026, 9, 5)) == []


def test_archive_outside_requested_dates_does_not_become_undated_snapshot():
    assert collector()._parse("GLD", "GOLD", "official", GLD,
                              date(2026, 8, 1), date(2026, 8, 31)) == []


def test_native_xlsx_reads_dates_and_separate_sheets_without_crossing_columns():
    import io
    from openpyxl import Workbook
    workbook = Workbook()
    workbook.active.title = "Read Me"
    workbook.active.append(["Official historical archive"])
    holdings = workbook.create_sheet("Historical Archive")
    holdings.append(["Date", "Total Shares Outstanding", "Total Gold in Trust in Ounces"])
    holdings.append([datetime(2026, 9, 4), 12000, 3000])
    prices = workbook.create_sheet("Price History")
    prices.append(["Date", "Share Price", "Trading Volume"])
    prices.append([datetime(2026, 9, 5), 100, 500])
    raw = io.BytesIO()
    workbook.save(raw)
    content = collector()._decode(httpx.Response(200, content=raw.getvalue()))
    records = collector()._parse("GLD", "GOLD", "official", content,
                                  date(2026, 9, 1), date(2026, 9, 5))
    assert len(records) == 1
    assert records[0]["effective_date"] == date(2026, 9, 4)
    assert records[0]["shares_outstanding"] == 12000
    assert records[0]["ounces"] == 3000


def test_native_spreadsheetml_sparse_columns_and_dated_values():
    raw = b'''<?xml version="1.0"?><Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet" xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet"><Worksheet ss:Name="Historical"><Table>
<Row><Cell><Data ss:Type="String">Date</Data></Cell><Cell ss:Index="3"><Data ss:Type="String">Shares Outstanding</Data></Cell><Cell><Data ss:Type="String">Net Assets</Data></Cell></Row>
<Row><Cell><Data ss:Type="DateTime">2026-09-04T00:00:00</Data></Cell><Cell ss:Index="3"><Data ss:Type="Number">12000</Data></Cell><Cell><Data ss:Type="Number">36000000</Data></Cell></Row>
</Table></Worksheet></Workbook>'''
    content = collector()._decode(httpx.Response(200, content=raw))
    records = collector()._parse("IAU", "GOLD", "official", content,
                                  date(2026, 9, 1), date(2026, 9, 5))
    assert records[0]["effective_date"] == date(2026, 9, 4)
    assert records[0]["shares_outstanding"] == 12000
    assert records[0]["net_assets"] == 36000000


def test_ishares_html_uses_each_fact_date_and_never_nav_per_share():
    content = '''<html><head><title>iShares Gold Trust | IAU</title></head><body>
<div><span>NAV</span><span>$83.01</span><span>as of Sep 04, 2026</span></div>
<div><span>Shares Outstanding</span><span>12,000</span><span>as of Sep 04, 2026</span></div>
<div><span>Ounces in Trust</span><span>3,000</span><span>as of Sep 03, 2026</span></div>
<div><span>Net Assets of Fund</span><span>$36,000,000</span><span>as of Sep 04, 2026</span></div>
</body></html>'''
    records = collector()._parse("IAU", "GOLD", "official", content,
                                  date(2026, 9, 1), date(2026, 9, 5))
    assert len(records) == 2
    assert records[0]["effective_date"] == date(2026, 9, 3)
    assert records[0]["ounces"] == 3000 and records[0]["shares_outstanding"] is None
    assert records[1]["effective_date"] == date(2026, 9, 4)
    assert records[1]["shares_outstanding"] == 12000 and records[1]["ounces"] is None
    assert records[1]["net_assets"] == 36000000


def test_html_requires_explicit_fact_date_and_correct_fund():
    content = '<html><title>iShares Gold Trust | IAU</title><div>Shares Outstanding<span>12,000</span></div></html>'
    assert collector()._parse("IAU", "GOLD", "official", content,
                              date(2026, 9, 1), date(2026, 9, 5)) == []
    wrong_fund = content.replace('</div>', '<span>as of Sep 04, 2026</span></div>')
    assert collector()._parse("SLV", "SILVER", "official", wrong_fund,
                              date(2026, 9, 1), date(2026, 9, 5)) == []


def test_native_download_failure_uses_official_dated_product_page():
    from collectors.metals_etf import FALLBACKS
    content = '<html><title>iShares Gold Trust | IAU</title><div><span>Shares Outstanding</span><span>12,000</span><span>as of Sep 04, 2026</span></div></html>'
    def handler(request):
        if str(request.url) == FALLBACKS["IAU"][0]:
            return httpx.Response(200, text=content)
        return httpx.Response(200, text='<html>File unavailable</html>')
    c = MetalsETFCollector(client=httpx.Client(transport=httpx.MockTransport(handler)))
    records = c.fetch_history(date(2026, 9, 1), date(2026, 9, 5))
    assert len(records) == 1 and records[0]["fund"] == "IAU"
    assert records[0]["source"] == FALLBACKS["IAU"][0]
    assert c.diagnostics["IAU"]["status"] == "HTTP_OK_PARSE_OK"
    assert c.diagnostics["IAU"]["attempts"][0]["status"] == "HTTP_OK_SCHEMA_UNEXPECTED"


def test_corrupt_workbook_is_schema_error_after_http_success():
    c = MetalsETFCollector(client=httpx.Client(transport=httpx.MockTransport(
        lambda _: httpx.Response(200, content=b'PK\x03\x04bad workbook'))))
    assert c.fetch_history(date(2026, 9, 1), date(2026, 9, 5)) == []
    assert c.diagnostics["GLD"]["status"] == "HTTP_OK_SCHEMA_UNEXPECTED"


def test_negative_holdings_are_unavailable():
    content = 'Fund Holdings as of,"Sep 04, 2026"\nShares Outstanding,"-12,000"\nOunces in Trust,"-3,000"\n'
    assert collector()._parse("IAU", "GOLD", "official", content,
                              date(2026, 9, 1), date(2026, 9, 5)) == []


def test_html_undated_card_does_not_borrow_footer_date():
    content = '<html><body><h1>iShares Gold Trust</h1><div><span>Shares Outstanding</span><span>12,000</span></div><footer>as of Sep 04, 2026</footer></body></html>'
    assert collector()._parse("IAU", "GOLD", "official", content,
                              date(2026, 9, 1), date(2026, 9, 5)) == []


def test_workbook_summary_values_keep_their_own_worksheet_dates():
    content = 'Fund Holdings as of,"Sep 01, 2026"\nShares Outstanding,12000\n__SPONSOR_WORKSHEET_BOUNDARY__\nFund Holdings as of,"Sep 04, 2026"\nOunces in Trust,3000\n__SPONSOR_WORKSHEET_BOUNDARY__\n'
    records = collector()._parse("IAU", "GOLD", "official", content,
                                  date(2026, 9, 1), date(2026, 9, 5))
    assert len(records) == 2
    assert records[0]["effective_date"] == date(2026, 9, 1)
    assert records[0]["shares_outstanding"] == 12000 and records[0]["ounces"] is None
    assert records[1]["effective_date"] == date(2026, 9, 4)
    assert records[1]["ounces"] == 3000 and records[1]["shares_outstanding"] is None


def test_declared_units_and_usd_currency_must_match_field():
    content = 'Fund Holdings as of,"Sep 04, 2026"\nShares Outstanding,100%\nOunces in Trust,3 tonnes\nNet Assets,€4000\n'
    assert collector()._parse("IAU", "GOLD", "official", content,
                              date(2026, 9, 1), date(2026, 9, 5)) == []


def test_html_preserves_separate_currency_and_unit_tokens():
    content = '<html><body><h1>iShares Gold Trust</h1><div><span>Net Assets of Fund</span><span>€</span><span>4000</span><span>as of Sep 04, 2026</span></div><div><span>Ounces in Trust</span><span>3</span><span>tonnes</span><span>as of Sep 04, 2026</span></div></body></html>'
    assert collector()._parse("IAU", "GOLD", "official", content,
                              date(2026, 9, 1), date(2026, 9, 5)) == []


def test_gld_parenthesized_holdings_units_are_physical_totals():
    content = '''Date,GLD Close,Ounces of Gold Per Share,Total Gold in Trust (Tonnes),Total Gold in Trust (Ounces),Total Net Asset Value in the Trust
04-Sep-2026,406.77,0.09,1000.25,32158784.1866,149293331231.18
'''
    record = collector()._parse("GLD", "GOLD", "official", content,
                                 date(2026, 9, 4), date(2026, 9, 4))[0]
    assert record["tonnes"] == 1000.25
    assert record["ounces"] == 32158784.1866
    assert record["physical_holdings"] == 32158784.1866 and record["holdings_unit"] == "OUNCES"
    assert record["net_assets"] == 149293331231.18
    assert record["shares_outstanding"] is None


def test_gld_physical_only_table_header_is_recognized():
    content = 'Date,Total Gold in Trust (Tonnes)\n04-Sep-2026,1000.25\n'
    record = collector()._parse("GLD", "GOLD", "official", content,
                                 date(2026, 9, 4), date(2026, 9, 4))[0]
    assert record["physical_holdings"] == 1000.25 and record["holdings_unit"] == "TONNES"
    assert record["net_assets"] is None and record["ounces"] is None


def test_gld_legacy_sponsor_labels_keep_weight_units_separate_from_assets():
    content = 'Date,Total Net Asset Value Ounces in the Trust,Total Net Asset Value Tonnes in the Trust,Total Net Asset Value in the Trust\n04-Sep-2026,32000000,995.3,140000000000\n'
    record = collector()._parse("GLD", "GOLD", "official", content,
                                 date(2026, 9, 4), date(2026, 9, 4))[0]
    assert record["ounces"] == 32000000 and record["tonnes"] == 995.3
    assert record["net_assets"] == 140000000000


def test_schema_diagnostic_finds_late_worksheet_header_and_columns():
    content = ('Legal preamble\n' * 55 + '__SPONSOR_WORKSHEET_BOUNDARY__\n'
               'Date,Close,NAV per Share,Price,Bid,Ask,Volume,Total Gold in Trust (Tonnes),Total Gold in Trust (Ounces),Total Net Asset Value in the Trust\n'
               '04-Sep-2026,406.77,407,405,406,407,500,1000.25,32158784.1866,149293331231.18\n')
    shape = collector()._shape(content)
    assert shape["table_headers"][0]["worksheet"] == 2
    assert shape["table_headers"][0]["line"] == 57
    assert "total gold in trust tonnes" in shape["table_headers"][0]["fields"]
    assert "total gold in trust ounces" in shape["table_headers"][0]["fields"]
    assert "149293331231" not in str(shape) and "32158784" not in str(shape)


def test_parse_diagnostic_reports_physical_field_coverage():
    content = 'Date,Total Gold in Trust (Tonnes),Total Net Asset Value in the Trust\n04-Sep-2026,1000.25,149293331231.18\n'
    c = MetalsETFCollector(client=httpx.Client(transport=httpx.MockTransport(
        lambda _: httpx.Response(200, text=content))))
    c.fetch_history(date(2026, 9, 4), date(2026, 9, 4))
    coverage = c.diagnostics["GLD"]["field_counts"]
    assert coverage["physical_holdings"] == 1 and coverage["tonnes"] == 1
    assert coverage["ounces"] == 0 and coverage["shares_outstanding"] == 0


def test_current_spdr_archive_headers_observed_in_production():
    # Exact worksheet 2 header schema from the official workbook's live update.
    content = ('Date,Closing Price,Ounces of Gold Per Share,NAV/share at 10.30am NYT,'
               'Indicative Price per Share at 4.15pm NYT,Mid point of bid ask spread at 4.15pm NYT,'
               'Premium discount of GLD mid point vs indicative value of GLD at 4.15pm NYT,'
               'Daily Share Volume,Total Ounces of Gold in the Trust,Tonnes of Gold,Total Net Asset Value in the Trust\n'
               '2026-09-04,400,0.09,400,400,400,0,1000000,30000000,933.1,130000000000\n')
    rows = collector()._parse("GLD", "GOLD", "official", content, date(2026, 9, 1), date(2026, 9, 7))
    assert len(rows) == 1
    assert rows[0]["physical_holdings"] == 30000000
    assert rows[0]["ounces"] == 30000000
    assert rows[0]["tonnes"] == 933.1
    assert rows[0]["shares_outstanding"] is None
    assert rows[0]["net_assets"] == 130000000000
