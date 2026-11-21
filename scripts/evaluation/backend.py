"""Capture the public Backend flow without sending complaints or copying its engine.

Only complaint text enters a draft. Golden labels/history never enter requests.
The append-only journal records mutations before sending them: ambiguous POSTs
are not retried automatically. Tokens/passwords never enter artifacts or errors.
"""
from __future__ import annotations

import fcntl
import json
import math
import os
import threading
import time
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .contracts import ContractError, validate_tags
from .data import BACKEND_CODES, file_hash, json_hash
from .reporting import write_csv, write_json
from .supplemental import LEVELS

INPUT_SCOPE = 'isolated_draft; golden complaint only; no golden history/regulation/labels'
DEV_INPUT_SCOPE = 'isolated_draft; development complaint only; no development history/regulation/labels'


class BackendError(RuntimeError):
    """A stable error code, never an HTTP body or upstream exception."""


class BackendInputError(ValueError):
    """A fixed, user-actionable message; never interpolate external values."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class BackendClient:
    def __init__(self, base_url, email, password, *, timeout=180, opener=None):
        url = urlsplit(base_url)
        if (url.scheme not in ('http', 'https') or not url.hostname
                or url.username or url.password or url.query or url.fragment
                or url.path not in ('', '/')
                or (url.scheme != 'https' and url.hostname not in ('localhost', '127.0.0.1'))):
            raise BackendInputError('Backend URL must be an HTTPS origin (HTTP only for localhost)')
        if not email or not password or not math.isfinite(timeout) or timeout <= 0:
            raise BackendInputError('Credentials and a positive finite timeout are required')
        self.base_url = base_url.rstrip('/')
        self.email, self.password, self.timeout = email, password, timeout
        self.opener = opener or build_opener(NoRedirect())
        self.token, self.expiry = None, 0
        self.auth_lock = threading.Lock()

    def _request(self, method, path, payload=None, token=None):
        headers = {'Accept': 'application/json', 'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = 'Bearer ' + token
        data = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode() if payload is not None else None
        request = Request(self.base_url + path, data=data, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                raw = response.read(2_000_001)
                if len(raw) > 2_000_000:
                    raise BackendError('backend:response_too_large')
                value = json.loads(raw.decode('utf-8'))
        except HTTPError as error:
            raise BackendError(f'backend:http_{error.code}') from None
        except (URLError, TimeoutError, OSError):
            raise BackendError('backend:connection_or_timeout') from None
        except (ValueError, UnicodeDecodeError):
            raise BackendError('backend:invalid_json') from None
        if not isinstance(value, (dict, list)):
            raise BackendError('backend:invalid_json_shape')
        return value

    def login(self):
        with self.auth_lock:
            if self.token and time.monotonic() < self.expiry:
                return
            session = self._request('POST', '/auth/login', {'email': self.email, 'password': self.password})
            if not isinstance(session, dict) or not isinstance(session.get('accessToken'), str) or not session['accessToken']:
                raise BackendError('backend:invalid_login_response')
            seconds = session.get('expiresIn', 300)
            if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds <= 0:
                raise BackendError('backend:invalid_token_expiry')
            self.token = session['accessToken']
            self.expiry = time.monotonic() + max(1, seconds - 30)

    def call(self, method, path, payload=None, *, before_send=None):
        self.login()
        # Authenticate before a durable mutation intent; never refresh again after it.
        if before_send is not None:
            before_send()
        return self._request(method, path, payload, self.token)

    def context(self, student_id=None, teacher_id=None):
        me = self.call('GET', '/users/me')
        if not isinstance(me, dict) or me.get('role') != 'PARENT':
            raise BackendError('backend:parent_role_required')
        students = me.get('students', [])
        ids = [s.get('studentId') for s in students if isinstance(s, dict)]
        if student_id is None:
            if len(ids) != 1:
                raise BackendInputError('Specify --student-id when the account does not have exactly one student')
            student_id = ids[0]
        if type(student_id) is not int or student_id <= 0 or student_id not in ids:
            raise BackendInputError('Student does not belong to this account')
        teachers = self.call('GET', f'/complaints/recipients?studentId={student_id}')
        if not isinstance(teachers, list):
            raise BackendError('backend:invalid_recipient_response')
        if any(not isinstance(teacher, dict) for teacher in teachers):
            raise BackendError('backend:invalid_recipient_response')
        if teacher_id is None:
            homeroom = [t for t in teachers if t.get('homeroomTeacher') is True]
            candidates = homeroom if len(homeroom) == 1 else teachers
            if len(candidates) != 1:
                raise BackendInputError('Specify --teacher-id when there is no unique homeroom teacher')
            teacher_id = candidates[0].get('teacherId')
        if type(teacher_id) is not int or teacher_id <= 0 or teacher_id not in [t.get('teacherId') for t in teachers]:
            raise BackendInputError('Teacher is not an available recipient for this student')
        return {'student_id': student_id, 'teacher_id': teacher_id, 'account_sha256': json_hash(self.email)}


def validate_capture(record):
    summary, details = record.get('summary'), record.get('detectorResults')
    if not isinstance(summary, dict) or not isinstance(details, dict):
        raise ValueError('Capture requires summary and detectorResults')
    complaint_id, analysis_id = summary.get('complaintId'), summary.get('analysisId')
    if (type(complaint_id) is not int or complaint_id <= 0 or type(analysis_id) is not int or analysis_id <= 0
            or complaint_id != record.get('complaintId') or details.get('analysisId') != analysis_id):
        raise ValueError('Capture complaint/analysis IDs differ')
    if summary.get('riskLevel') not in LEVELS or type(summary.get('riskScore')) is not int or not 0 <= summary['riskScore'] <= 100:
        raise ValueError('Capture risk level/score is invalid')
    if summary.get('analysisMode') not in ('HYBRID', 'RULE_ONLY'):
        raise ValueError('Capture analysis mode is invalid')
    rows = details.get('results')
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError('Capture detector results are invalid')
    for view in ('rule', 'llm', 'final'):
        tags = []
        for row in rows:
            component = row.get('llm' if view == 'final' else view)
            if not isinstance(component, dict):
                raise ValueError('Capture detector component is invalid')
            tag = {'code': row.get('code'), **component}
            if view == 'final':
                tag['state'] = row.get('finalState')
            tags.append(tag)
        validate_tags(tags)
    flags = details.get('safetyFlags')
    if flags is not None and (not isinstance(flags, dict) or any(v is not None and type(v) is not bool for v in flags.values())):
        raise ValueError('Capture safety flags are invalid')
    return record


def model_succeeded(record):
    summary = record['summary']
    return summary['analysisMode'] == 'HYBRID' and summary.get('aiAnalysisStatus') in ('COMPLETED', 'REUSED')


class Journal:
    def __init__(self, path, header, *, resume=False):
        self.header = dict(header)
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = self.path.with_suffix('.lock').open('a')
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.lock.close()
            raise BackendInputError('This capture is already running') from None
        self.mutex, self.states = threading.Lock(), {}
        self.completed = {}
        if self.path.exists():
            if not resume:
                self.close()
                raise BackendInputError('Existing checkpoint requires --resume')
            try:
                lines = self.path.read_text(encoding='utf-8').splitlines()
                items = [json.loads(line) for line in lines]
                if not items or items[0] != header:
                    raise ValueError('Checkpoint belongs to a different dataset/account/selection')
                for item in items[1:]:
                    if not isinstance(item, dict):
                        raise ValueError('Checkpoint record must be an object')
                    case_id = item.get('case_id')
                    if case_id not in header['case_ids']:
                        raise ValueError('Unknown checkpoint case')
                    if item.get('stage') == 'complete':
                        validate_capture(item)
                    self._remember(item)
            except (ValueError, KeyError, ContractError):
                self.close()
                raise BackendInputError('Checkpoint invalid; restore it without repeating POST requests') from None
        else:
            with self.path.open('x', encoding='utf-8') as stream:
                stream.write(json.dumps(header, ensure_ascii=False, allow_nan=False) + '\n')
                stream.flush()
                os.fsync(stream.fileno())

    def append(self, record):
        # Only collector-produced fields enter this journal; never login responses.
        with self.mutex:
            with self.path.open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + '\n')
                stream.flush()
                os.fsync(stream.fileno())
            self._remember(dict(record))

    def _remember(self, record):
        case_id = record['case_id']
        self.states[case_id] = record
        if record.get('stage') == 'complete':
            self.completed[case_id] = record

    def close(self):
        fcntl.flock(self.lock, fcntl.LOCK_UN)
        self.lock.close()


class Collector:
    def __init__(self, client, journal, dataset, context, run_version):
        self.client, self.journal, self.dataset = client, journal, dataset
        self.context, self.run_version = context, run_version

    def retry_fallbacks(self, cases):
        """Explicit opt-in: a cached Rule-only draft needs a NEW draft to call AI again."""
        validate_checkpoint_inputs(self.journal.states, cases)
        count = 0
        for case in cases:
            old = self.journal.states.get(case['case_id'], {})
            if old.get('stage') != 'complete' or model_succeeded(old):
                continue
            previous = list(old.get('previous_attempts', []))
            previous.append({'complaintId': old['complaintId'], 'analysisId': old['summary']['analysisId'],
                             'ai_status': old['summary'].get('aiAnalysisStatus'), 'analysis_mode': old['summary']['analysisMode']})
            self.journal.append({'case_id': case['case_id'], 'complaint_sha256': old['complaint_sha256'],
                                 'stage': 'retry_ready', 'attempt': old.get('attempt', 1) + 1,
                                 'previous_attempts': previous})
            count += 1
        return count

    def seed(self, path):
        value = json.loads(Path(path).read_text(encoding='utf-8'))
        case_id = value.get('case_id')
        cases = {case['case_id']: case for case in self.dataset.cases}
        if value.get('dataset_sha256') != self.dataset.digest or case_id not in cases:
            raise BackendInputError('Smoke capture belongs to a different dataset')
        if case_id not in self.journal.header['case_ids']:
            raise BackendInputError('Smoke capture is outside the selected case selection')
        if value.get('base_url') != self.client.base_url or value.get('complaint_sent') is not False:
            raise BackendInputError('Only an unsent smoke capture from this Backend can be reused')
        if case_id in self.journal.states:
            return
        validate_capture(value)
        owned = self.client.call('GET', f"/complaints/{value['complaintId']}")
        if (not isinstance(owned, dict) or owned.get('content') != cases[case_id]['message_text']
                or owned.get('status') != 'DRAFT' or owned.get('studentId') != self.context['student_id']):
            raise BackendInputError('Smoke capture is not an owned, matching evaluation draft')
        record = {key: value[key] for key in ('case_id', 'complaintId', 'latency_ms', 'summary', 'detectorResults')}
        record.update(stage='complete', complaint_sha256=json_hash(cases[case_id]['message_text']),
                      capture_source='previous_smoke', seed_sha256=file_hash(path), complaint_sent=False)
        self.journal.append(record)

    def collect_one(self, case):
        case_id = case['case_id']
        state = dict(self.journal.states.get(case_id, {}))
        digest = json_hash(case['message_text'])
        if state and state.get('complaint_sha256') != digest:
            raise BackendInputError('Checkpoint complaint input differs')
        if state.get('stage') == 'complete':
            return state
        if state.get('stage') in ('creating', 'analyzing'):
            raise ValueError(f'{case_id}: ambiguous POST; inspect the existing draft before retrying')
        if not state or state.get('stage') == 'retry_ready':
            state = {**state, 'case_id': case_id, 'complaint_sha256': digest, 'stage': 'creating'}
            payload = {'studentId': self.context['student_id'], 'teacherId': self.context['teacher_id'],
                       'title': f'[평가 {self.run_version[:40]}] {case_id}', 'content': case['message_text']}
            created = self.client.call('POST', '/complaints', payload,
                                       before_send=lambda: self.journal.append(state))
            complaint_id = created.get('complaintId') if isinstance(created, dict) else None
            if type(complaint_id) is not int or complaint_id <= 0:
                raise BackendError('backend:invalid_created_draft')
            state.update(stage='draft', complaintId=complaint_id, draft_created_at=datetime.now(timezone.utc).isoformat())
            self.journal.append(state)
        if state['stage'] == 'draft':
            state.update(stage='analyzing', analysis_started_at=datetime.now(timezone.utc).isoformat())
            started = time.perf_counter()
            summary = self.client.call('POST', f"/complaints/{state['complaintId']}/risk-analysis",
                                       before_send=lambda: self.journal.append(state))
            if not isinstance(summary, dict) or type(summary.get('analysisId')) is not int:
                raise BackendError('backend:invalid_analysis_summary')
            state.update(stage='analyzed', summary=summary, latency_ms=(time.perf_counter() - started) * 1000)
            self.journal.append(state)
        if state['stage'] != 'analyzed':
            raise BackendInputError('Invalid checkpoint stage')
        details = self.client.call('GET', f"/risk-analyses/{state['summary']['analysisId']}/detector-results")
        state.update(stage='complete', detectorResults=details, captured_at=datetime.now(timezone.utc).isoformat(),
                     capture_source='public_backend', complaint_sent=False)
        validate_capture(state)
        self.journal.append(state)
        return state

    def collect(self, cases, *, workers=1, progress=None):
        if workers not in (1, 2):
            raise BackendInputError('Use one or two workers')
        validate_checkpoint_inputs(self.journal.states, cases)
        pending = iter(case for case in cases if self.journal.states.get(case['case_id'], {}).get('stage') != 'complete')
        failures, completed, consecutive_fallbacks = [], 0, 0
        with ThreadPoolExecutor(max_workers=workers) as pool:
            active = {}
            def submit():
                case = next(pending, None)
                if case:
                    active[pool.submit(self.collect_one, case)] = case['case_id']
            for _ in range(workers):
                submit()
            halted = False
            while active:
                ready, _ = wait(active, return_when=FIRST_COMPLETED)
                for future in ready:
                    case_id = active.pop(future)
                    try:
                        record = future.result()
                        completed += 1
                        consecutive_fallbacks = 0 if model_succeeded(record) else consecutive_fallbacks + 1
                        if consecutive_fallbacks >= 3:
                            halted = True
                            failures.append({'case_id': case_id, 'error_code': 'backend:circuit_open_after_3_fallbacks'})
                        if progress:
                            progress({'case_id': case_id, 'completed_now': completed,
                                      'analysis_mode': record['summary']['analysisMode'],
                                      'ai_status': record['summary'].get('aiAnalysisStatus'),
                                      'latency_ms': round(record['latency_ms'])})
                    except (BackendError, ValueError, ContractError) as error:
                        # POST intent remains in the journal; never assume a timeout means no write.
                        halted = True
                        failures.append({'case_id': case_id, 'error_code': str(error) if isinstance(error, BackendError)
                                         else 'backend:capture_interrupted'})
                if not halted:
                    for _ in ready:
                        submit()
        return failures


def capture_header(dataset, cases, client, context):
    return {'schema_version': 1, 'type': 'backend_capture', 'dataset_sha256': dataset.digest,
            'base_url': client.base_url, **context, 'case_ids': [c['case_id'] for c in cases],
            'input_scope': INPUT_SCOPE if dataset.schema == 'goldenset' else DEV_INPUT_SCOPE,
            'complaints_sent': False}


def validate_checkpoint_inputs(states, cases):
    for case in cases:
        state = states.get(case['case_id'])
        if state is not None and state.get('complaint_sha256') != json_hash(case['message_text']):
            raise BackendInputError('Checkpoint complaint input differs')


def captured_risk_rows(targets, states, selected_ids):
    rows = []
    for case_id in selected_ids:
        target = targets.get(case_id, {})
        if target.get('review_status') != 'CONFIRMED' or not target.get('risk_level'):
            continue
        state = states.get(case_id, {})
        complete = state.get('stage') == 'complete'
        rows.append({'case_id': case_id, 'gold_risk_level': target['risk_level'],
                     'predicted_risk_level': state['summary']['riskLevel'] if complete else '',
                     'is_legitimate': target['is_legitimate'], 'success': int(complete),
                     'error': '' if complete else 'backend_capture_incomplete'})
    return rows


def export_capture(directory, journal, dataset, cases, *, failures=(), backend_source_commit=None):
    """Export three views of the SAME responses; this performs no network calls."""
    validate_checkpoint_inputs(journal.states, cases)
    directory = Path(directory)
    selected = [case['case_id'] for case in cases]
    # An in-progress retry can supersede the checkpoint stage before it supplies a new result.
    states = {cid: journal.completed[cid] for cid in selected if cid in journal.completed}
    validate_checkpoint_inputs(states, cases)
    failed = {item['case_id']: item['error_code'] for item in failures}
    unattempted = [cid for cid in selected if cid not in journal.states and cid not in failed]
    rules, predictions = {}, {view: [] for view in ('rule', 'llm', 'final')}
    mapping = []
    for case in cases:
        cid = case['case_id']
        state = states.get(cid)
        if not state:
            if cid in failed:
                for values in predictions.values():
                    values.append({'case_id': cid, 'mode': 'rule_llm', 'attempt': 1,
                                   'source_provenance_verified': False, 'request_success': 0,
                                   'error_code': 'request:' + failed[cid].removeprefix('backend:'),
                                   'response': None})
            continue
        validate_capture(state)
        details, summary = state['detectorResults'], state['summary']
        rules[cid] = [{'code': row['code'], **row['rule']} for row in details['results']]
        mapping.append({'case_id': cid, 'complaint_id': state['complaintId'], 'analysis_id': summary['analysisId'],
                        'analysis_mode': summary['analysisMode'], 'ai_status': summary.get('aiAnalysisStatus'),
                        'predicted_risk_level': summary['riskLevel'], 'risk_score': summary['riskScore'],
                        'latency_ms': state['latency_ms'], 'complaint_sent': False})
        for view in predictions:
            tags = []
            for row in details['results']:
                tag = {'code': row['code'], **row['llm' if view == 'final' else view]}
                if view == 'final':
                    # Final evidence is not exposed by detector-results. Do not attribute LLM evidence to Rule.
                    tag['state'] = row['finalState']
                    tag['evidenceSpans'] = []
                tags.append(tag)
            success = view != 'llm' or model_succeeded(state)
            metadata = dict(details.get('llm') or {})
            if view == 'rule':
                metadata = {'modelName': 'backend-rule-captured', 'temperature': None}
            metadata['backendCapture'] = {'prediction_view': view, 'complaintId': state['complaintId'],
                                           'analysisId': summary['analysisId'], 'analysisMode': summary['analysisMode']}
            predictions[view].append({'case_id': cid, 'mode': 'rule_llm', 'attempt': 1,
                                      'source_provenance_verified': False,
                                      'latency_ms': state['latency_ms'], 'request_success': int(success),
                                      'error_code': '' if success else 'request:backend_rule_only',
                                      'response': {'tags': tags, 'metadata': metadata, 'safetyFlags': details.get('safetyFlags')}})
    # Explicitly empty rules for unattempted cases allow replay to record them as failures, not fabricate predictions.
    for cid in selected:
        rules.setdefault(cid, [])
    write_json(directory / 'captured_rules.json', rules)
    write_csv(directory / 'backend_cases.csv', mapping,
              ['case_id', 'complaint_id', 'analysis_id', 'analysis_mode', 'ai_status', 'predicted_risk_level',
               'risk_score', 'latency_ms', 'complaint_sent'])
    for view, values in predictions.items():
        with (directory / f'{view}_predictions.jsonl').open('w', encoding='utf-8') as stream:
            for value in values:
                stream.write(json.dumps(value, ensure_ascii=False, allow_nan=False) + '\n')
    manifest = {'schema_version': 1, 'dataset_schema': dataset.schema, 'dataset_sha256': dataset.digest, 'selected_cases': len(cases),
                'captured_cases': len(states), 'model_success_cases': sum(model_succeeded(s) for s in states.values()),
                'replaced_fallback_attempts': sum(len(s.get('previous_attempts', [])) for s in journal.states.values()),
                'capture_status': ('partial' if len(states) != len(cases) else 'complete'
                                   if all(model_succeeded(s) for s in states.values()) else 'complete_with_model_failures'),
                'analysis_modes': dict(Counter(s['summary']['analysisMode'] for s in states.values())),
                'collection_stage_counts': dict(Counter(
                    journal.states.get(cid, {}).get('stage', 'failed_before_intent' if cid in failed else 'not_started')
                    for cid in selected)),
                'incomplete_case_ids': [cid for cid in selected if cid not in states],
                'not_started_case_ids': unattempted,
                'journal_sha256': file_hash(journal.path),
                'backend_source_commit': backend_source_commit, 'deployment_verified': False,
                'rule_version': 'server_unreported', 'prompt_version': 'server_unreported',
                'rag_version': 'server_unreported', 'actual_generation_settings': None,
                'note': 'Repository HEAD is not proof of deployment; temperature metadata is not SDK provenance.',
                'input_scope': journal.header['input_scope'],
                'source_provenance_verified': False, 'masked_model_input_captured': False,
                'comparison_kind': 'same_capture_rule_vs_hybrid_ablation; not prompt/model before-after',
                'final_evidence': 'unavailable in detector-results; final view evidence metrics disabled',
                'request_context': {key: journal.header[key] for key in ('base_url', 'student_id', 'teacher_id', 'account_sha256')},
                'school_context': 'single demo student/teacher; original case school_level is not supplied',
                'latency_scope': 'Backend analysis POST wall time; imported smoke may include detector GET'}
    write_json(directory / 'capture_manifest.json', manifest)
    return states, manifest
