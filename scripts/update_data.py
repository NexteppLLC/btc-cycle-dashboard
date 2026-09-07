#!/usr/bin/env python
from pathlib import Path
import argparse
import json
import logging
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.report_service import generate_report
from services.update_service import run_update
from services.health_service import build_diagnostics
from database.repository import Repository
from database.session import session_scope

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Update measured market data and daily report")
    parser.add_argument("--diagnostics-json", type=Path)
    parser.add_argument("--days", type=int, default=1500)
    args = parser.parse_args()
    if args.days < 1:
        parser.error("--days must be positive")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # HTTP request URLs can contain configured feed tokens/API keys. Collector
    # diagnostics log only bounded statuses and field names.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    result = run_update(days=args.days)
    with session_scope() as session:
        repo = Repository(session)
        diagnostics = build_diagnostics(repo.metrics(), repo.cot("gold") + repo.cot("silver"),
                                        repo.etf_holdings(), metric_points=result["points"],
                                        etf_records=result["etf_records"])
    path = generate_report(result["snapshot"], metals=result["metals"], diagnostics=diagnostics)
    if args.diagnostics_json:
        args.diagnostics_json.parent.mkdir(parents=True, exist_ok=True)
        args.diagnostics_json.write_text(json.dumps(diagnostics, ensure_ascii=False, indent=2), encoding="utf-8")
    for warning in diagnostics["warnings"]:
        logging.warning(warning)
    for failure in diagnostics["essential_failures"]:
        logging.error(failure)
    print(f'Updated {result["points"]} metric points and {result["etf_records"]} ETF records; report: {path}')
    print(f'Data quality: {diagnostics["status"]}')
    if diagnostics["essential_failures"]:
        sys.exit(1)
