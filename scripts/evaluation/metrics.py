"""Pure metrics. UNKNOWN gold is excluded only from binary metrics."""
from __future__ import annotations

from collections import Counter

from .data import BACKEND_TO_RISK_FACTOR, EVALUATED_CODES, STATES

POLICIES = {"present": {"PRESENT"}, "present_boundary": {"PRESENT", "BOUNDARY"}}
EVIDENCE_POLICY = "whitespace_substring_grounded_complaint_v1"


def safe_divide(numerator, denominator):
    return numerator / denominator if denominator else 0.0


def rate(numerator, denominator):
    return numerator / denominator if denominator else None


def binary_metrics(rows, policy):
    positives = POLICIES[policy]
    counts = dict(tp=0, fp=0, fn=0, tn=0)
    unknown = 0
    for row in rows:
        if row["gold_state"] == "UNKNOWN":
            unknown += 1
            continue
        gold = row["gold_state"] in positives
        pred = row["predicted_state"] in positives
        counts["tp" if gold and pred else "fn" if gold else "fp" if pred else "tn"] += 1
    n = sum(counts.values())
    tp, fp, fn = counts["tp"], counts["fp"], counts["fn"]
    return {**counts, "evaluated_labels": n, "excluded_gold_unknown": unknown,
            "gold_positive": tp + fn, "predicted_positive": tp + fp,
            "precision": safe_divide(tp, tp + fp) if n else None,
            "recall": safe_divide(tp, tp + fn) if n else None,
            "f1": safe_divide(2 * tp, 2 * tp + fp + fn) if n else None}


def calculate_present_metrics(gold_states, predicted_states):
    if len(gold_states) != len(predicted_states):
        raise ValueError("gold/prediction lengths differ")
    return binary_metrics([{"gold_state": g, "predicted_state": p}
                           for g, p in zip(gold_states, predicted_states)], "present")


def confusion(rows):
    matrix = {gold: {pred: 0 for pred in STATES} for gold in STATES}
    for row in rows:
        matrix[row["gold_state"]][row["predicted_state"]] += 1
    return matrix


def evidence_match(gold_evidence, predicted_evidences):
    """Legacy normalized substring criterion; grounding is checked separately."""
    if not gold_evidence:
        return ""
    if not predicted_evidences:
        return "NO_PREDICTED_EVIDENCE"
    gold = "".join(gold_evidence.split())
    for text in predicted_evidences:
        pred = "".join(text.split())
        if gold and pred and (gold in pred or pred in gold):
            return "MATCH"
    return "MISMATCH"


def evidence_columns(label, tag, complaint):
    gold = label["evidence_span"]
    texts = [span["text"] for span in tag.get("evidenceSpans", [])] if tag else []
    grounded = [text for text in texts if text in complaint]
    eligible = label["status"] in ("PRESENT", "BOUNDARY") and bool(gold) and gold in complaint
    exclusion = ("" if eligible else "gold_state_not_present_or_boundary"
                 if label["status"] not in ("PRESENT", "BOUNDARY") else "gold_evidence_missing"
                 if not gold else "gold_evidence_not_in_complaint")
    return {"gold_evidence": gold, "predicted_evidence": " | ".join(texts),
            "evidence_evaluable": int(eligible), "evidence_exclusion_reason": exclusion,
            "evidence_match": evidence_match(gold, grounded) if eligible else "NOT_EVALUABLE",
            "predicted_span_count": len(texts), "grounded_span_count": len(grounded),
            "predicted_evidence_in_source": int(len(texts) == len(grounded)) if texts else None}


def compute_metrics(rows, case_count, policies=("present", "present_boundary")):
    in_scope = [r for r in rows if r["evaluation_in_scope"]]
    successful = [r for r in in_scope if r["request_success"]]
    per_tag = {}
    for code in EVALUATED_CODES:
        selected = [r for r in successful if r["code"] == code]
        per_tag[code] = {
            "evaluated_labels": len(selected),
            "exact_state_accuracy": rate(sum(r["state_match"] for r in selected), len(selected)),
            "confusion_matrix": confusion(selected),
            "binary": {policy: binary_metrics(selected, policy) for policy in policies},
        }
    binary = {}
    for policy in policies:
        available = [per_tag[code]["binary"][policy] for code in EVALUATED_CODES
                     if per_tag[code]["binary"][policy]["evaluated_labels"]]
        binary[policy] = {"micro": binary_metrics(successful, policy),
                          "macro_precision": rate(sum(m["precision"] for m in available), len(available)),
                          "macro_recall": rate(sum(m["recall"] for m in available), len(available)),
                          "macro_f1": rate(sum(m["f1"] for m in available), len(available)),
                          "macro_tag_denominator": len(available)}
    cases = {}
    for row in successful:
        cases.setdefault(row["case_id"], []).append(row)
    complete = [items for items in cases.values() if {r["code"] for r in items} == set(EVALUATED_CODES)]
    perfect = sum(all(r["state_match"] for r in items) for items in complete)
    evidence_rows = [r for r in successful if r["evidence_evaluable"]]
    matched = sum(r["evidence_match"] == "MATCH" for r in evidence_rows)
    spans = sum(r["predicted_span_count"] for r in successful)
    grounded = sum(r["grounded_span_count"] for r in successful)
    return {
        "per_tag": per_tag, "binary": binary, "confusion_matrix": confusion(successful),
        "tag_exact_match": {"matched": sum(r["state_match"] for r in successful),
                            "denominator": len(successful),
                            "rate": rate(sum(r["state_match"] for r in successful), len(successful))},
        "all_tags_exact_match": {"matched_cases": perfect, "successful_complete_cases": len(complete),
                                 "rate": rate(perfect, len(complete)), "requested_cases": case_count,
                                 "requested_case_rate": rate(perfect, case_count)},
        "denominators": {"requested_cases": case_count, "successful_cases": len(cases),
                         "successful_labels": len(successful),
                         "failed_labels": len(in_scope) - len(successful),
                         "out_of_scope_labels": len(rows) - len(in_scope)},
        "evidence": {"policy": EVIDENCE_POLICY, "matched_labels": matched,
                     "evaluable_labels": len(evidence_rows), "match_rate": rate(matched, len(evidence_rows)),
                     "excluded_labels": len(successful) - len(evidence_rows),
                     "exclusion_reasons": dict(Counter(r["evidence_exclusion_reason"] for r in successful
                                                       if not r["evidence_evaluable"])),
                     "predicted_spans": spans, "grounded_spans": grounded,
                     "ungrounded_spans": spans - grounded, "grounding_rate": rate(grounded, spans)},
    }


def build_tag_metrics(rows, *, review_required=None):
    """Compatibility CSV: old present_* columns plus explicit binary denominators."""
    if review_required is not None:
        rows = [r for r in rows if r.get("review_required") == review_required]
    metrics = compute_metrics(rows, len({r["case_id"] for r in rows}))
    result = []
    for code, metric in metrics["per_tag"].items():
        present = metric["binary"]["present"]
        boundary = metric["binary"]["present_boundary"]
        tag_rows = [r for r in rows if r["code"] == code and r["request_success"]]
        gold_counts = Counter(r["gold_state"] for r in tag_rows)
        pred_counts = Counter(r["predicted_state"] for r in tag_rows)
        result.append({"code": code, "risk_factor": BACKEND_TO_RISK_FACTOR[code],
                       "evaluated_cases": metric["evaluated_labels"],
                       "exact_state_accuracy": metric["exact_state_accuracy"],
                       "present_precision": present["precision"], "present_recall": present["recall"],
                       "present_f1": present["f1"], "tp": present["tp"], "fp": present["fp"],
                       "fn": present["fn"], "tn": present["tn"],
                       "binary_evaluated_labels": present["evaluated_labels"],
                       "excluded_gold_unknown": present["excluded_gold_unknown"],
                       "present_boundary_precision": boundary["precision"],
                       "present_boundary_recall": boundary["recall"], "present_boundary_f1": boundary["f1"],
                       **{"gold_" + state.lower(): gold_counts[state] for state in STATES},
                       **{"pred_" + state.lower(): pred_counts[state] for state in STATES}})
    return result
