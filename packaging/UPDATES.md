# Updates

Studio's sidebar has **Check for updates**. It opens a non-modal window with the
installed version, latest stable version and the release's notes. An available
update also appears in a banner above the recording controls. **What's new** opens
the same window. Downloads open in the browser; installation is explicit.

The watcher checks GitHub when it starts (after five seconds) and every 24 hours,
reusing a profile cache for 24 hours. Even failed checks are throttled. Manual checks bypass
that cache. A file lock prevents overlapping requests from Studio and the watcher.
An already open Studio reads the shared result within 15 seconds; no extra window
is launched by checking. Only clicking the tray notification opens Studio.

The source is the public `narbotonur/LectureStudio` GitHub Releases endpoint.
No login or personal account information is sent. Drafts and prereleases are
excluded. A commit or an Actions artifact by itself is not an app update.

## Publish an update

1. Change `VERSION` in `annie/version.py` (for example `0.2.1`) and edit
   `packaging/RELEASE_NOTES.md` with the actual changes. Use numeric X.Y.Z versions.
2. Run `python tools/check_studio.py`, commit and push the code.
3. Run **Build Lecture Studio for macOS** in GitHub Actions and enable
   **Create a draft GitHub release after successful builds**. Both Mac builds must pass.
4. Test the draft's Apple Silicon/Intel DMGs on Macs. The workflow's diagnostics
   do not validate microphone hardware, permissions, or Keychain interactions.
5. Publish the draft as a stable release. Its description is the changelog shown
   in the app. Upload a Windows ZIP from `tools/build_studio_release.py` if available.

The workflow refuses to overwrite an existing version. Choose a new version for
new artifacts. Manually created releases work too: use a tag such as `v0.2.1`,
paste the release notes into the description, and attach installers using the
builders' original filenames. Keep `-arm64-`/`-x86_64-` in Mac DMG names and
`LectureStudio-Windows-` in Windows ZIP names.

The first installation containing this feature must be installed manually once.
For source installations, update the Git checkout and dependencies. For packaged
Mac apps, quit Studio and the watcher and replace the app in Applications.
Recordings/settings stay in the separate user profile; credentials stay in Keychain.
Keep the app in the same location for login startup. A rebuilt unsigned app may
ask for Keychain access again.
