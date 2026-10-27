# Lecture Studio 0.5.0 · local hackathon build

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
