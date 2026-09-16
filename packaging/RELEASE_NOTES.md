# Lecture Studio 0.4.0

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
