from __future__ import annotations

import json
import logging

from app.services.ai_service import AiService
from scripts.evaluation.data import BACKEND_CODES


def risk_output(states=None, evidence=None):
    """Synthetic structure, not severity/count/safety ground truth."""
    states, evidence = states or {}, evidence or {}
    tags = []
    for code in BACKEND_CODES:
        state = states.get(code, "UNKNOWN" if code == "REPEAT" else "ABSENT")
        tags.append({"code": code, "state": state, "confidence": None,
                     "severity": 1 if state == "PRESENT" else 0 if state == "ABSENT" else None,
                     "repeatCount": 1 if state == "PRESENT" else 0 if state == "ABSENT" else None,
                     "evidenceSpans": [{"text": text} for text in evidence.get(code, [])],
                     "reason": "synthetic_fixture"})
    return {"tags": tags, "safetyFlags": {"credibleThreat": None, "studentSafetyConcern": None, "privacyExposure": None}}


class FakeLlm:
    model = "claude-sonnet-4-6"
    generation_settings = {"max_tokens": 4096, "temperature": 0.0}

    def __init__(self, *outcomes, sdk_log=None):
        self.outcomes = outcomes or (json.dumps(risk_output()),)
        self.prompts = []
        self.sdk_log = sdk_log

    def generate(self, prompt):
        index = len(self.prompts)
        self.prompts.append(prompt)
        if self.sdk_log:
            logging.getLogger("anthropic.transport").error("%s", self.sdk_log)
        outcome = self.outcomes[min(index, len(self.outcomes) - 1)]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeRetriever:
    max_results, max_per_source, score_threshold, search_k = 3, 2, 0.35, 10

    def __init__(self, documents=None):
        self.documents = documents or []
        self.calls = []

    def search(self, text, **kwargs):
        self.calls.append((text, kwargs))
        return self.documents


def make_service(client=None, retriever=None):
    client = client or FakeLlm()
    retriever = retriever or FakeRetriever()
    return AiService(retriever=retriever, example_retriever=FakeRetriever(),
                     risk_llm_client=client, context_llm_client=client, revision_llm_client=client,
                     summary_llm_client=client, response_draft_llm_client=client)
