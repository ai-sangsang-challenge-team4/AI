#!/usr/bin/env python3
"""Recover complete records without model calls or changes to strict replay parsing."""
import argparse
import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.evaluation.checkpoint import recover_checkpoint


def main(argv=None):
    parser = argparse.ArgumentParser(description="중단된 체크포인트의 완전한 JSONL 기록만 별도 파일로 복구")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        value = recover_checkpoint(args.input, args.output)
    except (ValueError, OSError) as exc:
        print(f"체크포인트 복구 오류: {type(exc).__name__}", file=sys.stderr)
        return 2
    print(json.dumps(value, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
