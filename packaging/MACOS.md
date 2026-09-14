# Lecture Studio for macOS

The Mac implementation includes all Studio pages and recording sources, including
native system audio. **Native compilation and hardware validation are still
pending.** Passing Windows tests does not prove that a Mac binary works.
This source kit is not an installer; the Mac build produces the installer.

## Included features

- Local Whisper transcription: microphone, phone, system sound and Mic + system.
- Transcript/notes, flashcards, assistant, slide analysis and multi-file exam prep.
- Weekly schedule, Google Calendar, lecture reminders and meeting prompts.
- Study subjects, start/pause/resume/end timers, active totals and calendar sync.
- Floating dock, portal shortcuts, recording meter, animations and edge snapping.
- Per-user Keychain accounts, setup, silent login watcher and single-instance routing.
- Mac font choices, Command shortcuts via Qt and pixel-accurate trackpad scrolling.

The same application code powers both platforms. Mac audio uses a small Swift
ScreenCaptureKit helper and CoreAudio microphone input. No virtual audio driver
is needed. Local Whisper uses CPU on Mac, not CUDA or Apple GPU acceleration.

## Build without borrowing a friend's Mac

The clean kit contains a manual GitHub Actions workflow:
`.github/workflows/macos-studio.yml`. Put **only this clean source kit** into a
repository you control, then choose Actions > Build Lecture Studio for macOS >
Run workflow. Never upload your working directory, accounts, recordings or tokens.
No repository has been created or uploaded by this implementation.

The workflow builds Intel (`macos-15-intel`) and Apple Silicon (`macos-15`),
compiles the native helper, runs the staged Studio tests, checks the bundled UI
and backend imports, and transcribes generated speech using a public base Whisper
model. Download the DMG/ZIP artifacts after both jobs pass. Runner usage is governed
by your GitHub plan. CI explicitly skips actual Keychain access and cannot test
your recording hardware, Google login or recording permissions.

## Build locally on a Mac

Target macOS 14+ with native Python 3.12 and Apple Command Line Tools
(`xcode-select --install` if absent). Use arm64 Python on Apple Silicon or x86_64
on Intel. Don't mix Rosetta and native packages.

```sh
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r packaging/requirements-macos.txt
python tools/build_macos_audio.py
python -m unittest discover -s tests -p 'test_macos*.py'
python lecture_studio_entry.py --self-test
python lecture_studio_entry.py
```

The self-test uses a disposable profile, creates/removes one dummy Keychain item,
and checks the helper without recording or requesting capture permission.
Source-run permissions may belong to Python/Terminal; recheck them for the app.
Compile the helper before attempting system audio from source.

Build the app, ZIP and drag-to-Applications DMG:

```sh
python tools/build_studio_macos.py
```

Artifacts go to `releases/`; diagnostics remain in the temporary build directory
printed by the script. The frozen self-test must pass before packaging. Optional
`--smoke-model /absolute/path/to/cached/Whisper-model` also transcribes generated
speech without speaker playback or microphone recording.

ONNX Runtime is pinned to 1.23.2 on Mac because it has both Intel and Apple Silicon
wheels; the Windows pin 1.24.4 has no Intel Mac wheel. Dependencies and native code
still need to pass the real Mac build gate.

## Signing and distribution

Default artifacts are marked UNNOTARIZED. For third-party distribution use your
own installed Developer ID Application identity and an existing notarytool profile
in your Mac's Keychain:

```sh
python tools/build_studio_macos.py \
  --sign-identity 'Developer ID Application: Your Name (TEAMID)' \
  --notary-profile 'your-notary-profile'
```

Only this explicit option submits anything to Apple. Credentials are not passed
on the command line. The builder verifies signatures, requires Accepted
notarization, staples/validates the app and DMG, and writes SHA-256 checksums.
No Apple signing identity or credentials are included. Do not disable Gatekeeper
or strip quarantine as a substitute for signing.

Open the DMG and drag Lecture Studio into Applications. Move it to its final
location **before enabling login startup**. Each recipient connects their own
Google account and optional AI key in Accounts & Setup.

## Recording and permissions

- Microphone: selected device at its native sample rate, converted to mono 16 kHz.
  Allow Microphone access when prompted by your explicit recording action.
- System audio: ScreenCaptureKit audio output only. The helper never registers
  a video output and never writes screen images. Allow Screen & System Audio
  Recording (wording varies across macOS releases).
- Mic + system: timestamp-aligned inputs, bounded buffers, silence for gaps and
  saturating mixing. Headphones avoid recording speaker sound twice via the mic.
- Wireless mic: phone IP/port with an uncompressed PCM16 WAV HTTP stream, as on
  Windows. Allow Local Network if macOS requests it.
- Permission denial, stopped device, missing helper or helper failure surfaces a
  recording error. Already received audio passes through the recoverable WAV
  spool. Stop and parent exit close the native helper.

Recording starts only through your action or an accepted recording prompt.
The watcher does not capture microphone/system audio. With permission, it reads
window titles. On macOS 14.2+ it also reads CoreAudio process-activity flags
(metadata, not sound) to recognize course-named Teams meetings. Scans run off the
GUI thread with bounded helper timeouts. Detection remains heuristic and can
depend on language, window title and app version.

## Accounts, startup and storage

- Data: `~/Library/Application Support/Annie/LectureStudio`; an explicit
  `ANNIE_DATA_DIR` override creates a separate profile.
- API keys/OAuth: explicit Keychain backend, no plaintext fallback. Legacy
  `.dpapi` filenames contain only profile-bound references on Mac. Don't copy
  Windows credentials or move a configured profile; reconnect instead.
- Calendar reminders don't require recording permissions. Local timers and notes
  don't require an AI key or Google account.
- Login startup is opt-in through a user LaunchAgent, effective next login.
  It never starts recording and has no Dock icon. Use its menu-bar Open Studio /
  Quit watcher actions. Opening Studio shows a Dock icon; minimizing to the
  floating panel hides it.
- Disabling startup prevents future login launches. Use Quit watcher to end the
  current session safely; changing a setting never kills an active recording.

## Remaining native acceptance gate

Before calling a build production-ready, verify on Intel and Apple Silicon:

- Both CI jobs and bundled generated-speech transcription pass.
- Keychain deny/allow/relaunch, Google connect/disconnect and calendar sync.
- At least 30 minutes of mic/system/dual capture, phone input, Stop and recovery.
- Permission revocation, disconnected devices, display changes and sleep/wake.
- Reminders, real Zoom/Teams/Meet detection, repeated launch while recording.
- Dock animations/edges/multiple displays, schedule scrolling and study totals.
- Signed/notarized download and first launch on a second Mac.

References: [Apple ScreenCaptureKit](https://developer.apple.com/documentation/screencapturekit/capturing-screen-content-in-macos),
[CoreAudio process metadata](https://developer.apple.com/documentation/coreaudio/kaudiohardwarepropertyprocessobjectlist),
[PyInstaller bundles](https://pyinstaller.org/en/stable/spec-files.html),
[Mac CI runners](https://docs.github.com/en/actions/reference/runners/github-hosted-runners).
