# Updates

Studio's sidebar has **Check for updates**. It opens a non-modal window with the
installed version, latest stable version and the release's notes. An available
update also appears in a banner above the recording controls. **What's new** opens
the same window. **Download update** streams the matching installer inside Studio,
with progress and cancellation. Installation is a separate explicit action.

Downloads require SHA-256 from GitHub asset metadata or a matching `.sha256` release
attachment. Both builders already produce checksum files; attach those alongside
the installers. Failed, partial or mismatched downloads cannot be installed.

On macOS, **Open DMG** opens the verified download in Finder. Quit Studio and the
watcher, then drag the app into Applications and confirm replacement. This keeps
the normal macOS installation and signing checks.

For a packaged Windows installation in its original `LectureStudio` folder,
**Install and restart** stages the ZIP next to the installed folder. After your
confirmation and after Studio exits, a small helper swaps the folders and starts
the new app. Quit the watcher and prayer widget first. No process is force-killed.
The previous app remains in `LectureStudio.backup-<id>` beside the installation.
If moving the new app or starting it fails, the helper attempts to restore the old
folder. This detects launch errors, not later crashes inside a running new app.
Recording/generation must finish before installation. Folders requiring elevated
access need manual installation; the updater does not elevate privileges.

Source checkouts or renamed/nonstandard Windows folders still support download
and verification; use **Open downloaded ZIP** for manual replacement or update
the source checkout. The updater never swaps a source tree or a user data folder.
Cancelled preparation can leave a `LectureStudio-update-*` staging folder, which
can be removed later once no update is running. Verified downloads remain in the
profile's `updates` folder; recordings and accounts are stored separately.

The watcher checks GitHub when it starts (after five seconds) and every 24 hours,
reusing a profile cache for 24 hours. Even failed checks are throttled. Manual checks bypass
that cache. A file lock prevents overlapping requests from Studio and the watcher.
An already open Studio reads the shared result within 15 seconds; no extra window
is launched by checking. Only clicking the tray notification opens Studio.

The source is the public `narbotonur/LectureStudio` GitHub Releases endpoint.
No login or personal account information is sent. Drafts and prereleases are
excluded. A commit or an Actions artifact by itself is not an app update.

## Publish an update

1. Change `VERSION` in `annie/version.py` (for example `0.3.1`) and edit
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
paste the release notes into the description, and attach installers and checksums using the
builders' original filenames. Keep `-arm64-`/`-x86_64-` in Mac DMG names and
`LectureStudio-Windows-` in Windows ZIP names.

The first installation containing this feature must be installed manually once.
For source installations, update the Git checkout and dependencies. For packaged
Mac apps, quit Studio and the watcher and replace the app in Applications.
Recordings/settings stay in the separate user profile; credentials stay in Keychain.
Keep the app in the same location for login startup. A rebuilt unsigned app may
ask for Keychain access again.
