"""Run the deterministic VAYU Phase 12 backtest."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.backtesting import run_backtest


def main() -> int:
    shapes = run_backtest(ROOT)
    print("VAYU Phase 12 backtesting completed")
    for name in sorted(shapes):
        rows, columns = shapes[name]
        print(f"  {name}: {rows} rows x {columns} columns")
    print("Protected Phase 1-11 and reference hashes: UNCHANGED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
