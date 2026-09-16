"""Fail safely when a public tree or reachable history looks private."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRIVATE_SUFFIXES = {
    '.dpapi', '.sqlite', '.sqlite3', '.db', '.wav', '.mp3', '.m4a', '.aac',
    '.key', '.pem', '.p12', '.pfx',
}
PRIVATE_NAMES = {
    '.env', 'credentials.json', 'client_secret.json', 'token.json',
    'google_credentials.json',
}
PATTERNS = (
    ('Google API key', re.compile('AI' + r'za[0-9A-Za-z_-]{20,}')),
    ('GitHub token', re.compile('gh' + r'[pousr]_[0-9A-Za-z]{20,}')),
    ('private key', re.compile('-----BEGIN ' + r'(?:RSA |EC |OPENSSH )?PRIVATE KEY-----')),
    ('absolute Windows user path', re.compile(r'\b[A-Za-z]:\\Users\\[^\\\s]+', re.I)),
    ('private Moodle URL', re.compile(r'https?://\S+(?:token|authtoken)=[0-9A-Za-z%_-]{12,}', re.I)),
)


def git(*args, check=True):
    return subprocess.run(('git', *args), cwd=ROOT, check=check,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def tracked_paths(revision=None):
    if revision:
        raw = git('ls-tree', '-r', '--name-only', '-z', revision).stdout
    else:
        raw = git('ls-files', '-z').stdout
    return [Path(item.decode('utf-8', 'replace')) for item in raw.split(b'\0') if item]


def blob(path, revision=None):
    if revision:
        return git('show', f'{revision}:{path.as_posix()}', check=False).stdout
    try:
        return (ROOT / path).read_bytes()
    except OSError:
        return b''


def suspicious_path(path):
    lowered = path.name.casefold()
    parts = {part.casefold() for part in path.parts}
    return (path.suffix.casefold() in PRIVATE_SUFFIXES or lowered in PRIVATE_NAMES or
            'recordings' in parts or lowered.startswith(('credentials.', 'client_secret.')))


def scan_tree(label, revision=None):
    findings = set()
    for path in tracked_paths(revision):
        if suspicious_path(path):
            findings.add((label, path.as_posix(), 0, 'private artifact path'))
        data = blob(path, revision)
        if not data or b'\0' in data[:4096] or len(data) > 5_000_000:
            continue
        text = data.decode('utf-8', 'replace')
        for number, line in enumerate(text.splitlines(), 1):
            for kind, pattern in PATTERNS:
                match = pattern.search(line)
                if not match:
                    continue
                value = match.group(0).casefold()
                if ('example' in value or 'test-token' in value or
                        path.as_posix() == 'tools/audit_public_repo.py'):
                    continue
                findings.add((label, path.as_posix(), number, kind))
    return findings


def scan_history(revisions):
    """Use git-grep per revision so unchanged blobs are not spawned one by one."""
    findings = set()
    for revision in revisions:
        label = revision[:12]
        for path in tracked_paths(revision):
            if suspicious_path(path):
                findings.add((label, path.as_posix(), 0, 'private artifact path'))
        for kind, pattern in PATTERNS:
            result = git('grep', '-I', '-n', '-P', pattern.pattern, revision, check=False)
            for raw in result.stdout.decode('utf-8', 'replace').splitlines():
                match = re.match(r'^[^:]+:(.*?):(\d+):(.*)$', raw)
                if not match:
                    continue
                path, number, line = match.groups()
                value_match = pattern.search(line)
                value = value_match.group(0).casefold() if value_match else ''
                if ('example' in value or 'test-token' in value or
                        path == 'tools/audit_public_repo.py'):
                    continue
                findings.add((label, path, int(number), kind))
    return findings


def author_findings():
    output = git('log', '--all', '--format=%H%x00%an%x00%ae').stdout.decode('utf-8', 'replace')
    findings = set()
    for row in output.splitlines():
        commit, _name, email = row.split('\0', 2)
        if email and not email.casefold().endswith('@users.noreply.github.com'):
            findings.add((commit[:12], '<commit metadata>', 0,
                          'author email is not a GitHub noreply address'))
    return findings


def main():
    if git('rev-parse', '--is-inside-work-tree', check=False).returncode:
        print('Run this tool inside the Lecture Studio Git repository.', file=sys.stderr)
        return 2
    findings = scan_tree('working tree')
    revisions = git('rev-list', '--all').stdout.decode().splitlines()
    findings.update(scan_history(revisions))
    findings.update(author_findings())
    if findings:
        print('Public repository audit FAILED. Values are redacted:')
        for revision, path, line, kind in sorted(findings):
            location = f'{path}:{line}' if line else path
            print(f'- {revision} {location}: {kind}')
        return 1
    print(f'Public repository audit passed: {len(tracked_paths())} tracked files and '
          f'{len(revisions)} reachable commits checked; no private artifacts or '
          'credential-shaped values found.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
