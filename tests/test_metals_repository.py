from datetime import date, datetime, timezone
from database.repository import Repository
from database.session import create_schema, session_scope
def test_cot_upsert_is_idempotent(tmp_path):
    url=f"sqlite:///{tmp_path/'m.db'}"; create_schema(url); now=datetime.now(timezone.utc)
    row={"asset":"GOLD","report_date":date(2026,1,6),"category":"managed_money","long":2,"short":1,"spreading":0,"net":1,"open_interest":10,"source":"CFTC","fetched_at":now,"status":"OK"}
    with session_scope(url) as s: Repository(s).upsert_cot([row,row])
    with session_scope(url) as s: assert len(Repository(s).cot("gold"))==1
