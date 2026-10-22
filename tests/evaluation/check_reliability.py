"""Provider-free regression fixture. PostgreSQL requires explicit disposable opt-in."""
import argparse
import json
from pathlib import Path

from reliability.fixture import run_fixture


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=["sqlite", "postgres"], default="sqlite")
    parser.add_argument("--report", type=Path)
    options = parser.parse_args()
    result = run_fixture(options.backend)
    if options.report:
        options.report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    negatives = sum(len(c["negative"]) for c in result["cases"])
    print(f"PASS {options.backend}: {len(result['cases'])} positive controls; {negatives} executed wrong-SQL controls rejected")
    print("Fixture/comparator proof only; no model accuracy, API/UI, or historical benchmark verdict")


if __name__ == "__main__":
    main()
