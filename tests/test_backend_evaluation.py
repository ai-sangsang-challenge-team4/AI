"""Offline Backend capture: mutations, resumption, provenance and secret boundaries."""
import copy
import io
import json
import runpy
import tempfile
import threading
import unittest
from pathlib import Path
from contextlib import redirect_stderr
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

from scripts.evaluation.backend import (BackendClient, BackendError, Collector, Journal,
                                        captured_risk_rows, capture_header, export_capture, validate_capture,
                                        validate_checkpoint_inputs)
from scripts.evaluation.data import BACKEND_CODES, json_hash, load_dataset
from scripts.evaluate_backend_goldenset import build_parser, make_reports, main


def capture(case_id='G001', complaint_id=7, analysis_id=9, mode='HYBRID'):
    return {'case_id': case_id, 'stage': 'complete', 'complaintId': complaint_id, 'latency_ms': 123,
            'summary': {'complaintId': complaint_id, 'analysisId': analysis_id, 'riskLevel': 'LOW',
                        'riskScore': 0, 'analysisMode': mode,
                        'aiAnalysisStatus': 'COMPLETED' if mode == 'HYBRID' else 'RULE_ONLY_AI_UNAVAILABLE'},
            'detectorResults': {'analysisId': analysis_id, 'llm': {'modelName': 'test', 'temperature': 0},
                               'safetyFlags': None,
                               'results': [{'code': code, 'finalState': 'ABSENT',
                                            'rule': {'state': 'ABSENT', 'confidence': None, 'evidenceSpans': []},
                                            'llm': {'state': 'ABSENT', 'confidence': .9, 'severity': 0,
                                                    'repeatCount': 0, 'evidenceSpans': []}}
                                           for code in BACKEND_CODES]}}


class FakeClient:
    base_url = 'https://backend.invalid'
    email = 'test@example.com'

    def __init__(self, case, fail_analysis=False):
        self.case, self.calls, self.fail_analysis = case, [], fail_analysis

    def call(self, method, path, payload=None, *, before_send=None):
        if before_send is not None:
            before_send()
        self.calls.append((method, path, payload))
        if path == '/complaints' and method == 'POST':
            return {'complaintId': 7}
        if path == '/complaints/7/risk-analysis':
            if self.fail_analysis:
                raise BackendError('backend:connection_or_timeout')
            return copy.deepcopy(capture()['summary'])
        if path == '/risk-analyses/9/detector-results':
            return copy.deepcopy(capture()['detectorResults'])
        if path == '/complaints/7':
            return {'content': self.case['message_text'], 'status': 'DRAFT', 'studentId': 1}
        raise AssertionError('Unexpected endpoint')


class BackendCaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.dataset = load_dataset('data/goldenset', 'goldenset')
        self.case = self.dataset.cases[0]
        self.context = {'student_id': 1, 'teacher_id': 1, 'account_sha256': json_hash(FakeClient.email)}
        self.client = FakeClient(self.case)
        self.header = capture_header(self.dataset, [self.case], self.client, self.context)

    def journal(self, resume=False, header=None):
        journal = Journal(self.root / 'checkpoint.jsonl', header or self.header, resume=resume)
        self.addCleanup(lambda: None if journal.lock.closed else journal.close())
        return journal

    def test_actual_flow_never_sends_golden_labels_history_or_submits_a_complaint(self):
        journal = self.journal()
        record = Collector(self.client, journal, self.dataset, self.context, 'test').collect_one(self.case)
        self.assertEqual([call[:2] for call in self.client.calls], [
            ('POST', '/complaints'), ('POST', '/complaints/7/risk-analysis'),
            ('GET', '/risk-analyses/9/detector-results')])
        payload = self.client.calls[0][2]
        self.assertEqual(set(payload), {'studentId', 'teacherId', 'title', 'content'})
        self.assertEqual(payload['content'], self.case['message_text'])
        self.assertFalse(record['complaint_sent'])
        stages = [json.loads(line).get('stage') for line in journal.path.read_text().splitlines()[1:]]
        self.assertEqual(stages, ['creating', 'draft', 'analyzing', 'analyzed', 'complete'])

    def test_development_mode_captures_and_replays_dev_without_sending_labels(self):
        dataset = load_dataset('data/dev', 'dev')
        case = dataset.cases[0]
        client = FakeClient(case)
        credentials = self.root / 'credentials.json'
        credentials.write_text(json.dumps({'email': FakeClient.email, 'password': 'synthetic-only'}))
        command = ['--dataset', 'dev', '--capture-dir', str(self.root / 'dev-capture'),
                   '--report-dir', str(self.root / 'dev-reports'), '--limit', '1',
                   '--credentials-file', str(credentials), '--run-version', 'dev-before']
        with patch('scripts.evaluate_backend_goldenset.BackendClient', return_value=client), \
                patch.object(client, 'context', return_value=self.context, create=True):
            self.assertEqual(main(command), 0)
        self.assertEqual(client.calls[0][2]['content'], case['message_text'])
        self.assertEqual(set(client.calls[0][2]), {'studentId', 'teacherId', 'title', 'content'})
        index = json.loads((self.root / 'dev-capture/report_index.json').read_text())
        self.assertEqual(index['dataset_schema'], 'dev')
        final = json.loads((Path(index['reports']['final']) / 'manifest.json').read_text())
        self.assertEqual(final['dataset_schema'], 'dev')
        self.assertIn('development complaint only', final['backend_capture']['input_scope'])
        self.assertEqual(final['backend_capture']['gold_standard_acceptance']['status'], 'dataset_metadata')
        lines = (self.root / 'dev-capture/checkpoint.jsonl').read_text().splitlines()
        self.assertEqual(json.loads(lines[0])['case_ids'], [case['case_id']])
        self.assertTrue(case['case_id'].startswith('DEV'))
        with patch('scripts.evaluate_backend_goldenset.BackendClient') as no_network:
            self.assertEqual(main(command + ['--replay-only']), 0)
            no_network.assert_not_called()
            self.assertEqual(main(command + ['--replay-only', '--previous-final', index['reports']['final']]), 0)
            compared = json.loads((self.root / 'dev-capture/report_index.json').read_text())
            diff = json.loads((Path(compared['reports']['final']) / 'diff.json').read_text())
            self.assertEqual(diff['paired_cases'], 1)
            self.assertEqual(diff['previous_run'], index['reports']['final'])
            no_network.assert_not_called()
            with self.assertRaisesRegex(ValueError, 'dataset/selection differs'):
                wrong = list(command)
                wrong[1] = 'goldenset'
                main(wrong + ['--replay-only'])

    def test_resume_complete_never_repeats_any_request(self):
        journal = self.journal()
        Collector(self.client, journal, self.dataset, self.context, 'test').collect_one(self.case)
        journal.close()
        resumed = self.journal(resume=True)
        self.client.calls.clear()
        Collector(self.client, resumed, self.dataset, self.context, 'test').collect_one(self.case)
        self.assertEqual(self.client.calls, [])

    def test_explicit_fallback_retry_creates_new_draft_and_preserves_failed_attempt(self):
        journal = self.journal()
        old = capture(mode='RULE_ONLY', complaint_id=6, analysis_id=8)
        old['complaint_sha256'] = json_hash(self.case['message_text'])
        journal.append(old)
        collector = Collector(self.client, journal, self.dataset, self.context, 'retry')
        self.assertEqual(collector.retry_fallbacks([self.case]), 1)
        record = collector.collect_one(self.case)
        self.assertEqual(record['complaintId'], 7)
        self.assertEqual(record['attempt'], 2)
        self.assertEqual(record['previous_attempts'][0]['complaintId'], 6)
        self.assertEqual(collector.retry_fallbacks([self.case]), 0)
        self.assertEqual(sum(method == 'POST' and path == '/complaints' for method, path, _ in self.client.calls), 1)

    def test_analysis_timeout_preserves_id_and_is_not_automatically_retried(self):
        journal = self.journal()
        self.client.fail_analysis = True
        collector = Collector(self.client, journal, self.dataset, self.context, 'test')
        with self.assertRaises(BackendError):
            collector.collect_one(self.case)
        self.assertEqual(journal.states['G001']['complaintId'], 7)
        self.assertEqual(journal.states['G001']['stage'], 'analyzing')
        self.client.calls.clear()
        with self.assertRaisesRegex(ValueError, 'ambiguous POST'):
            collector.collect_one(self.case)
        self.assertEqual(self.client.calls, [])

    def test_auth_refresh_failure_before_create_leaves_no_post_intent(self):
        self.check_auth_failure_resume('creating')

    def test_auth_refresh_failure_before_analysis_preserves_created_draft(self):
        self.check_auth_failure_resume('analyzing')

    def check_auth_failure_resume(self, failed_stage):
        journal = self.journal()
        remote = BackendClient(self.client.base_url, FakeClient.email, 'synthetic-password')
        fail_auth = True

        def request(method, path, payload=None, token=None):
            if path == '/auth/login':
                if fail_auth and (failed_stage == 'creating' or self.client.calls):
                    raise BackendError('backend:http_503')
                return {'accessToken': 'synthetic-token', 'expiresIn': 3600}
            result = self.client.call(method, path, payload)
            if path == '/complaints' and failed_stage == 'analyzing':
                remote.expiry = 0  # Expire the token between the two mutation requests.
            return result

        collector = Collector(remote, journal, self.dataset, self.context, 'auth-test')
        with patch.object(remote, '_request', side_effect=request):
            with self.assertRaisesRegex(BackendError, 'backend:http_503'):
                collector.collect_one(self.case)
            if failed_stage == 'creating':
                self.assertEqual(journal.states, {})
                self.assertEqual(self.client.calls, [])
            else:
                self.assertEqual(journal.states['G001']['stage'], 'draft')
                self.assertEqual(journal.states['G001']['complaintId'], 7)
                self.assertEqual([call[:2] for call in self.client.calls], [('POST', '/complaints')])
            # Resume from the durable journal after authentication recovers.
            journal.close()
            resumed = self.journal(resume=True)
            fail_auth = False
            result = Collector(remote, resumed, self.dataset, self.context, 'auth-test').collect_one(self.case)
        self.assertEqual(result['stage'], 'complete')
        self.assertEqual(sum(method == 'POST' and path == '/complaints' for method, path, _ in self.client.calls), 1)
        self.assertEqual(sum(method == 'POST' and path.endswith('/risk-analysis') for method, path, _ in self.client.calls), 1)

    def test_cli_shows_actual_checkpoint_errors_without_claiming_a_post_was_sent(self):
        journal = self.journal()
        errors = []
        try:
            Journal(journal.path, self.header, resume=True)
        except ValueError as error:
            errors.append(error)
        journal.close()
        try:
            Journal(journal.path, self.header)
        except ValueError as error:
            errors.append(error)
        try:
            validate_checkpoint_inputs({'G001': {'complaint_sha256': 'wrong'}}, [self.case])
        except ValueError as error:
            errors.append(error)
        self.assertEqual(len(errors), 3)
        for error in errors:
            status, output = run_cli_failure(error)
            self.assertEqual(status, 2)
            self.assertIn(str(error), output)
            self.assertNotIn('POST', output)

    def test_resume_after_summary_only_fetches_details(self):
        journal = self.journal()
        journal.append({'case_id': 'G001', 'complaintId': 7, 'stage': 'analyzed',
                        'complaint_sha256': json_hash(self.case['message_text']), 'latency_ms': 1,
                        'summary': capture()['summary']})
        Collector(self.client, journal, self.dataset, self.context, 'test').collect_one(self.case)
        self.assertEqual([call[:2] for call in self.client.calls], [('GET', '/risk-analyses/9/detector-results')])

    def test_checkpoint_rejects_wrong_dataset_account_or_selection(self):
        journal = self.journal()
        journal.close()
        for key, value in [('dataset_sha256', '0' * 64), ('account_sha256', '1' * 64), ('case_ids', ['G002'])]:
            with self.subTest(key=key):
                wrong = {**self.header, key: value}
                with self.assertRaises(ValueError):
                    self.journal(resume=True, header=wrong)

    def test_seed_checks_ownership_and_reuses_without_analysis(self):
        journal = self.journal()
        seed = capture()
        seed.update(dataset_sha256=self.dataset.digest, base_url=self.client.base_url, complaint_sent=False)
        path = self.root / 'smoke.json'
        path.write_text(json.dumps(seed))
        collector = Collector(self.client, journal, self.dataset, self.context, 'test')
        collector.seed(path)
        collector.collect_one(self.case)
        self.assertEqual([call[:2] for call in self.client.calls], [('GET', '/complaints/7')])

    def test_seed_outside_selection_cannot_poison_resumable_checkpoint(self):
        journal = self.journal()
        seed = capture(case_id='G002')
        seed.update(dataset_sha256=self.dataset.digest, base_url=self.client.base_url, complaint_sent=False)
        path = self.root / 'smoke.json'
        path.write_text(json.dumps(seed))
        with self.assertRaisesRegex(ValueError, 'selection'):
            Collector(self.client, journal, self.dataset, self.context, 'test').seed(path)
        self.assertEqual(self.client.calls, [])
        self.assertEqual(journal.states, {})
        journal.close()
        self.assertEqual(self.journal(resume=True).states, {})

    def test_collect_stops_new_work_after_three_consecutive_fallbacks(self):
        cases = self.dataset.cases[:5]
        journal = self.journal(header=capture_header(self.dataset, cases, self.client, self.context))
        collector = Collector(self.client, journal, self.dataset, self.context, 'test')
        processed = []

        def fallback(case):
            processed.append(case['case_id'])
            return capture(case_id=case['case_id'], mode='RULE_ONLY')

        with patch.object(collector, 'collect_one', side_effect=fallback):
            failures = collector.collect(cases, workers=1)
        self.assertEqual(processed, ['G001', 'G002', 'G003'])
        self.assertEqual(failures, [{'case_id': 'G003', 'error_code': 'backend:circuit_open_after_3_fallbacks'}])

    def test_collect_preserves_inflight_result_after_another_worker_fails(self):
        cases = self.dataset.cases[:3]
        journal = self.journal(header=capture_header(self.dataset, cases, self.client, self.context))
        collector = Collector(self.client, journal, self.dataset, self.context, 'test')
        first_failed = threading.Event()
        processed, progress = [], []

        def collect(case):
            processed.append(case['case_id'])
            if case['case_id'] == 'G001':
                first_failed.set()
                raise BackendError('backend:connection_or_timeout')
            self.assertTrue(first_failed.wait(5))
            record = capture(case_id=case['case_id'])
            record['complaint_sha256'] = json_hash(case['message_text'])
            journal.append(record)
            return record

        with patch.object(collector, 'collect_one', side_effect=collect):
            failures = collector.collect(cases, workers=2, progress=progress.append)
        self.assertEqual(set(processed), {'G001', 'G002'})
        self.assertEqual(failures, [{'case_id': 'G001', 'error_code': 'backend:connection_or_timeout'}])
        self.assertEqual(journal.states['G002']['stage'], 'complete')
        self.assertEqual([value['case_id'] for value in progress], ['G002'])

    def test_three_views_preserve_fallback_as_failed_llm_and_unknown_versions(self):
        journal = self.journal()
        record = capture(mode='RULE_ONLY')
        record['complaint_sha256'] = json_hash(self.case['message_text'])
        journal.append(record)
        states, manifest = export_capture(self.root, journal, self.dataset, [self.case])
        self.assertEqual(manifest['model_success_cases'], 0)
        self.assertIsNone(manifest['backend_source_commit'])
        self.assertFalse(manifest['deployment_verified'])
        self.assertEqual(manifest['capture_status'], 'complete_with_model_failures')
        for view in ('rule', 'llm', 'final'):
            value = json.loads((self.root / f'{view}_predictions.jsonl').read_text())
            self.assertEqual(value['request_success'], int(view != 'llm'))
            self.assertFalse(value['source_provenance_verified'])
            if view == 'final':
                self.assertTrue(all(tag['evidenceSpans'] == [] for tag in value['response']['tags']))
        args = build_parser().parse_args(['--capture-dir', str(self.root), '--report-dir', str(self.root / 'reports'),
                                          '--limit', '1', '--replay-only'])
        result = make_reports(args, self.dataset, [self.case], journal, states, manifest)
        self.assertEqual(result['views']['llm']['coverage']['failure_codes']['request:backend_rule_only'], 1)
        journal.close()
        with patch('scripts.evaluate_backend_goldenset.BackendClient') as client:
            status = main(['--capture-dir', str(self.root), '--report-dir', str(self.root / 'cli-reports'),
                           '--limit', '1', '--replay-only'])
            self.assertEqual(status, 1, 'A captured Rule-only result is not a successful AI evaluation')
            client.assert_not_called()

    def test_capture_requires_all_tags_and_matching_server_ids(self):
        wrong = capture()
        wrong['detectorResults']['results'].pop()
        with self.assertRaises(ValueError):
            validate_capture(wrong)
        wrong = capture()
        wrong['detectorResults']['analysisId'] = 123
        with self.assertRaises(ValueError):
            validate_capture(wrong)

    def test_no_final_risk_gold_is_invented_and_pending_targets_are_excluded(self):
        states = {'G001': capture()}
        self.assertEqual(captured_risk_rows({}, states, ['G001']), [])
        target = {'review_status': 'PENDING', 'risk_level': 'LOW', 'is_legitimate': 'TRUE'}
        self.assertEqual(captured_risk_rows({'G001': target}, states, ['G001']), [])
        target['review_status'] = 'CONFIRMED'
        rows = captured_risk_rows({'G001': target}, states, ['G001'])
        self.assertEqual(rows[0]['predicted_risk_level'], 'LOW')
        self.assertEqual(rows[0]['gold_risk_level'], 'LOW')

    def test_journal_locks_and_refuses_corrupted_tail(self):
        journal = self.journal()
        with self.assertRaisesRegex(ValueError, 'already running'):
            self.journal(resume=True)
        journal.close()
        with journal.path.open('a') as stream:
            stream.write('{unfinished')
        with self.assertRaisesRegex(ValueError, 'Checkpoint invalid'):
            self.journal(resume=True)

    def test_non_object_checkpoint_record_is_rejected_and_lock_released(self):
        journal = self.journal()
        journal.close()
        valid = journal.path.read_text()
        for value in ([], None, 42):
            with self.subTest(value=value):
                journal.path.write_text(valid + json.dumps(value) + '\n')
                with self.assertRaisesRegex(ValueError, 'Checkpoint invalid'):
                    self.journal(resume=True)
        journal.path.write_text(valid)
        self.assertEqual(self.journal(resume=True).states, {})

    def test_completed_capture_with_mismatched_input_cannot_enter_reports(self):
        journal = self.journal()
        for digest in (None, json_hash('different input')):
            with self.subTest(digest=digest):
                record = capture()
                if digest is not None:
                    record['complaint_sha256'] = digest
                journal.append(record)
                collector = Collector(self.client, journal, self.dataset, self.context, 'test')
                with self.assertRaisesRegex(ValueError, 'input differs'):
                    collector.collect([self.case])
                with self.assertRaisesRegex(ValueError, 'input differs'):
                    collector.retry_fallbacks([self.case])
                with self.assertRaisesRegex(ValueError, 'input differs'):
                    export_capture(self.root, journal, self.dataset, [self.case])
                self.assertFalse((self.root / 'final_predictions.jsonl').exists())
                self.assertEqual(self.client.calls, [])

    def test_reports_compare_rule_and_final_without_recalling_model_or_faking_evidence(self):
        journal = self.journal()
        record = capture()
        threat = next(row for row in record['detectorResults']['results'] if row['code'] == 'THREAT')
        threat['llm'].update(state='PRESENT', severity=3, repeatCount=1)
        threat['finalState'] = 'PRESENT'
        record['complaint_sha256'] = json_hash(self.case['message_text'])
        journal.append(record)
        states, manifest = export_capture(self.root, journal, self.dataset, [self.case])
        args = build_parser().parse_args(['--capture-dir', str(self.root), '--report-dir', str(self.root / 'reports'),
                                          '--limit', '1', '--replay-only'])
        result = make_reports(args, self.dataset, [self.case], journal, states, manifest)
        rule = json.loads((Path(result['reports']['rule']) / 'metrics.json').read_text())
        final_dir = Path(result['reports']['final'])
        final = json.loads((final_dir / 'metrics.json').read_text())
        self.assertGreater(final['binary']['present']['micro']['recall'], rule['binary']['present']['micro']['recall'])
        self.assertEqual(final['final_risk']['status'], 'not_evaluated')
        self.assertIsNone(final['evidence']['match_rate'])
        self.assertEqual(final['evidence']['status'], 'not_evaluated_final_evidence_unavailable')
        self.assertEqual(final['versions']['prompt']['version'], 'server_unreported')
        self.assertEqual(json.loads((final_dir / 'diff.json').read_text())['paired_cases'], 1)
        self.assertFalse((final_dir / 'risk_confusion.png').exists())
        self.assertEqual(self.client.calls, [])
        # A later invocation can compare against a final run, not silently its Rule baseline.
        args.previous_final = final_dir
        args.gold_standard_status = 'team_approved'
        second = make_reports(args, self.dataset, [self.case], journal, states, manifest)
        difference = json.loads((Path(second['reports']['final']) / 'diff.json').read_text())
        self.assertEqual(difference['previous_run'], str(final_dir))
        self.assertEqual(difference['paired_cases'], 1)
        self.assertFalse(difference['controlled_ab'])
        self.assertEqual(second['gold_standard_acceptance']['status'], 'team_approved')

    def test_partial_capture_separates_unattempted_cases_from_actual_failures(self):
        cases = self.dataset.cases[:2]
        header = capture_header(self.dataset, cases, self.client, self.context)
        journal = self.journal(header=header)
        record = capture()
        record['complaint_sha256'] = json_hash(cases[0]['message_text'])
        journal.append(record)
        states, manifest = export_capture(self.root, journal, self.dataset, cases)
        args = build_parser().parse_args(['--capture-dir', str(self.root), '--report-dir', str(self.root / 'reports'),
                                          '--limit', '2', '--replay-only'])
        result = make_reports(args, self.dataset, cases, journal, states, manifest)
        coverage = result['views']['llm']['coverage']
        self.assertEqual((coverage['succeeded_cases'], coverage['failed_cases'], coverage['not_attempted_cases']), (1, 0, 1))
        self.assertEqual(coverage['failure_codes'], {})
        directory = Path(result['reports']['llm'])
        summary = json.loads((directory / 'summary.json').read_text())
        self.assertEqual((summary['cases_succeeded'], summary['cases_failed'], summary['cases_not_attempted']), (1, 0, 1))
        import csv
        with (directory / 'not_attempted.csv').open(encoding='utf-8-sig') as stream:
            self.assertEqual([row['case_id'] for row in csv.DictReader(stream)], ['G002'])


class BackendTransportTests(unittest.TestCase):
    def test_dev_cannot_claim_golden_approval_or_compare_another_dataset_before_login(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            previous = root / 'previous'
            previous.mkdir()
            (previous / 'manifest.json').write_text(json.dumps({
                'backend_capture': {'prediction_view': 'final'}, 'dataset': {'sha256': '0' * 64}}))
            for extra in (['--gold-standard-status', 'team_approved'], ['--previous-final', str(previous)]):
                with self.subTest(extra=extra), patch('scripts.evaluate_backend_goldenset.BackendClient') as client:
                    with self.assertRaises(ValueError):
                        main(['--dataset', 'dev', '--capture-dir', str(root / 'capture'), *extra])
                    client.assert_not_called()

    def test_malformed_previous_manifest_is_a_safe_preflight_error(self):
        with tempfile.TemporaryDirectory() as directory:
            previous = Path(directory) / 'previous'
            previous.mkdir()
            for value in (None, [], {'backend_capture': None},
                          {'backend_capture': {'prediction_view': 'final'}, 'dataset': None},
                          {'backend_capture': {'prediction_view': 'final'}, 'dataset': []}):
                with self.subTest(value=value), patch('scripts.evaluate_backend_goldenset.BackendClient') as client:
                    (previous / 'manifest.json').write_text(json.dumps(value))
                    with self.assertRaises(ValueError):
                        main(['--dataset', 'dev', '--capture-dir', str(Path(directory) / 'capture'),
                              '--previous-final', str(previous)])
                    client.assert_not_called()

    def test_authentication_then_durable_intent_then_post_without_a_second_login(self):
        client = BackendClient('https://backend.invalid', 'user', 'synthetic-password')
        events = []
        def login():
            events.append('auth')
            client.token = 'synthetic-token'
        def intent():
            events.append('intent')
            client.expiry = 0
        def request(*args):
            events.append('post')
            self.assertEqual(args[-1], 'synthetic-token')
            return {'complaintId': 7}
        with patch.object(client, 'login', side_effect=login), patch.object(client, '_request', side_effect=request):
            client.call('POST', '/complaints', {}, before_send=intent)
        self.assertEqual(events, ['auth', 'intent', 'post'])

    def test_failed_intent_write_prevents_mutation_request(self):
        client = BackendClient('https://backend.invalid', 'user', 'synthetic-password')
        with patch.object(client, 'login'), patch.object(client, '_request') as request:
            with self.assertRaises(OSError):
                client.call('POST', '/complaints', {}, before_send=MagicMock(side_effect=OSError('write failed')))
            request.assert_not_called()

    def test_cli_shows_authentication_and_safe_context_errors(self):
        client = BackendClient('https://backend.invalid', 'user', 'synthetic-password')
        errors = [BackendError('backend:http_401')]
        for responses in ([{'role': 'PARENT', 'students': []}],
                          [{'role': 'PARENT', 'students': [{'studentId': 1}]}, [{'teacherId': 1}, {'teacherId': 2}]]):
            with patch.object(client, 'call', side_effect=responses):
                try:
                    client.context()
                except ValueError as error:
                    errors.append(error)
        self.assertEqual(len(errors), 3)
        for error in errors:
            status, output = run_cli_failure(error)
            self.assertEqual(status, 2)
            self.assertIn(str(error), output)

    def test_cli_never_echoes_arbitrary_value_or_file_errors(self):
        secret = 'RAW_ERROR_sk-SECRET_CANARY'
        for error in (ValueError(secret), json.JSONDecodeError(secret, secret, 0), OSError(secret), KeyError(secret)):
            with self.subTest(kind=type(error).__name__):
                status, output = run_cli_failure(error)
                self.assertEqual(status, 2)
                self.assertNotIn(secret, output)
                self.assertNotIn('POST', output)

    def test_context_rejects_wrong_role_and_unowned_student_before_mutations(self):
        client = BackendClient('https://backend.invalid', 'user', 'secret')
        with patch.object(client, 'call', return_value={'role': 'TEACHER'}) as call:
            with self.assertRaisesRegex(BackendError, 'parent_role_required'):
                client.context()
            self.assertEqual(call.call_args_list[0].args, ('GET', '/users/me'))
            self.assertEqual(call.call_count, 1)
        with patch.object(client, 'call', return_value={'role': 'PARENT', 'students': [{'studentId': 1}]}) as call:
            with self.assertRaisesRegex(ValueError, 'does not belong'):
                client.context(student_id=2)
            self.assertEqual(call.call_count, 1)

    def test_bad_targets_fail_before_login_or_any_paid_call(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'bad-targets.csv'
            target.write_text('wrong,header\n')
            with patch('scripts.evaluate_backend_goldenset.BackendClient') as client:
                with self.assertRaises(ValueError):
                    main(['--capture-dir', str(Path(directory) / 'capture'), '--targets', str(target)])
                client.assert_not_called()

    def test_upstream_errors_never_include_body_token_or_password(self):
        for error in (HTTPError('https://backend.invalid/auth/login', 401, 'SECRET', {}, io.BytesIO(b'SECRET')),
                      URLError('SECRET')):
            with self.subTest(error=type(error).__name__):
                opener = MagicMock()
                opener.open.side_effect = error
                client = BackendClient('https://backend.invalid', 'user', 'SECRET', opener=opener)
                with self.assertRaises(BackendError) as caught:
                    client.login()
                self.assertNotIn('SECRET', str(caught.exception))

    def test_credentials_cannot_be_sent_to_plain_http_remote_or_credential_url(self):
        for url in ('http://example.com', 'https://user:password@example.com', 'https://example.com?key=value'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                BackendClient(url, 'user', 'secret')


def run_cli_failure(error):
    output = io.StringIO()
    path = Path(__file__).parents[1] / 'scripts/evaluate_backend_goldenset.py'
    with patch('sys.argv', [str(path), '--capture-dir', 'unused']), \
            patch('scripts.evaluation.data.load_dataset', side_effect=error), redirect_stderr(output):
        try:
            runpy.run_path(str(path), run_name='__main__')
        except SystemExit as stopped:
            return stopped.code, output.getvalue()
    raise AssertionError('CLI did not exit')


if __name__ == '__main__':
    unittest.main()
