"""Benchmark ground truth extraction — Phase 7."""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Print plan without executing")
    parser.add_argument("--limit", type=int, default=None, help="Cap items processed (smoke test)")
    args = parser.parse_args()
    if args.dry_run:
        print(f"[create_gt] dry-run — no side effects")
        return 0
    raise NotImplementedError("Implementation comes in plan 07-02")


if __name__ == "__main__":
    sys.exit(main())
