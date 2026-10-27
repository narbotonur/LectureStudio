"""Small frozen DEVELOPMENT evaluation, not holdout validation or ASR evaluation.

Default: validate/list authored cases, no credentials or network.
--live: one Meta request per case, maximum 12 calls and a $0.25 token budget.
No real transcript, calendar or profile store is used. Only app credentials are
read to construct the provider client. The report never dumps API payloads.
"""
import argparse
import contextlib
import datetime as dt
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from deadline_evaluation_cases import CASES

FIXTURES = Path(__file__).with_name('deadline_evaluation_cases.py')
MODEL = 'muse-spark-1.3'
INPUT_RATE = 1.25 / 1_000_000
OUTPUT_RATE = 4.25 / 1_000_000
MAX_BUDGET = 0.25
MAX_OUTPUT = 4096


def fingerprint(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def name(value):
    value = re.sub(r'(?<=[a-z])(?=\d)|(?<=\d)(?=[a-z])', ' ', value.casefold())
    return ' '.join(re.findall(r'[^\W_]+', value))


def evaluate(case, analysis):
    expected = case['expected']
    actual = analysis.proposals
    failures = []
    if len(actual) != len(expected['proposals']):
        failures.append('proposal_count: expected %d, actual %d' % (len(expected['proposals']), len(actual)))
    for item in expected['proposals']:
        matches = [p for p in actual if name(p['title']) == name(item['title'])]
        if len(matches) != 1:
            failures.append('assignment_identity: ' + item['title'])
            continue
        proposal = matches[0]
        for field, actual_field in [('due_at', 'proposed_due_at'), ('relation', 'relation')]:
            if proposal[actual_field] not in item[field]:
                failures.append(item['title'] + ': unexpected ' + actual_field)
        for field in ('assignment_id', 'expected_revision', 'previous_due_at'):
            if field in item and proposal[field] != item[field]:
                failures.append(item['title'] + ': incorrect ' + field)
        if len(proposal['evidence']) < item.get('minimum_evidence', 1):
            failures.append(item['title'] + ': missing evidence')
        if item.get('assumed_time_required') and proposal['proposed_due_at'] is not None:
            if not re.search(r'assum|default|end.of.day', proposal['reason'], re.I):
                failures.append(item['title'] + ': missing explicit time-assumption explanation')
    hints = sum(p['type'] == 'exam_hint' for p in analysis.study_scan.actions)
    if 'exam_hint_count' in expected and hints != expected['exam_hint_count']:
        failures.append('unsupported_exam_hint')
    safe_actual = [{'title': p['title'], 'assignment_id': p['assignment_id'], 'relation': p['relation'],
                    'due_at': p['proposed_due_at'], 'previous_due_at': p['previous_due_at'],
                    'expected_revision': p['expected_revision'], 'evidence_count': len(p['evidence'])}
                   for p in actual]
    return {'pass': not failures, 'failures': failures, 'actual': safe_actual,
            'study_findings': len(analysis.study_scan.actions), 'exam_hints': hints,
            'rejected_count': analysis.rejected_count}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--expected-sha256', help='Require the previously frozen source-file digest.')
    parser.add_argument('--report', type=Path, default=ROOT/'review_artifacts/deadline-evaluation/development.json')
    args = parser.parse_args()
    dataset_hash = fingerprint(FIXTURES)
    assert len(CASES) == 12 and len({case['id'] for case in CASES}) == 12
    for case in CASES:
        assert isinstance(case['expected']['proposals'], list)
        assert case['segments'] and all(s['end'] > s['start'] for s in case['segments'])
    if args.expected_sha256 and args.expected_sha256 != dataset_hash:
        parser.error('Frozen fixture digest changed; no API calls made.')
    report = {'kind': 'author-created frozen development evaluation', 'dataset_sha256': dataset_hash,
              'case_count': len(CASES), 'model': MODEL, 'effort': 'medium', 'strict': True,
              'max_tokens': MAX_OUTPUT, 'max_attempts': 1, 'budget_usd': MAX_BUDGET,
              'live': args.live, 'cases': [], 'credits_verified': False}
    print(json.dumps({'dataset_sha256': dataset_hash, 'cases': [case['id'] for case in CASES],
                      'live': args.live}), flush=True)
    if not args.live:
        return 0
    if not args.expected_sha256:
        parser.error('--live requires --expected-sha256 from the offline freeze check.')
    # Prevent accidental repeat billing and preserve the first frozen result.
    if args.report.exists():
        parser.error('Report already exists; choose a new report path explicitly.')
    with contextlib.redirect_stdout(io.StringIO()):
        from annie.meta_client import MetaClient, MetaAPIError
        client = MetaClient(model=MODEL, reasoning_effort='medium', strict=True,
                            max_tokens=MAX_OUTPUT, timeout=45, max_attempts=1)
    if not client.api_key:
        parser.error('Configure the Meta key in the application first; no calls made.')
    from annie.lecture_reconciliation import analyze_lecture
    import annie.lecture_reconciliation as runtime
    report['runtime_sha256'] = fingerprint(Path(runtime.__file__))
    report['started_utc'] = dt.datetime.now(dt.timezone.utc).isoformat()
    budget_spent = 0.0
    for case in CASES:
        request_start = client.request_count
        started = time.monotonic()
        row = {'id': case['id'], 'description': case['description'], 'expected': case['expected']}
        reserved = 0.0
        def generate(messages, schema):
            nonlocal reserved
            if client.request_count >= 12 or client.request_count != request_start:
                raise ValueError('Per-case request limit reached.')
            # UTF-8 bytes + protocol allowance conservatively bound input tokens.
            maximum_input = len(json.dumps({'messages': messages, 'schema': schema}).encode('utf-8')) + 512
            reserved = maximum_input * INPUT_RATE + MAX_OUTPUT * OUTPUT_RATE
            if budget_spent + reserved > MAX_BUDGET:
                raise ValueError('Evaluation budget guard reached before the next request.')
            return client.complete(messages, schema)
        try:
            # Analysis must stay read-only; block any accidental store writes.
            with patch('annie.secure_storage.atomic_write', side_effect=AssertionError('Profile writes forbidden')):
                analysis = analyze_lecture(case['segments'], 'CSCI 231', 'Authored development lecture',
                    dt.date(2026, 10, 27), current=case['current'], generator=generate)
            row.update(evaluate(case, analysis))
        except MetaAPIError as exc:
            row.update({'pass': False, 'failures': ['api_error'], 'http_status': exc.status_code})
        except (ValueError, TypeError, KeyError, AssertionError):
            row.update({'pass': False, 'failures': ['analysis_or_budget_error']})
        usage = client.last_usage if client.request_count > request_start else {}
        if 'prompt_tokens' in usage and 'completion_tokens' in usage:
            spent = usage['prompt_tokens'] * INPUT_RATE + usage['completion_tokens'] * OUTPUT_RATE
        elif client.request_count > request_start:
            spent = reserved
        else:
            spent = 0.0
        budget_spent += spent
        row.update({'requests': client.request_count - request_start, 'usage': usage,
                    'elapsed_seconds': round(time.monotonic() - started, 3)})
        report['cases'].append(row)
        report.update({'requests': client.request_count, 'usage': client.total_usage,
                       'budget_accounted_usd': round(budget_spent, 8),
                       'passed': sum(x['pass'] for x in report['cases']),
                       'completed': len(report['cases'])})
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        print(json.dumps({'id': case['id'], 'pass': row['pass'], 'failures': row['failures'],
                          'elapsed_seconds': row['elapsed_seconds']}), flush=True)
    report['finished_utc'] = dt.datetime.now(dt.timezone.utc).isoformat()
    args.report.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: report[k] for k in ('passed', 'completed', 'requests', 'usage', 'budget_accounted_usd')}), flush=True)
    return 0 if report['passed'] == len(CASES) else 1


if __name__ == '__main__':
    raise SystemExit(main())
