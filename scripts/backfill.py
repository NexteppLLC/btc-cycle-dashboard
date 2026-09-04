#!/usr/bin/env python
"""Incremental, idempotent Coin Metrics/Glassnode historical ingestion."""
from pathlib import Path
import argparse, sys, time
from datetime import date, timedelta
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from collectors.coinmetrics import CoinMetricsCollector
from collectors.glassnode import GlassnodeCollector
from config.settings import get_settings
from database.repository import Repository
from database.session import create_schema, session_scope

def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--start", type=date.fromisoformat, required=True); parser.add_argument("--end", type=date.fromisoformat, required=True); parser.add_argument("--chunk-days", type=int, default=180); parser.add_argument("--sleep", type=float, default=.5); args = parser.parse_args()
    if args.start > args.end: parser.error("--start must not be after --end")
    create_schema(); settings = get_settings(); collectors = [CoinMetricsCollector(), GlassnodeCollector(settings.glassnode_api_key)]
    cursor = args.start
    while cursor <= args.end:
        chunk_end = min(args.end, cursor + timedelta(days=args.chunk_days - 1)); points = []
        for collector in collectors: points.extend(collector.fetch_history(cursor, chunk_end))
        with session_scope() as session: Repository(session).upsert_metrics(points)
        print(f"saved {cursor}..{chunk_end}: {len(points)} points"); cursor = chunk_end + timedelta(days=1); time.sleep(args.sleep)

if __name__ == "__main__": main()

