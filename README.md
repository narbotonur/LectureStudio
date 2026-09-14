# Lecture Studio

Standalone university workspace. No voice assistant, wake-word listener or
assistant camera service is included or required.

Record and transcribe lectures, analyze slides, prepare study guides from files,
manage your schedule and Google Calendar, and track timed study sessions.
Meeting/lecture reminders and the floating dock remain available. The prayer
widget is optional and runs separately.

## Run on Windows

Install 64-bit Python (the Windows dependency set was tested with Python 3.14).
In this directory:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r packaging/requirements-studio.txt
.\run_studio.bat
```

After setup, double-click `run_studio.bat`. The launcher prefers this repository's
virtual environment and never falls back to the old ANNIE directory.

For development with an existing compatible Python installation, run
`python lecture_studio_entry.py`. This does not launch the voice assistant.

## Run on macOS

Use Python 3.12 and follow [the macOS setup and permissions guide](packaging/MACOS.md).
Install `packaging/requirements-macos.txt`, compile the native audio helper using
`python tools/build_macos_audio.py`, then run `python lecture_studio_entry.py`.
Native recording and packaging still require testing on a real Mac.

## Modes

```text
python lecture_studio_entry.py                 Open Studio
python lecture_studio_entry.py --watch         Silent meeting/lecture reminders
python lecture_studio_entry.py --prayer-widget Optional prayer widget
python lecture_studio_entry.py --self-test     Isolated offline diagnostics
```

Watching meetings does not itself start a recording. Set up your own accounts in
Studio; enable login startup only after setup. Before switching startup from an
older installation, stop its watcher via its tray menu and disable startup there.
Do not run both installations' watchers together.

## Private data and moving from ANNIE

Code and personal data are separate. The marker `lecture-studio.standalone`
enables the private profile even when running Windows source code:

- Windows: `%LOCALAPPDATA%\Annie\LectureStudio`
- macOS: `~/Library/Application Support/Annie/LectureStudio`
- Override for development: `ANNIE_DATA_DIR` (an absolute directory outside Git).

The existing `annie` Python package and profile names are retained for compatibility;
they do not mean the voice assistant is running. Installed Studio releases may
already use this same profile. Original ANNIE workspace data is not auto-imported.

Exporting this repository copies no accounts, recordings, model weights or personal
settings. Nothing in the original installation is removed. Reconnect Google and
enter your API key through setup for a fresh profile. Do not copy credentials into
this repository, publish personal files, or share an authenticated profile with a
friend. Encrypted credentials are user/device-bound and should not be moved to a
friend's computer. Local library migration should be performed with both Studios
closed, backed up, and with a clearly chosen destination profile.

## Develop and build

```text
python tools/check_studio.py
python tools/build_studio_release.py --stage-only
python tools/build_studio_release.py
python tools/build_studio_macos.py --source-only
```

Windows executables build on Windows; native Mac bundles build on macOS. See
[build instructions](packaging/BUILDING.md). Source archives are not installers.
The Mac workflow is manually triggered, not automatically run on push.

This is a new local Git repository with no commit history or remote configured.
Review `git status` and `git diff --cached` before committing or publishing.

The test runner uses a temporary profile; do not run the test suite against your
authenticated profile. The explicit migration utility is
`python tools/migrate_studio_profile.py OLD_PROFILE EMPTY_PRIVATE_PROFILE`.
It refuses nonempty targets and running source apps, preserves originals, uses
SQLite backup for history, and encrypts credentials for the current OS user.
It copies recordings, local Whisper cache, and recognized study-library folders.
It does not change startup entries or shortcuts. Review disk space first.
