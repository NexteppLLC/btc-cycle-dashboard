#!/usr/bin/env python
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from database.session import create_schema

if __name__ == "__main__":
    create_schema(); print("Database schema initialized.")

