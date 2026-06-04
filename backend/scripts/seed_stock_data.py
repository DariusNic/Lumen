"""One-shot historical seed of `stock_data`.

Pulls 5 years of OHLCV bars from yfinance for every ticker in `TICKERS`
(100 names by default) and upserts into Mongo. Idempotent — re-running
re-pulls and overwrites the same (ticker, date) rows rather than duplicating.

Usage (from `backend/`):
    python -u -m scripts.seed_stock_data
    python -u -m scripts.seed_stock_data --tickers AAPL,MSFT,NVDA
    python -u -m scripts.seed_stock_data --start 2020-01-01
    python -u -m scripts.seed_stock_data --batch-size 25

The `-u` flag is recommended so progress prints stream live instead of
buffering to the end. Default batch size is 25 tickers per yfinance call —
batching reduces total HTTP calls without risking a single failure killing
the whole pull.

Network: ~30-60 s for the full 100-ticker pull on a normal connection.
"""
from __future__ import annotations

import argparse
import sys
import time

from app import create_app
from app.services import stock_data_service
from app.utils.constants import TICKERS, TRAIN_DATA_START


def _chunk(items: list[str], n: int) -> list[list[str]]:
    return [items[i:i + n] for i in range(0, len(items), n)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed stock_data from yfinance.")
    parser.add_argument(
        "--tickers",
        help="Comma-separated subset (default: all 100 from TICKERS)",
    )
    parser.add_argument("--start", default=TRAIN_DATA_START, help=f"Start date (default {TRAIN_DATA_START})")
    parser.add_argument("--end", default=None, help="End date (default today)")
    parser.add_argument("--batch-size", type=int, default=25,
                        help="Tickers per yfinance batch (default 25)")
    args = parser.parse_args(argv)

    if args.tickers:
        ticker_list = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    else:
        ticker_list = list(TICKERS)

    app = create_app()
    with app.app_context():
        print(f"Seeding {len(ticker_list)} ticker(s) from {args.start} to {args.end or 'today'}", flush=True)
        print(f"Batches of {args.batch_size}; per-row insert via insert_many(ordered=False).", flush=True)

        total_ok = 0
        total_failed = 0
        all_failed: list[str] = []
        total_written = 0
        t_start = time.time()

        for i, batch in enumerate(_chunk(ticker_list, args.batch_size), start=1):
            t0 = time.time()
            stats = stock_data_service.seed_history(batch, start=args.start, end=args.end)
            total_ok += stats["tickers_ok"]
            total_failed += stats["tickers_failed"]
            all_failed.extend(stats["failed_list"])
            total_written += stats["rows_written"]
            elapsed = time.time() - t0
            print(
                f"  [{i:2d}] {batch[0]:>5s}…{batch[-1]:<5s} "
                f"ok={stats['tickers_ok']:>2d}/{len(batch):<2d} "
                f"rows+{stats['rows_written']:>5d}  {elapsed:5.1f}s",
                flush=True,
            )

        total_elapsed = time.time() - t_start
        print(f"\nDone in {total_elapsed:.1f}s.", flush=True)
        print(f"  ok:     {total_ok}/{len(ticker_list)}", flush=True)
        print(f"  failed: {total_failed}", flush=True)
        if all_failed:
            print(f"          {', '.join(all_failed)}", flush=True)
        print(f"  rows written: {total_written}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
