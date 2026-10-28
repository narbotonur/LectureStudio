# Lecture Studio — Campus Radar

Current target: **Indie Developer**, **Build for Your World**.
This page is submission copy and a reviewer guide. It does not mean the project
has been submitted, or that a demo video has been recorded or uploaded.

## Ready-to-use project copy

### One-line description

Catch unannounced homework and review lecture deadline changes with source evidence.

### Problem

At university, homework can appear in WeBWorK without a notification. A lecturer
can also correct a deadline halfway through class. Students have to keep checking
different sources, and a transcript alone does not tell them which date to act on.

### What I built

I extended my existing Lecture Studio desktop app with Campus Radar and a
Meta-powered evidence-review workflow. Radar watches explicitly selected NU
WeBWorK courses through a local Chrome extension, records observed changes and
requests Windows alerts. It keeps the source link and last successful check
visible, so an unavailable source is not mistaken for an empty to-do list.

For lectures, Muse Spark proposes assignment instructions and deadline corrections
from timestamped text. The app checks the referenced quotes and asks the student
to confirm the assignment and date. A confirmed correction keeps the previous
version and updates one active local deadline. Repeating confirmation does not
create another deadline.

These are two supported input workflows in one desktop workspace. Automatic
matching and conflict resolution between WebWork and lecture sources is not
implemented in this release.

### Why Meta matters

Muse Spark 1.3 performs the semantic step: identifying an assignment and whether
the lecturer explicitly corrected an earlier date. Local code checks references,
versions and allowed changes; the student makes the final date decision.
This is more specific than a general education chatbot. It turns an interpreted
instruction into a reviewable, durable action while retaining its source.

Radar itself parses structured WebWork metadata locally. It does not need an
LLM, and university account data is not silently sent to Meta. Muse Code used
for development is not presented as a replacement for model use in the product.

### Technical implementation

Python/PyQt desktop UI; local Whisper with optional cloud transcription;
schema-constrained Meta analysis; exact transcript-reference checks; versioned
SQLite obligations and a durable Inbox projection; a Chrome Manifest V3 adapter;
an authenticated loopback receiver with protected pairing; and a notification
ledger separate from the student's review state.

An additional bounded BFS lab uses a Meta-generated, source-backed interpretation
and deterministic local graph execution. It is available in More and is not the
main student-deadline story.

### What is new during the hackathon

The baseline is [f2fd428](https://github.com/narbotonur/LectureStudio/tree/pre-hackathon-baseline).
The [comparison](https://github.com/narbotonur/LectureStudio/compare/pre-hackathon-baseline...v0.8.0)
identifies the new work.

- New: Meta adapters, timestamped lecture review, source checks, deadline
  reconciliation and version history, approval/recovery logic, Today integration,
  Campus Radar's domain/UI/receiver/Chrome adapter, and the bounded BFS lab.
- Improvements to existing features: cold-start transcription handling, saved
  transcript workflow, flexible routines and inline grade scenarios.
- Pre-existing: the original recorder, note/flashcard tools, calendar, original
  GPA/habit/weekly-planner features, study timer and packaging foundations.

The application was not created from scratch during the event. Coding agents are
development tools, not additional human team members. The final participant list
must include every actual human collaborator; confirm it in the submission form.

### Validation and honest limits

- 440 isolated Python tests; 12 offline Node adapter tests; Windows frozen-app
  diagnostics with native protected storage and 13 workspaces.
- Owner-authorized live WebWork capture and a later automatic browser-alarm check:
  six observations, unchanged event count on the second capture.
- A real Muse Spark correction example preserved two deadline versions and one
  active Inbox entry. A separate live BFS example generated a checked graph spec.
- Frozen development evaluation: 10 of 12 authored text scenarios met expectations.
  Ambiguous-date and missing-time candidates were missed. This is not held-out,
  classroom, multilingual or speech-recognition accuracy.
- Windows accepted a notification request; its on-screen appearance was not
  visually confirmed. No real university deadline was edited to induce a test.
- Gmail, opportunity ranking, advance reminders and cross-source reconciliation
  remain future work. No claim of worldwide uniqueness or guaranteed grades.

## Reviewer quick start

1. Download the [v0.8.0 Windows release](https://github.com/narbotonur/LectureStudio/releases/tag/v0.8.0)
   and follow its instructions. A Meta API key is needed only for model-backed
   lecture analysis. Radar requires a permitted, signed-in NU WebWork course.
2. For a reproducible synthetic Radar example without a university account or
   Meta request, run from source:

   ```powershell
   git clone --branch v0.8.0 https://github.com/narbotonur/LectureStudio.git
   cd LectureStudio
   python -m pip install PyQt5==5.15.11
   python -B tools/demo_campus_radar.py
   ```

   The clearly marked demo uses the real local receiver and UI with synthetic
   capture payloads. It is not a demonstration of a signed-in Chrome session.
3. To run the broader application and reproduce the offline lecture-correction
   path, install the full dependencies first:

   ```powershell
   python -m pip install -r packaging/requirements-studio.txt
   python -B tools/check_deadline_workflow.py
   python -B tools/capture_deadline_changes.py
   ```

   These use supplied model responses and temporary profiles. For an optional
   live model request, configure your own key and explicitly use
   `python -B tools/check_deadline_workflow.py --live`. API usage may be billed.
4. Validation commands:

   ```powershell
   python -B tools/check_studio.py
   node --test browser/campus-radar/tests/*.test.cjs
   ```

See [Radar evidence](CAMPUS_RADAR_IMPLEMENTATION.md),
[deadline workflow](DEADLINE_WORKFLOW.md) and
[development evaluation](review_artifacts/DEADLINE_EVALUATION.md).

## Three-minute video script

The final video is still to be recorded. Use a temporary demo profile, authored
transcript and synthetic assignment data. Show a clear **synthetic input / offline
response / live Meta call** label for the corresponding section. A prerecorded
or accelerated model response must be labelled; do not claim a fixture is live.

| Time | Show | Suggested narration |
| --- | --- | --- |
| 0:00–0:20 | Problem and project title | “Homework can appear in WebWork without notifying us. Deadlines can also change during a lecture. I built a way to catch those changes and check the evidence before acting.” |
| 0:20–0:50 | Synthetic Radar baseline, new set, changed date | “Radar records what it actually observed and when it checked. Repeating the same capture does not create duplicate changes. This screen uses a simulated source; the signed-in NU integration was tested separately.” |
| 0:50–1:15 | Authored transcript with November 3 → November 6 correction | “For lecture instructions, Muse Spark identifies a possible correction. The quotes and timestamps stay visible. Here is the original date and the explicit correction.” |
| 1:15–1:50 | Review proposal, confirm assignment/date, one active Inbox deadline | “The model proposes; the student confirms. The new date becomes one active deadline, while the earlier version stays in history.” |
| 1:50–2:15 | Reopen/repeat the confirmed operation | “Retries do not create another deadline. A failed or partial source check does not mean the assignment is complete.” |
| 2:15–2:40 | Architecture and actual results | “Meta handles the meaning in lecture text. Local code checks sources and versions. The app and browser adapter passed their test suites, and a real browser alarm captured a course without a manual check.” |
| 2:40–3:00 | Baseline/new-work comparison and current limits | “The original recorder and trackers predate the hackathon. Evidence review, versioned corrections and Campus Radar are new. Gmail and automatic cross-source reconciliation are next, not shipped claims.” |

Do not spend this three-minute deadline story touring the old trackers or the
optional BFS lab. A short, working path is more useful than listing every screen.

## Submission gate

The [public event page](https://cerebralvalley.ai/e/meta-ai-developer-hackathon)
lists the deadline as **November 4, 2026, 21:00 Eastern**. The participant guide
provided by the owner specifies EST: **November 5, 07:00 Asia/Qyzylorda (UTC+05)**.
Use **November 4, 20:00 Qyzylorda** as the internal submission target.

The supplied participant guide requires a public repository, a publicly accessible
three-minute video, one project submission per team, and an accurate list of
contributors. It weights Impact 30%, Meta tooling 25%, Technical Depth 20% and
Demo 25%. The public event page was checked October 28; the detailed page needs
participant access. Recheck the live form and organizer announcements before
submitting, including any updates to these requirements.

Still required from the representative: record/review the final video, provide its
accessible link, confirm the actual participant list/track, and review the final
CV submission fields and any required declarations. The field names and video
URL below are intentionally not invented. Map this copy to the actual form.

- Repository: `https://github.com/narbotonur/LectureStudio/tree/v0.8.0`
- Release: `https://github.com/narbotonur/LectureStudio/releases/tag/v0.8.0`
- Video URL: **not recorded/uploaded yet**.
- Submission receipt: **not submitted**.
