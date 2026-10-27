# Evidence-backed deadline changes (0.6.0)

Lecture Studio can now group mentions of one assignment, display the earlier and
proposed date with transcript quotes, and save a confirmed change as one active
deadline. The English native desktop workspace is retained.

## Try it

1. Configure Meta Model API in **More → Accounts & Setup**. The API model is
   `muse-spark-1.3`; the owner's account was successfully tested during this run.
2. Record/import a timestamped lecture, then open **Review → Analyze current lecture**.
3. Inspect the assignment, both source quotes and the proposed date. Choose a
   date/time where unresolved, then tick the explicit confirmation box.
4. Click **Confirm deadline**. Today shows the current deadline and offers a
   suggested work block even when no GPA course has been configured.
5. **Add to today → Start studying** uses the existing local study timer.

The analysis sends lecture text to Meta only on the user's Analyze action. It
does not automatically change deadlines. All shown times use UTC+05.

## What changed

- A structured model response carries deadline proposals separately from study
  findings. Each reference is checked against the saved transcript segment range.
- The model may suggest an assignment link, but IDs must match the same course
  and canonical assignment name. Lab 2 is distinct from Lab 20.
- A later statement alone is insufficient for an explicit correction. Unknown,
  unsupported or competing dates remain unresolved for manual confirmation.
- SQLite stores immutable proposals and confirmed assignment versions. An outbox
  projects them into the existing JSON Inbox by stable assignment ID/revision.
- Repeated confirmation and interrupted projection are retry-safe. Stale
  revisions cannot overwrite a newer approval.
- Today highlights the pending review count and offers a concrete work step for
  confirmed Inbox deadlines. An accepted work block retains its time while its
  displayed deadline reason follows the current confirmed date.

This is a bounded **single structured-analysis pipeline**, not an implemented
multi-step tool agent. No cloud reasoning trace or hidden chain-of-thought is
stored. Exact quote matching proves transcript location, not speech recognition,
semantic correctness or authority. Human review remains essential.

## Existing data

Legacy Inbox rows, GPA, habits, transcripts and settings are preserved. A new
versioned assignment that matches an existing unlinked legacy Inbox row is
blocked with a linking/migration message, rather than silently creating a second
deadline or changing the old one. A migration/linking UI is not implemented.

If a projection fails after confirmation, Review says **Confirmed, syncing to
Inbox**. Opening Review or Today retries the durable pending operation. SQLite
and JSON are not presented as a single atomic transaction.

## Reproduce checks

```powershell
python -B tools/check_studio.py
python -B tools/check_meta_access.py --check
python -B tools/check_deadline_workflow.py
python -B tools/capture_deadline_changes.py
```

Explicit network checks, each with fictional inputs and no user Inbox changes:

```powershell
python -B tools/check_meta_access.py --live
python -B tools/check_deadline_workflow.py --live
```

The second live command seeds a previously confirmed fictional deadline in a
temporary profile, makes one Meta request and verifies the new date, retained
versions, repeat confirmation and reopening.

## Observed validation

On October 27, a real `muse-spark-1.3` request using medium effort identified the
explicit November 3 → November 6 correction: one proposal, zero rejected items,
one active Inbox deadline after approval/reopening, two retained versions. It
used 923 prompt + 1,527 completion tokens and completed the local workflow in
8.826 seconds. This is one authored English example, not an accuracy benchmark.

The separate account smoke used one request and 125 total tokens. Credit balance
was not inspected. Sanitized reports are under ignored `review_artifacts`;
neither test read personal lectures or changed the user's deadlines.

Native UI previews use a supplied fictional response (not a live model) and a
temporary profile. Six captures cover Review and Today at 1180×820 and 720×820.
Both sizes were visually inspected; the native date/time control's dark styling
was corrected after inspection.

The full isolated source suite passes **346 tests**. The final Windows package
and the relocated copy passed their fresh-profile frozen self-tests.

The frozen live development evaluation passed **10/12** predeclared English text
cases. Ambiguous-next-week and missing-clock cases missed review candidates; the
run did not save any false date (it was analysis-only). See the complete
[evaluation and its two failures](review_artifacts/DEADLINE_EVALUATION.md).

Microphone/classroom acceptance, long recordings, broader language quality and
macOS/device acceptance remain separate work.

## Local Windows build

- Runnable directory: `releases/LectureStudio-0.6.0-local/LectureStudio.exe`.
- Final ZIP: `releases/LectureStudio-Windows-x64-20261027-234454.zip`.
- SHA-256: `8b74a4a4902b1c1e4edc6bfbe9372a250f9521c1fc51955e74007d6daf3e7413`.

The earlier 0.5.0 package is preserved. This build is local; no release upload or
hackathon submission was performed.
