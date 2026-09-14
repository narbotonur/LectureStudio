# Building the shareable Windows app

Use a dedicated Windows x64 Python environment. Install `packaging/requirements-studio.txt`, then run:

```
python tools/build_studio_release.py
```

The builder creates a fresh allowlisted staging directory, checks source for embedded credentials/personal defaults, builds GUI and console-worker executables, runs offline frozen-app diagnostics with disposable data, and writes a timestamped ZIP plus SHA-256 checksum under `releases`.
It does not copy recordings, settings, OAuth clients/tokens, model caches, browsers, or the assistant's unrelated skills. Whisper model weights download on the recipient's first use.

The allowlist is in `tools/build_studio_release.py`. New runtime modules/assets must be explicitly added there. The frozen entry dispatches `--whisper-service` before any GUI import; do not replace the console worker with the windowed executable.

For a faster retry after a build failure, use `--reuse-build` with the exact temporary `lecture-studio-build-*` directory printed by the builder. Reuse is limited to those directories. Keep temporary build diagnostics until you have tested the release.

Test a release on a clean Windows machine as well as the included offline diagnostics. Verify microphone/system/phone audio and Google/Gemini with test accounts; do not ship a publisher's login token for convenience. Signing the executables requires a publisher-controlled code-signing certificate and is not done automatically.

The runtime honors `ANNIE_DATA_DIR` for isolated testing. Frozen builds otherwise use `%LOCALAPPDATA%\Annie\LectureStudio`. Source development keeps its existing workspace data to avoid migrating or deleting the developer's history unexpectedly.

Useful checks:

```
python -m unittest discover -s tests -v
python lecture_studio_entry.py --self-test
LectureStudioWorker.exe --self-test
```
