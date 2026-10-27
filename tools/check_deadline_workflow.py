"""Exercise one versioned deadline in a temporary profile; no personal lectures.

Default is an offline fixture. --live makes ONE Meta request using the configured
account and a fictional lecture. It never changes the signed-in user's Inbox.
"""
import argparse
import datetime as dt
import json
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OLD = '2026-11-03T17:00+05:00'
NEW = '2026-11-06T17:00+05:00'
SOURCE = 'Fictional deadline-change lecture'
SEGMENTS = [
    {'start': 0, 'end': 10, 'source': SOURCE,
     'text': 'Lab 2 is due November 3, 2026 at 17:00.'},
    {'start': 60, 'end': 75, 'source': SOURCE,
     'text': 'Correction: Lab 2 is now due November 6, 2026 at 17:00, not November 3.'},
]


def fixture_response(current=(), correction=True):
    refs = [{'quote': s['text'], 't_start': s['start'], 't_end': s['end'],
             'source': s['source'], 'due_at': NEW if i else OLD}
            for i, s in enumerate(SEGMENTS if correction else SEGMENTS[:1])]
    return json.dumps({'findings': [], 'deadlines': [{
        'title': 'Lab 2', 'assignment_id': current[0]['assignment_id'] if current else None,
        'relation': 'explicit_correction' if correction else 'new',
        'due_at': NEW if correction else OLD,
        'reason': 'The lecturer explicitly corrected the deadline.' if correction else 'An explicit deadline.',
        'evidence': refs}]})


def seed_old(store):
    from annie.lecture_reconciliation import analyze_lecture
    initial = analyze_lecture(SEGMENTS[:1], 'CSCI 231', SOURCE, dt.date(2026, 10, 27),
        generator=lambda *_: fixture_response(correction=False))
    saved = store.propose(initial.proposals[0])
    return store.approve(saved['id'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--model', default='muse-spark-1.3')
    args = parser.parse_args()
    from annie.lecture_reconciliation import analyze_lecture
    from annie.obligations import ObligationStore
    from annie.deadlines import DeadlineStore
    report = {'mode': 'one live Meta request' if args.live else 'offline supplied model response',
              'personal_data_used': False, 'user_inbox_modified': False}
    started = time.monotonic()
    client = None
    try:
        with tempfile.TemporaryDirectory(prefix='lecture-deadline-workflow-') as root:
            store = ObligationStore(root)
            seed_old(store)
            current = store.list_current('CSCI 231')
            if args.live:
                from annie.meta_client import MetaClient
                client = MetaClient(model=args.model, reasoning_effort='medium',
                                    max_tokens=4096, max_attempts=1, strict=True, timeout=60)
                generator = client.complete
            else:
                generator = lambda *_: fixture_response(current)
            analysis = analyze_lecture(SEGMENTS, 'CSCI 231', SOURCE, dt.date(2026, 10, 27),
                                       current=current, generator=generator)
            report['rejected_count'] = analysis.rejected_count
            report['proposal_count'] = len(analysis.proposals)
            report['relations'] = [p['relation'] for p in analysis.proposals]
            if len(analysis.proposals) != 1:
                raise ValueError('Expected one source-checked deadline proposal.')
            proposal = analysis.proposals[0]
            if proposal['proposed_due_at'] != NEW or proposal['relation'] != 'explicit_correction':
                raise ValueError('The model did not establish the explicit corrected date.')
            saved = store.propose(proposal)
            assert store.list_current()[0]['due_at'] == OLD, 'Extraction changed an active deadline.'
            approved = store.approve(saved['id'], expected_fingerprint=analysis.fingerprint)
            store.approve(saved['id'])
            reopened = ObligationStore(root)
            deadlines = DeadlineStore(root).load()
            versions = reopened.history(approved['assignment_id'])
            assert len(deadlines) == 1 and deadlines[0]['due_at'] == NEW
            assert len(versions) == 2
            assert len(reopened.list_current()) == 1
            report.update(passed=True, active_deadline_count=1, confirmed_due_at=NEW,
                          retained_versions=2, double_approve_safe=True,
                          extraction_left_old_deadline_unchanged=True,
                          previous_quote_retained=bool(proposal['previous_evidence']))
    except Exception as exc:
        from annie.meta_client import MetaAPIError
        report['passed'] = False
        report['error'] = str(exc) if isinstance(exc, (ValueError, MetaAPIError)) else 'Local workflow check failed.'
    if client:
        report.update(model=client.model, effort=client.reasoning_effort,
                      request_count=client.request_count, usage=client.total_usage)
    report['elapsed_seconds'] = round(time.monotonic() - started, 3)
    output = ROOT / 'review_artifacts' / 'deadline-workflow'
    output.mkdir(parents=True, exist_ok=True)
    (output / ('live.json' if args.live else 'offline.json')).write_text(
        json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))
    return 0 if report.get('passed') else 1


if __name__ == '__main__':
    raise SystemExit(main())
