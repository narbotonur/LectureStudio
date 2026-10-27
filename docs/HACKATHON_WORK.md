# Lecture Studio hackathon work

Baseline: `f2fd4285479b44d9f54fc98b90750bca1d337974`.
Tag: `pre-hackathon-baseline`. Integration branch: `meta-hackathon`.
All features in that baseline are pre-existing, including the original recording,
notes, calendar, GPA, habits, weekly planner and packaging.

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
