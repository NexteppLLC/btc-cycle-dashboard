#!/usr/bin/env python
from pathlib import Path
import logging, sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.report_service import generate_report
from services.update_service import run_update

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    result = run_update(); path = generate_report(result["snapshot"])
    print(f'Updated {result["points"]} points; report: {path}')

