# Lecture Studio hackathon work

Baseline: `f2fd4285479b44d9f54fc98b90750bca1d337974`.
Tag: `pre-hackathon-baseline`. Integration branch: `meta-hackathon`.
All features in that baseline are pre-existing, including the original recording,
notes, calendar, GPA, habits, weekly planner and packaging.

## Release candidate status — October 28, 0.8.0

Current reviewer instructions and submission copy are in
[`HACKATHON_SUBMISSION.md`](HACKATHON_SUBMISSION.md). Campus Radar now has a verified
real course capture and a second automatic browser-alarm check; see
[`CAMPUS_RADAR_IMPLEMENTATION.md`](CAMPUS_RADAR_IMPLEMENTATION.md). Final source
validation: 440 Python tests and 12 offline Node tests; the Windows frozen build
passed its clean-profile self-test. The current Windows artifact is
`LectureStudio-Windows-x64-20261028-213139.zip`.

The dates, work assignments and verification entries below are a historical work
log. Superseded plans do not describe pending work in the current release.
The three-minute submission video and the final CV submission remain outstanding.

## Strategy update after discussion on October 27

The owner confirmed the main pain is missing assignments, deadlines or changed
requirements, and has about one hour per day for validation/demo work.
The selected next direction is evidence-backed deadline reconciliation with
explicit approval, rather than expanding the trackers. The historical local
strategy/contracts drafts are superseded for reviewers by
[`HACKATHON_SUBMISSION.md`](HACKATHON_SUBMISSION.md).
The reconciliation and durable outbox slice has since been implemented in 0.6.0;
see [`DEADLINE_WORKFLOW.md`](DEADLINE_WORKFLOW.md). A multi-step tool loop remains
unimplemented; the shipped analysis uses one structured request. These priorities
supersede the earlier feature-first milestones below. Existing completed
work and verification records remain historical evidence, not claims about the
new proposed implementation.

## Work ownership

| Workstream | Branch | Ownership |
| --- | --- | --- |
| Integration | meta-hackathon | main shell, settings, Today, scheduling, documentation |
| Transcription | hackathon/transcription | runtime, Meta Voice adapter, segments, benchmark |
| Verified actions | hackathon/verified-agent | extraction, evidence checks, action store, Review |
| Trackers | hackathon/trackers | habits and GPA domain/UI, additive migrations |

Independent work runs in separate worktrees; integration is reviewed and tested.

## Delivery milestones

Dates are in Asia/Qyzylorda (UTC+05:00). Milestones can be completed early;
they are not instructions to leave an agent waiting until that day.

| Date | Acceptance milestone |
| --- | --- |
| October 27 | Baseline, isolated workstreams, documented API contracts and diagnostics |
| October 28 | Local and optional Meta Voice transcription, saved audio, timestamped segments |
| October 29 | Structured findings, source/timestamp validation, negative fixtures |
| October 30 | Review, explicit approval and durable local study actions |
| October 31 | Today, upcoming schedule, routines and focused study flow |
| November 1 | Inline grades, what-if and planner suggestions; feature cut-off |
| November 2 | Regression tests, recording benchmark and clean-profile walkthrough |
| November 3 | Three-minute video, public-access checks and submission copy |
| November 4 | Submission buffer, no new features |

Submission cutoff from the participant guide: November 4, 21:00 EST,
which is November 5, 07:00 in Qyzylorda. Submit earlier.

## Verification boundaries

Offline fixtures, model-backed inference, microphone capture, packaged builds and
user acceptance are separate checks. A mocked API test is not a live API result.
Private recordings and channel messages must not be used as public demo assets.
Meta Voice is optional: its documented evaluated language list excludes Russian
and Kazakh. A successful account request must not be inferred from adapter tests.

The final work log records completed changes and outstanding live checks.

## Implemented and checked on October 27

- Integrated commits for timestamped transcription, Meta adapters, evidence review,
  routines, inline grades and Today into `meta-hackathon`.
- Retained the original advanced weekly view in More, with explicit habit durations
  and prayer/bedtime anchors. The primary navigation now has five entries.
- Fixed cold-model startup so recording writes audio before loading the model.
- Fixed credential refresh in a persistent worker and task reappearance after
  postponement. These have regression tests.
- Full source suite: 287 tests passed, including CUDA runtime discovery. Source self-test passed with a clean temporary
  profile, including encrypted-secret storage and all eleven internal workspaces.
- Offline fictional end-to-end check: three findings retained, one unsupported quote
  rejected, one local deadline and two study tasks approved, local study timer started.
- Inspected full-window Today, Review, Academics and Routines screenshots, plus
  all four screens at a 720px window width. Previews are generated by
  `tools/capture_hackathon.py` into ignored `review_artifacts/hackathon`.
- Synthetic English speech was tested on CPU and, after repairing runtime discovery,
  on GPU. Existing CUDA/cuDNN wheels were found outside the loader path; no installation
  or system PATH changes were needed. These are different fixtures, not an accuracy
  evaluation or a controlled speed comparison.
- Windows 0.5.0 package built and passed frozen self-test. Its actual isolated worker
  transcribed a synthetic 10.368-second English WAV on GPU in 1.625 seconds of
  inference and shut down cleanly. This is a file-input check, not a microphone test.
- Local package: `releases/LectureStudio-0.5.0-local/LectureStudio.exe`.
  ZIP: `releases/LectureStudio-Windows-x64-20261027-221309.zip`.
  SHA-256: `6225a55168115067b14ff95e711a1a55a40bebdb8f42af3eb0820680cce2582d`.

## Still required before submission

### Executable Lectures slice on October 28

- Implemented the approved bounded BFS lab in the existing English desktop UI;
  source review, graph edits, local step execution and persisted predictions.
- Real Muse Spark 1.3 generated a checked lab from authored English input.
- Full source suite: 395 tests passed. The graph suite includes an independent
  exhaustive-path oracle on 120 small fixed-seed graphs.
- Actual native captures at 720/1180 inspected; capture uses a replay, not a new
  model call. See [`EXECUTABLE_LECTURES.md`](EXECUTABLE_LECTURES.md).
- General topics, arbitrary generated programs, real classroom learning efficacy
  and slide/board extraction remain outside this first template.
- Windows 0.7.0 and relocated copy passed frozen self-tests including a computed
  graph counterexample. Final ZIP CRC verified. Runnable:
  `releases/LectureStudio-0.7.0-local/LectureStudio.exe`.
  ZIP: `LectureStudio-Windows-x64-20261028-161210.zip`.
  SHA-256: `e5384955fc24c4bb8adde4dcba6edf6dafbfdce14c638cb4d4fb3b995b59fbf9`.

### Delivered in the subsequent 0.6.0 work

- Configured account successfully called Muse Spark 1.3; the live fictional
  correction preserved two confirmed versions and one active Inbox deadline.
- Native Review displays both quotes and requires explicit date/assignment
  confirmation. Today exposes pending findings and suggests work on confirmed
  deadlines even without GPA setup.
- SQLite versions and a durable, idempotent Inbox outbox protect retries and
  stale revisions. Matching unlinked legacy deadlines are blocked safely;
  a legacy linking/migration interface is still required for that case.
- Final source suite: 346 tests passed. Native screenshots at 720/1180 inspected.
- Frozen development evaluation: 10/12 authored text cases passed, with two missed
  candidates recorded unchanged. This is not classroom or held-out validation.
- Windows 0.6.0 and relocated self-test passed. Runnable app:
  `releases/LectureStudio-0.6.0-local/LectureStudio.exe`.
  Final ZIP: `LectureStudio-Windows-x64-20261027-234454.zip`.
  SHA-256: `8b74a4a4902b1c1e4edc6bfbe9372a250f9521c1fc51955e74007d6daf3e7413`.
- No public upload, repository push or submission. See `DEADLINE_WORKFLOW.md`
  and `DEMO_HACKATHON.md` for the implemented behavior and three-minute storyboard.

### Remaining validation

- Meta Spark access is now confirmed with the owner's configured account and
  fictional English inputs. The $150 credit balance and optional Meta Voice
  access remain unverified; do not infer them from the Spark request.
- Compare real lecture accents/noise and English/Russian/Kazakh quality on material
  the owner permits to process. Test a full class and cloud interruption/rotation.
- Validate real microphone capture and full-class behavior. The Windows file-input
  check does not establish microphone or macOS device acceptance.
- Record the three-minute video, check public access and submit. Repository pushes,
  release publication and hackathon submission were not performed in this run.

## Optional follow-up features

UI/UX research and OYSAN-derived visual direction were explored in local design
drafts and an offline interactive concept, rather than shipped as a web redesign.
This is a design proposal, not an implemented native redesign. It includes
screen priorities, daily acceptance milestones and account-access states from
the organizer FAQ supplied by the owner.
Owner clarification: retain English UI and Lecture Studio's desktop structure.
Borrow only visual styling from OYSAN (colors, typography, spacing and control
appearance), not its website layout or navigation behavior.

Bulk syllabus-to-grade-component import, richer calendar rescheduling, SAM diagram
extraction and an open-weight deployment remain outside this implementation. They
should follow live validation of the main lecture-to-action scenario.
