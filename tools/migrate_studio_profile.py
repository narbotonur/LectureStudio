"""Explicit same-machine profile COPY. Never delete originals or merge profiles."""
import argparse
from contextlib import closing
import json
from pathlib import Path
import shutil
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from annie.secure_storage import atomic_write, read_secret, write_secret

DIRECTORIES = ('recordings', 'model-cache')
LIBRARIES = ('csci235_materials', 'csci235_study_guide', 'lecture_dataset', 'syllabuses')
PLAIN_FILES = ('lecture_schedule_cache.json', 'prayer-widget.json', 'prayer-times-cache.json')


def active_source_processes(source):
    import psutil
    found = []
    for process in psutil.process_iter(['pid', 'name']):
        if process.pid == __import__('os').getpid() or not (process.info['name'] or '').lower().startswith('python'):
            continue
        try:
            args = process.cmdline()
            if (any('annie.' in arg or Path(arg).name in ('lecture_studio_entry.py', 'main.py') for arg in args)
                    and Path(process.cwd()).resolve() == source):
                found.append(process.pid)
        except (psutil.Error, OSError):
            continue
    return found


def migrate(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if not (source / 'annie_settings.json').is_file():
        raise ValueError('Expected an existing ANNIE profile with annie_settings.json.')
    if (destination == source or source in destination.parents or destination == ROOT
            or ROOT in destination.parents or destination in source.parents):
        raise ValueError('The private profile must be separate from both source repositories.')
    if destination.exists() and any(destination.iterdir()):
        raise FileExistsError('Destination profile is not empty; automatic merging is disabled.')
    if active_source_processes(source):
        raise RuntimeError('Close the old Studio, watcher, prayer widget and recording workers first.')
    settings = json.loads((source / 'annie_settings.json').read_text(encoding='utf-8-sig'))
    secrets = {name: settings.pop(name) for name in list(settings) if name.endswith('_api_key')}
    if (source / 'accounts.dpapi').exists():
        secrets.update(read_secret(source / 'accounts.dpapi'))
    # Refuse redirected content: migration must not wander outside its source.
    for name in DIRECTORIES + LIBRARIES:
        folder = source / name
        if folder.exists():
            for path in [folder, *folder.rglob('*')]:
                # Hugging Face uses file links from snapshots to local blobs.
                # Dereference only files whose targets stay inside this folder.
                if ((path.is_symlink() and (not path.is_file() or folder not in path.resolve().parents))
                        or (hasattr(path, 'is_junction') and path.is_junction())):
                    raise ValueError('Linked content requires a manual migration: ' + str(path))
    destination.mkdir(parents=True, exist_ok=True)
    write_secret(destination / 'accounts.dpapi', secrets)
    atomic_write(destination / 'annie_settings.json', json.dumps(settings, ensure_ascii=False, indent=2).encode())
    for protected, legacy in (('calendar.dpapi', 'token.json'), ('google-client.dpapi', 'credentials.json')):
        if (source / protected).exists():
            value = read_secret(source / protected)
        elif (source / legacy).exists():
            value = json.loads((source / legacy).read_text(encoding='utf-8-sig'))
        else:
            continue
        write_secret(destination / protected, value)
        if read_secret(destination / protected) != value:
            raise RuntimeError('Encrypted credential verification failed.')
    for name in PLAIN_FILES:
        if (source / name).is_file():
            shutil.copy2(source / name, destination / name)
    db = source / 'study_sessions.sqlite3'
    if db.is_file():
        with closing(sqlite3.connect(db.as_uri() + '?mode=ro', uri=True)) as old:
            with closing(sqlite3.connect(destination / db.name)) as new:
                old.backup(new)
                if new.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise RuntimeError('Study history integrity check failed.')
    for name in DIRECTORIES + LIBRARIES:
        if (source / name).is_dir():
            target = destination / name if name in DIRECTORIES else destination / 'library' / name
            shutil.copytree(source / name, target)
    library = destination / 'library'
    for path in source.iterdir():
        if path.is_file() and path.suffix.lower() in ('.md', '.txt') and path.name != 'requirements.txt':
            library.mkdir(exist_ok=True)
            shutil.copy2(path, library / path.name)
    # Mark completion only after every copy succeeds. No OAuth refresh, cloud call,
    # login startup change or microphone access occurs during migration.
    atomic_write(destination / 'setup-complete.json', b'{"version": 1}')
    atomic_write(destination / 'migration-report.json', json.dumps({
        'source': str(source), 'mode': 'copy', 'originals_preserved': True,
        'credentials': 'user-bound encryption', 'library': str(library),
    }, indent=2).encode())
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    print('Private profile copied to:', migrate(args.source, args.destination))
    print('Original files preserved. No credentials were printed or added to Git.')
