from datetime import datetime, timezone
from sqlalchemy import func, select
from collectors.base import MetricPoint, MetricStatus
from database.models import Metric
from database.repository import Repository
from database.session import create_schema, session_scope

def test_upsert_prevents_duplicate(tmp_path):
    url=f"sqlite:///{tmp_path/'test.db'}"; create_schema(url); now=datetime.now(timezone.utc); p=MetricPoint(metric_name="x",timestamp=now,value=1,source="test",fetched_at=now,status=MetricStatus.OK)
    with session_scope(url) as s: Repository(s).upsert_metrics([p,p])
    with session_scope(url) as s: assert s.scalar(select(func.count()).select_from(Metric)) == 1

