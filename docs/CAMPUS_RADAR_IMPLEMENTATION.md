# Campus Radar preview — 0.8.0

The first connected workflow watches explicitly selected NU WeBWorK courses and
records new observations and changes in the native Lecture Studio workspace.
It addresses missing homework announcements without requiring a recording of
the lecture. Gmail opportunities and exam catch-up remain subsequent work.

## What ships

- More → Campus Radar: course coverage, last successful capture, partial/error
  states, old/new dates and quoted source fields, source links and review state.
- Today links to the unreviewed Radar changes. Open assignments appear above
  closed baseline history. Reviewing a change does not complete an assignment.
- Chrome MV3 development extension under `browser/campus-radar`. The user opts
  into each course. No Gmail, cookies, scripting, broad tabs or notification
  permission. Queries are removed from assignment links before transmission.
- Existing signed-in course tabs request only their same-origin course index.
  The adapter parses the 2.20 server assignment container; section headings are
  generated later by WeBWorK JavaScript and are not required in fetched HTML.
- Explicit offset dates only. `due_at` and `closes_at` are separate. Missing dates
  remain null. Login, unsupported structures and empty extraction are failures.
  Unsupported assignment formats or dates yield partial coverage.
- Authenticated HTTP receiver on `127.0.0.1:8768`, explicitly enabled in the UI.
  Pairing uses DPAPI on Windows or Keychain on macOS. Website origins, wrong host,
  invalid captures, duplicate JSON keys and overlarge bodies are rejected.
- Windows tray notifications: one baseline summary per course, then grouped
  observed changes. A persistent delivery ledger is separate from review state.
  Unsupported/disabled notifications retain pending delivery and show an error.

## Evidence and limits

- Live owner-authorized Chrome installation and Moodle sign-in succeeded.
- A real course index reached the packaged app: six assignment observations,
  one explicitly open with an exact due timestamp, five explicitly closed with
  unknown due timestamps. Personal identifiers and captures stay in the private
  application profile; repository tests use synthetic coursework.
- Native rendered UI was inspected with the real source and open homework first.
- The real browser alarm completed a second capture at 21:45 UTC+05 without
  pressing Check now: two snapshots, six items and still six observation events.
  The persistent notification ledger acknowledged the six baseline events as
  one summary request after Windows tray messages were explicitly enabled by
  the owner. The alert's rendered appearance was not visually confirmed.
- 440 Python tests passed in an isolated profile; the frozen Windows self-test
  passed including protected storage and all 13 workspaces. An earlier repeat
  exposed an intermittent pre-existing macOS helper stdin-close error on Windows;
  its focused rerun and the final full run passed. This is not macOS device proof.
- Twelve offline Node tests cover date/link parsing, server container acquisition,
  failure/partial capture, adjacent HTML nodes, stale tab fallback and stop races.
- No assignment was submitted, edited or marked complete. No course metadata is
  sent to an AI provider. No Gmail account was read or connected.

Both Chrome and the enabled desktop receiver must remain running, with a signed-in
course tab. Browser alarms can be delayed and cannot guarantee continuous coverage
during sleep or shutdown. No advance deadline-reminder scheduler is included yet.
Notification API acceptance is a delivery attempt, not proof that Windows rendered
an alert or the student read it. A real changed deadline/new assignment has not
been induced on the university service; diff and retry behavior use local fixtures.

The extension is installed locally with explicit user approval, not distributed
through the Chrome Web Store. The app and extension are separate local artifacts;
running Studio never silently installs an extension. No release was published.
