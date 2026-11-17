#!/usr/bin/env python3
"""Public Backend Golden Set capture and offline reports (#26)."""
from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from pathlib import Path

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.evaluate_risk_prompt_updated import build_parser as evaluation_parser
from scripts.evaluation.backend import (BackendClient, BackendError, Collector, Journal,
                                        capture_header, export_capture)
from scripts.evaluation.charts import check_available
from scripts.evaluation.data import check_disjoint, load_dataset
from scripts.evaluation.reporting import write_json
from scripts.evaluation.runner import evaluate
from scripts.evaluation.supplemental import read_targets


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='https://teacherhub.duckdns.org')
    parser.add_argument('--capture-dir', required=True, type=Path)
    parser.add_argument('--report-dir', type=Path, default=Path('reports/backend_goldenset'))
    parser.add_argument('--credentials-file', type=Path, help='Private JSON with email/password; never retained in reports')
    parser.add_argument('--student-id', type=int)
    parser.add_argument('--teacher-id', type=int)
    parser.add_argument('--workers', type=int, choices=(1, 2), default=1)
    parser.add_argument('--timeout', type=float, default=180)
    parser.add_argument('--limit', type=int)
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--retry-fallbacks', action='store_true', help='With --resume after recovery, create new drafts only for captured Rule-only failures')
    parser.add_argument('--replay-only', action='store_true', help='No login or HTTP calls; requires an existing capture')
    parser.add_argument('--seed-smoke', type=Path)
    parser.add_argument('--run-version', default='backend-g200-baseline')
    parser.add_argument('--targets', type=Path)
    parser.add_argument('--charts', action='store_true')
    parser.add_argument('--previous-final', type=Path, help='Compare with an earlier final-view run; otherwise compare captured Rule and final')
    parser.add_argument('--gold-standard-status', choices=('dataset_metadata', 'team_approved'),
                        default='dataset_metadata', help='Explicit team acceptance; preserves original per-label review metadata')
    return parser


def validate_previous(args):
    if args.previous_final:
        previous = json.loads((args.previous_final / 'manifest.json').read_text())
        if previous.get('backend_capture', {}).get('prediction_view') != 'final':
            raise ValueError('--previous-final requires a final-view Backend report')


def make_reports(args, dataset, cases, journal, states, capture_manifest):
    validate_previous(args)
    capture_manifest = {**capture_manifest, 'gold_standard_acceptance': {
        'status': args.gold_standard_status,
        'scope': 'eight tag states in the original Golden Set CSVs; final risk not included',
        'original_review_metadata_preserved': True}}
    if args.previous_final:
        capture_manifest['comparison_kind'] = 'previous_final_run; uncontrolled deployment comparison'
    directories = {}
    metrics_by_view = {}
    for view in ('rule', 'llm', 'final'):
        command = ['--dataset', 'goldenset', '--mode', 'rule_llm',
                   '--predictions', str(args.capture_dir / f'{view}_predictions.jsonl'),
                   '--rule-results', str(args.capture_dir / 'captured_rules.json'),
                   '--report-dir', str(args.report_dir / view), '--run-version', f'{args.run_version}-{view}',
                   '--rule-version', 'server_unreported', '--prompt-version', 'server_unreported',
                   '--rag-version', 'server_unreported']
        if args.limit:
            command.extend(['--limit', str(args.limit)])
        if args.targets:
            command.extend(['--targets', str(args.targets)])
        if args.charts:
            command.append('--charts')
        if view == 'final':
            command.extend(['--previous', str(args.previous_final or directories['rule'])])
        options = evaluation_parser().parse_args(command)
        options.policies = ['present', 'present_boundary']
        options.backend_capture = {'manifest': capture_manifest, 'states': states, 'view': view,
                                   'journal_path': str(journal.path.resolve())}
        metrics, directory, status = evaluate(options)
        directories[view] = str(directory.resolve())
        metrics_by_view[view] = {'coverage': metrics['coverage'], 'binary': metrics['binary'],
                                 'final_risk_status': metrics['final_risk']['status'], 'exit_status': status}
    index = {'dataset_sha256': dataset.digest, 'capture': str(args.capture_dir.resolve()),
             'reports': directories, 'views': metrics_by_view,
             'comparison': ('Previous final run; actual deployment/generation differences are unverified'
                            if args.previous_final else 'Rule versus final from the same captured backend executions; not a prompt improvement claim'),
             'gold_standard_acceptance': capture_manifest['gold_standard_acceptance'],
             'limitations': ['REPEAT excluded; golden history/regulation not supplied',
                             'Original review groups are preserved separately from explicit team acceptance',
                             'Final risk requires independent CONFIRMED human targets',
                             'Deployed prompt/rule/source versions and masked model input are unreported']}
    write_json(args.capture_dir / 'report_index.json', index)
    return index


def main(argv=None):
    args = build_parser().parse_args(argv)
    dataset = load_dataset('data/goldenset', 'goldenset')
    dev = load_dataset('data/dev', 'dev')
    if not check_disjoint(dataset.cases, dev.cases)['passed']:
        raise ValueError('dev/gold overlap detected')
    if args.limit is not None and args.limit < 1:
        raise ValueError('--limit must be positive')
    if args.retry_fallbacks and (not args.resume or args.replay_only):
        raise ValueError('--retry-fallbacks requires live --resume')
    read_targets(args.targets, dataset)
    validate_previous(args)
    if args.charts:
        check_available()
    cases = dataset.cases[:args.limit] if args.limit else dataset.cases
    if args.replay_only:
        header = json.loads((args.capture_dir / 'checkpoint.jsonl').read_text().splitlines()[0])
        expected_ids = [case['case_id'] for case in cases]
        if header.get('dataset_sha256') != dataset.digest or header.get('case_ids') != expected_ids:
            raise ValueError('Capture dataset/selection differs')
        journal = Journal(args.capture_dir / 'checkpoint.jsonl', header, resume=True)
        failure_path = args.capture_dir / 'capture_failures.json'
        failures = json.loads(failure_path.read_text()) if failure_path.exists() else []
    else:
        if args.credentials_file:
            credentials = json.loads(args.credentials_file.read_text())
            email, password = credentials.get('email'), credentials.get('password')
        else:
            email = os.getenv('TEACHERHUB_EMAIL') or input('Test parent email: ')
            password = os.getenv('TEACHERHUB_PASSWORD') or getpass.getpass('Test parent password: ')
        client = BackendClient(args.base_url, email, password, timeout=args.timeout)
        context = client.context(args.student_id, args.teacher_id)
        header = capture_header(dataset, cases, client, context)
        journal = Journal(args.capture_dir / 'checkpoint.jsonl', header, resume=args.resume)
        collector = Collector(client, journal, dataset, context, args.run_version)
        if args.seed_smoke:
            collector.seed(args.seed_smoke)
        if args.retry_fallbacks:
            print(json.dumps({'event': 'fallback_retries_prepared', 'cases': collector.retry_fallbacks(cases)}), flush=True)
        print(json.dumps({'event': 'capture_started', 'cases': len(cases), 'workers': args.workers,
                          'already_captured': sum(s.get('stage') == 'complete' for s in journal.states.values())}), flush=True)
        failures = collector.collect(cases, workers=args.workers,
                                     progress=lambda value: print(json.dumps(value, ensure_ascii=False), flush=True))
    try:
        states, capture_manifest = export_capture(args.capture_dir, journal, dataset, cases)
        index = make_reports(args, dataset, cases, journal, states, capture_manifest)
        write_json(args.capture_dir / 'capture_failures.json', failures)
        print(json.dumps({'event': 'reports_saved', 'captured': len(states), 'requested': len(cases),
                          'reports': index['reports'], 'failures': failures}, ensure_ascii=False), flush=True)
        return int(bool(failures) or len(states) != len(cases)
                   or capture_manifest['model_success_cases'] != len(cases)
                   or any(view['exit_status'] for view in index['views'].values()))
    finally:
        journal.close()


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (BackendError, ValueError, OSError, KeyError):
        print('Backend evaluation stopped. Check the capture checkpoint; no POST is retried automatically.', file=sys.stderr)
        sys.exit(2)
