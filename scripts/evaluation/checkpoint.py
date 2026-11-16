"""Explicit prefix recovery for interrupted JSONL checkpoints, never ordinary replay."""
from __future__ import annotations

import json
import math
from pathlib import Path


def read_checkpoint(path):
    lines = Path(path).read_bytes().splitlines(keepends=True)
    records, seen, ignored_tail = [], set(), False
    def invalid_constant(value):
        raise ValueError("non-finite checkpoint JSON")
    def finite_float(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("non-finite checkpoint JSON")
        return number
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            record = json.loads(line.decode("utf-8"), parse_constant=invalid_constant, parse_float=finite_float)
        except (UnicodeDecodeError, json.JSONDecodeError):
            if index == len(lines) - 1 and not line.endswith(b"\n"):
                ignored_tail = True
                break
            raise ValueError("corrupt complete checkpoint record") from None
        if (not isinstance(record, dict) or not isinstance(record.get("case_id"), str)
                or not record["case_id"] or record["case_id"] in seen
                or type(record.get("request_success")) is not int or record["request_success"] not in (0, 1)
                or "response" not in record):
            raise ValueError("invalid or duplicate checkpoint record")
        seen.add(record["case_id"])
        records.append(record)
    return records, ignored_tail


def recover_checkpoint(source, destination):
    records, ignored_tail = read_checkpoint(source)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x", encoding="utf-8") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
    return {"recovered_records": len(records), "ignored_incomplete_final_record": ignored_tail,
            "output": str(destination)}
