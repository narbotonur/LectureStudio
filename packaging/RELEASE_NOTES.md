# Lecture Studio 0.7.0 · executable lectures preview

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
