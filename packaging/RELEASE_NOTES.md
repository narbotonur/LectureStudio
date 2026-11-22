# Lecture Studio 0.9.2 · Transcript navigation

## What's new since 0.8.0

- **Lecture workspace.** Open Notes, Transcript, and Flashcards from the same workspace. Open the library from Today or with Ctrl+O. Import audio directly from Lecture. Recording controls stay accessible when you switch sections.
- **Transcript reader.** Find phrases in visible passages with Ctrl+F. F3 and Shift+F3 move between matches. Adjust playback speed, see the current passage, and save named bookmarks at exact times. Bookmarks reopen with the lecture.
- **Editing and audio.** Correct passages with F2, rename or merge speaker groups, and review overlapping speech. Test the input with a short recording, prepare Whisper, and install optional local Sherpa models from the app.
- **Local archive.** Search lectures by title, course, tags, or content. Edit lecture details, link an audio file, restore revisions, or export WebVTT captions.
- **Study workflow.** Review local deadlines and suggested study blocks, edit routine check-ins and study sessions, forecast course scores, and review flashcards. The optional Campus Radar Chrome adapter adds per-course controls and freshness information.
- **Desktop design.** Updated navigation, typography, transcript and notes layouts. Compact Windows layout checked at 100%, 125%, and 150% scaling.

## Install

Download the Windows x64 ZIP and its SHA-256 file. Extract the full ZIP and open `LectureStudio.exe`. Keep the worker and `_internal` folder beside it. The Windows executable is unsigned.

Close Studio and back up `%LOCALAPPDATA%\Annie\LectureStudio` before replacing an older installation. Install the optional Campus Radar adapter as an unpacked Chrome extension only if you use it. The adapter has its own ZIP and checksum.

## Verification

The source suite and frozen Windows smoke tests use clean profiles and test audio. Classroom speaker attribution and physical microphone behavior depend on the recording and device. See the package's `START_HERE.md` for setup.

## Lecture Studio 0.9.1 · Audio setup and speaker review

- Check the selected audio source with a five-second local recording, peak level, and playback. The recording view displays audio input and transcript processing separately.
- Prepare Whisper on demand or install the optional Sherpa models from Studio. The speaker download shows transfer progress and validates the files before use.
- Filter a transcript by speaker, preview an excerpt, rename or merge speakers, and assign selected passages. Filter unassigned passages and overlapping speech for review.
- Keep the window at its selected size when switching workspace tabs in compact mode.

## Lecture Studio 0.9.0 · Local lecture library

- Search lecture titles, courses, tags, notes and transcript passages. Edit the lecture title, course, date and content with local autosave and revision history.
- Link audio to a transcript, double-click a passage to play it, or click its time. Review can open the archived lecture behind a finding. Export captions as WebVTT.
- Use the optional local speaker models to label recurring voices. Right-click a passage to edit speaker groups, reassign passages or correct text. Review retains the original source.
- Manage saved deadlines in Deadline Inbox. Today checks due times and conflicts, and supports manual and pinned blocks. Schedule supports local classes and a compact day view.
- Edit completed study sessions and past routine check-ins. Academics supports semester filters, archived courses, score pasting and component forecasts.
- Export editable flashcards as Anki TSV or review due cards in Studio. Campus Radar adds per-course controls, freshness and deadline drafts. Saved lecture labs support graph variants.

## Upgrade and recovery

1. Close Lecture Studio and back up the entire per-user profile. On Windows the
   default is `%LOCALAPPDATA%\Annie\LectureStudio`. On macOS it is
   `~/Library/Application Support/Annie/LectureStudio`.
2. Install the new app in a separate app folder and open Studio. The lecture
   library reads older transcript archives. A save writes version 2 and adds
   speaker labels, notes and other lecture data where present.
3. If the original audio is missing, open the transcript and choose **Link audio**.
   See [Local speaker analysis](DIARIZATION.md) for optional model files.
4. To revert, close Studio before restoring the profile backup. Keep a separate
   copy of the updated profile if you need materials saved after the upgrade.

## Previous version · 0.8.0 · Campus Radar preview

- More → Campus Radar reviews observed coursework changes and source freshness; Today links to unreviewed changes.
- An optional local Chrome extension checks explicitly watched NU WeBWorK courses using a signed-in course tab, about every five minutes while Chrome runs.
- An authenticated receiver binds only to 127.0.0.1:8768, starts explicitly, and keeps pairing protected with DPAPI / Keychain.
- Initial assignment observations produce one baseline summary per course. Later new observations and changed due/closing/status fields request Windows notifications with persistent deduplication.
- Due dates and closing times remain distinct; missing cards, login errors, unsupported formats and partial captures never imply assignment completion or a clean check.

This adapter supports the English NU course index and regular assignments. Chrome,
a signed-in course tab, and the enabled desktop receiver must remain running.
Windows may suppress notifications. Advance deadline reminders, Gmail and exam
catch-up are not connected in this preview. Extension installation is a separate
explicit action; it is not installed by launching Studio.

## Previous version: 0.7.0 · executable lectures preview

- More → Executable lecture lab builds a bounded BFS experiment from timestamped lecture text.
- Exact source quotes, interpreted claims and constructed example assumptions are shown for review before use.
- Native graph controls edit edges, endpoints and weight mode; queue/discovery state can be stepped through.
- BFS hop paths and Dijkstra minimum-cost paths are computed locally, with explicit equal-weight assumptions.
- Prediction checks save the graph, mode and computed result; they do not claim topic mastery.
- Saved labs reopen locally. Approved BFS study actions in Today open their own saved lecture context.
- A real Muse Spark 1.3 request on authored English text produced a source-checked lab; no arbitrary model code is executed.

The first template supports small BFS graphs only. Generated interpretation still
needs human review; source quotes do not prove semantic correctness. The built-in
example is explicitly authored/offline. Classroom learning efficacy is untested.

## Previous version: 0.6.0

- Review groups mentions of an assignment and proposes a source-backed deadline correction.
- Earlier and later quotes, the previous date and the proposed date remain visible before confirmation.
- A native date/time picker and explicit assignment/date confirmation precede local deadline changes.
- Versioned assignments keep history and project one active deadline into Inbox, with retry-safe recovery.
- Today highlights findings awaiting review. Existing English desktop navigation is retained.
- A live Muse Spark 1.3 check on a fictional correction completed successfully; it did not read or change personal lectures or deadlines.

This is a structured analysis pipeline, not an implemented multi-step tool agent.
Quote matching does not prove speech-recognition or semantic correctness. Real
classroom/microphone acceptance, broader live model evaluation and credit balance
verification remain separate. Legacy deadlines are preserved and not silently merged.

## Previous version: 0.5.0

- Today combines upcoming classes, approved study actions and daily routines.
- Review finds lecture actions through Muse Spark and verifies quotes against timestamped segments before approval.
- Optional Muse Voice transcription, with Local Whisper retained for offline use and unsupported languages.
- Cold model preparation no longer postpones local audio capture; legacy automatic notes are opt-in.
- Timestamped transcripts save locally and reopen through More.
- Routines have minimum/normal/ideal goals and independent duration; GPA supports inline raw scores and what-if.

The Meta adapters were verified with offline transport fixtures. This build still
needs a configured Meta key and live account testing. Source, package, microphone
and classroom validation are separate checks; see the hackathon work log.

## Previous version: 0.4.0

This release expands Lecture Studio from lecture capture into a complete,
local-first study workspace.

## New

- Track courses, assessment weights, target grades, and estimated semester GPA.
- Build habits with Done, Minutes, or Count goals and a weekly progress view.
- Generate a reviewable weekly plan around calendar events, prayer times, Jumuah,
  habits, credits, grade gaps, and confirmed deadlines.
- Import a syllabus or paste an assignment page into the review-first Deadline
  Inbox before anything is stored.
- Preview a private Moodle calendar export without giving Studio your password.

## Improved

- Meeting detection routes Start to the already-running Studio instead of opening
  a duplicate window.
- The study timer counts active time only and can sync completed sessions to Google
  Calendar when enabled.
- The schedule uses denser calendar blocks and faster scrolling.
- macOS and Windows update downloads are verified with SHA-256 before installation.
- Public documentation now includes reproducible demo media, an architecture map,
  privacy guidance, and a repository audit.

## Before installing

Quit the watcher and prayer widget, then close Lecture Studio. Your profile remains
separate from the application and is preserved during replacement.

macOS builds are not notarized yet. Choose the DMG matching Apple Silicon (`arm64`)
or Intel (`x86_64`) and follow the macOS permissions guide.
