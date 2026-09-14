"""Create a new, private-data-free Studio source repository; never move originals."""
import argparse
import ast
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.build_studio_macos import stage_macos
from tools.build_studio_release import DENIED, validate_source


def audit(destination):
    """Validate source credentials and ensure all absolute Annie imports resolve."""
    for path in destination.rglob('*'):
        if not path.is_file():
            continue
        if path.name in DENIED or path.suffix.lower() in ('.wav', '.sqlite3', '.dpapi'):
            raise ValueError('Personal data is not allowed: ' + str(path))
        if path.suffix != '.py':
            continue
        validate_source(path)
        tree = ast.parse(path.read_text(encoding='utf-8-sig'))
        for node in ast.walk(tree):
            names = ([a.name for a in node.names] if isinstance(node, ast.Import)
                     else [node.module] if isinstance(node, ast.ImportFrom) and node.module else [])
            for name in names:
                if name == 'annie' or name.startswith('annie.'):
                    module = destination.joinpath(*name.split('.'))
                    if not module.with_suffix('.py').is_file() and not (module / '__init__.py').is_file():
                        raise ValueError(f'Missing Studio dependency in {path.name}: {name}')


def export(destination, initialize_git=True):
    destination = Path(destination).resolve()
    if destination == ROOT or ROOT in destination.parents:
        raise ValueError('Choose a separate directory outside the original project.')
    # No merge or overwrite: existing source and profiles always remain intact.
    destination.mkdir(parents=False, exist_ok=False)
    stage_macos(destination)
    for name in ('BUILDING.md', 'START_HERE.md', 'Create shortcuts.ps1'):
        shutil.copy2(ROOT / 'packaging' / name, destination / 'packaging' / name)
    for source in (ROOT / 'packaging/standalone').iterdir():
        if source.is_file():
            shutil.copy2(source, destination / source.name)
    templates = destination / 'packaging/standalone'
    templates.mkdir()
    for source in (ROOT / 'packaging/standalone').iterdir():
        if source.is_file():
            shutil.copy2(source, templates / source.name)
    shutil.copy2(Path(__file__), destination / 'tools/export_studio_repository.py')
    shutil.copy2(ROOT / 'tools/migrate_studio_profile.py', destination / 'tools/migrate_studio_profile.py')
    shutil.copy2(ROOT / 'tools/check_studio.py', destination / 'tools/check_studio.py')
    for name in ('test_distribution.py', 'test_standalone_export.py', 'test_studio_migration.py'):
        shutil.copy2(ROOT / 'tests' / name, destination / 'tests' / name)
    audit(destination)
    if initialize_git:
        subprocess.run(['git', 'init', '--initial-branch=main', str(destination)], check=True)
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    print('Standalone repository:', export(args.destination))
    print('No accounts, recordings, model weights, Git history or remote were copied.')
