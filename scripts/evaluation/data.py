"""Dataset adapters and validation shared by evaluation and data checks."""
from __future__ import annotations

import csv
import hashlib
import json
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

RISK_FACTOR_TO_BACKEND = {
    "GENERAL_PROFANITY_EMOTION": "PROFANITY",
    "DIRECT_INSULT_PERSONAL_ATTACK": "INSULT",
    "THREAT_INTIMIDATION": "THREAT",
    "LEGAL_ADMIN_ACTION_MENTION": "LEGAL",
    "PUBLIC_DISCLOSURE_THREAT": "EXPOSURE",
    "REPETITION": "REPEAT",
    "UNREASONABLE_DEMAND": "UNFAIR_REQUEST",
    "PERSONAL_INFO_MISUSE_RISK": "PRIVACY",
}
BACKEND_CODES = list(RISK_FACTOR_TO_BACKEND.values())
BACKEND_TO_RISK_FACTOR = {v: k for k, v in RISK_FACTOR_TO_BACKEND.items()}
STATES = ("PRESENT", "ABSENT", "BOUNDARY", "UNKNOWN")
ALLOWED_STATES = set(STATES)
EVALUATED_CODES = [code for code in BACKEND_CODES if code != "REPEAT"]
FILENAMES = {
    "dev": ("teachercare_dev_cases_100.csv", "teachercare_dev_risk_labels_100.csv"),
    "goldenset": ("TeacherCare_goldenset_200cases.csv", "TeacherCare_goldenset_200risktages.csv"),
}


def clean(value):
    return (value or "").strip()


def json_hash(value):
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")).hexdigest()


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_csv(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        headers = reader.fieldnames or []
        if not headers or len(headers) != len(set(headers)) or any(not h for h in headers):
            raise ValueError(f"{path}: empty or duplicate CSV headers")
        rows = []
        for number, row in enumerate(reader, 2):
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"{path}:{number}: malformed CSV row")
            rows.append({key: clean(value) for key, value in row.items()})
        return headers, rows


def require_columns(headers, required, path):
    missing = set(required) - set(headers)
    if missing:
        raise ValueError(f"{path}: missing columns: {', '.join(sorted(missing))}")


def load_cases(path):
    headers, rows = read_csv(path)
    require_columns(headers, {"case_id", "message_text"}, path)
    if not rows:
        raise ValueError(f"{path}: no cases")
    ids = Counter(row["case_id"] for row in rows)
    if ids.get("") or any(not row["message_text"] for row in rows):
        raise ValueError(f"{path}: blank case_id or message_text")
    if any(count > 1 for count in ids.values()):
        raise ValueError(f"{path}: duplicate case_id")
    return rows


def load_labels(path, schema="auto"):
    headers, rows = read_csv(path)
    if schema == "auto":
        schema = "goldenset" if "riskTagCode" in headers else "dev"
    code_key, state_key, evidence_key = (
        ("riskTagCode", "state", "evidence") if schema == "goldenset"
        else ("risk_factor", "status", "evidence_span")
    )
    require_columns(headers, {"case_id", code_key, state_key, evidence_key}, path)
    result = {}
    for source in rows:
        case_id, raw_code = source["case_id"], source[code_key]
        code = raw_code if schema == "goldenset" else RISK_FACTOR_TO_BACKEND.get(raw_code)
        if not case_id or code not in BACKEND_CODES:
            raise ValueError(f"{path}: blank case_id or invalid tag code")
        if source[state_key] not in ALLOWED_STATES:
            raise ValueError(f"{case_id}/{code}: invalid label state")
        if code in result.setdefault(case_id, {}):
            raise ValueError(f"{case_id}/{code}: duplicate label")
        row = dict(source)
        row.update(backend_code=code, risk_factor=BACKEND_TO_RISK_FACTOR[code],
                   status=source[state_key], evidence_span=source[evidence_key])
        if schema == "goldenset":
            row["review_group"] = (
                "teacher_reviewed" if source.get("teacher_review_status") == "TEACHER_REVIEWED_1P"
                else "unconfirmed"
            )
        else:
            row["review_group"] = (
                "dev_stable_ai" if source.get("review_required") == "NO" else "dev_review_required"
            )
        result[case_id][code] = row
    return result


def ensure_complete_labels(cases, labels, schema="dev"):
    case_ids = {case["case_id"] for case in cases}
    if set(labels) - case_ids:
        raise ValueError("orphan labels: " + ", ".join(sorted(set(labels) - case_ids)))
    for case in cases:
        case_id = case["case_id"]
        if set(labels.get(case_id, {})) != set(BACKEND_CODES):
            raise ValueError(f"{case_id}: expected exactly 8 labels")
        if schema == "goldenset":
            for code in BACKEND_CODES:
                if case.get(code) not in ALLOWED_STATES:
                    raise ValueError(f"{case_id}/{code}: missing or invalid wide state")
                if case[code] != labels[case_id][code]["status"]:
                    raise ValueError(f"{case_id}/{code}: golden CSV state disagreement")


@dataclass
class Dataset:
    schema: str
    cases: list
    labels: dict
    paths: tuple
    file_hashes: dict

    @property
    def hashes(self):
        return dict(self.file_hashes)

    @property
    def digest(self):
        return json_hash(self.hashes)


def load_dataset(data_dir, schema="auto"):
    directory = Path(data_dir)
    if schema == "auto":
        matches = [name for name, files in FILENAMES.items()
                   if all((directory / file).is_file() for file in files)]
        if len(matches) != 1:
            raise ValueError(f"{directory}: cannot uniquely detect dataset schema")
        schema = matches[0]
    paths = tuple(directory / file for file in FILENAMES[schema])
    cases, labels = load_cases(paths[0]), load_labels(paths[1], schema)
    ensure_complete_labels(cases, labels, schema)
    return Dataset(schema, cases, labels, paths, {path.name: file_hash(path) for path in paths})


def normalize_message(text):
    """NFKC plus removal of all Unicode whitespace; not used for model input."""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))


def check_disjoint(left_cases, right_cases):
    left_ids = {case["case_id"] for case in left_cases}
    right_ids = {case["case_id"] for case in right_cases}
    right_text = {}
    for case in right_cases:
        right_text.setdefault(normalize_message(case["message_text"]), []).append(case["case_id"])
    overlaps = []
    for case in left_cases:
        for other in right_text.get(normalize_message(case["message_text"]), []):
            overlaps.append({"case_id": case["case_id"], "other_case_id": other})
    return {"normalization": "nfkc_remove_unicode_whitespace_v1",
            "id_overlaps": sorted(left_ids & right_ids), "text_overlaps": overlaps,
            "passed": not (left_ids & right_ids) and not overlaps}
