import json
import csv
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent

DATA_PATH = PROJECT_DIR / "data" / "context_examples.json"
OUTPUT_PATH = BASE_DIR / "summary_results" / "summary_gold.csv"

with open(DATA_PATH, "r", encoding="utf-8") as f:
    data = json.load(f)

with open(OUTPUT_PATH, "w", encoding="utf-8-sig", newline="") as f:
    writer = csv.writer(f)

    writer.writerow([
        "caseId",
        "message",
        "gold_summary",
    ])

    for case in data:
        writer.writerow([
            case["caseId"],
            case["message"],
            "",
        ])

print(f"Gold Summary 파일 생성:")
print(OUTPUT_PATH)
print(f"총 데이터: {len(data)}건")