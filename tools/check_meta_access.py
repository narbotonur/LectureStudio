"""Check credential presence; --live sends one small fictional Meta API request.

Never prints credentials, private lecture data, provider content or headers.
python tools/check_meta_access.py --check
python tools/check_meta_access.py --live
"""
import argparse
import contextlib
import io
import json
from pathlib import Path
import re
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--check', action='store_true', help='Only check local credential presence (default).')
    modes.add_argument('--live', action='store_true', help='Send one fictional request; API usage may be billed.')
    parser.add_argument('--model', default=None)
    parser.add_argument('--report', type=Path, default=Path('review_artifacts/meta-access/access.json'))
    args = parser.parse_args()
    # Config has routine status prints; keep smoke reports machine-readable.
    with contextlib.redirect_stdout(io.StringIO()):
        from annie.meta_client import MetaAPIError, MetaClient
        client = MetaClient(model=args.model, reasoning_effort='minimal', max_tokens=512,
                            strict=True, timeout=35, max_attempts=1)
    # Do not echo arbitrary local configuration as if it were safe metadata.
    model = client.model if isinstance(client.model, str) and re.fullmatch(r'muse-[a-z0-9.-]{1,80}', client.model) else 'configured-model'
    report = {'key_configured': bool(client.api_key), 'model': model,
              'live_requested': args.live, 'status': 'not_tested', 'requests': 0}
    code = 0
    if not client.api_key:
        report['status'] = 'missing_key'
        code = 2
    elif args.live:
        started = time.monotonic()
        schema = {'type': 'object', 'properties': {'ready': {'type': 'boolean'}},
                  'required': ['ready'], 'additionalProperties': False}
        try:
            value = json.loads(client.complete([
                {'role': 'developer', 'content': 'Return JSON matching the schema. Set ready to true.'},
                {'role': 'user', 'content': 'This is a fictional Lecture Studio connectivity check.'}], schema))
            if value != {'ready': True}:
                report['status'] = 'unexpected_output'
                code = 1
            else:
                report['status'] = 'ok'
        except MetaAPIError as exc:
            report['status'] = 'api_error'
            report['error'] = str(exc)
            if exc.status_code is not None:
                report['http_status'] = exc.status_code
            code = 1
        except (ValueError, TypeError):
            report['status'] = 'unreadable_output'
            code = 1
        report.update(requests=client.request_count, usage=client.total_usage,
                      elapsed_seconds=round(time.monotonic() - started, 3))
    else:
        report['status'] = 'key_present_access_unverified'
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
