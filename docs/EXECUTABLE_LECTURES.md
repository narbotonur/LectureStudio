# Executable Lectures — 0.7.0 preview

28 October 2026. A timestamped BFS lecture can now become a bounded, source-reviewed
graph experiment in the existing English native desktop application.

## Try without an API call

1. Open **More → Executable lecture lab → Load built-in example**.
2. Read the claim, assumptions and source quote. Tick the source-review checkbox,
   then choose **Use this lab**. The example is explicitly authored/offline.
3. Step through BFS with **Next step**, or move the execution slider. Queue means
   the remaining frontier; Discovered means vertices already enqueued.
4. Enable **Use edge weights**. The built-in graph's direct edge costs 10; the
   two-edge alternative costs 2. BFS minimizes hops and takes the direct edge.
5. Predict the **returned BFS route cost** (10), then **Check prediction**. This
   is a practice observation about this graph, not a claim of topic mastery.

Edges are edited as `source target weight`, one per line. Start/target selectors,
edge edits and weight mode are experimental changes. **Apply graph edits** runs
validation before recomputing; invalid or unapplied edits disable checking and
stepping. **Restore original graph** returns to the saved example.

## Build from a lecture

With a configured Meta account and timestamped source discussing BFS, choose
**Build lab from lecture**. One structured request proposes a graph, an
interpretation, assumptions and source references. Exact quotes and time ranges
are checked locally. Unrelated topics are rejected rather than given a generic
BFS lab. A successful request is still a proposal, requiring source review.

The first template is deliberately limited to BFS. Model interpretation and
example assumptions may add conditions not explicitly stated by the teacher.
They are labelled for review. A constructed graph is not a quoted teacher fact;
even a proposed lecture-example graph needs human verification of its values.

**Saved labs → Open saved lab** restores a local source snapshot. Source changes
invalidate the previous unsaved review/experiment; an old lab is not relabelled
as belonging to a new lecture. A corrupt saved row/file is preserved and reported,
and should not prevent the rest of the desktop workspace from opening.

## Connection to Today

Approved study actions mentioning BFS/breadth-first search offer **Open executable
lab**. The lab receives that action's saved, fingerprint-checked transcript,
rather than whichever lecture happens to be active. Predictions retain an action
ID for that study context. A passed check does not automatically complete the
study action or claim mastery.

## Local execution and boundaries

`graph_lab.py` accepts 2–12 nodes and at most 32 edges, finite nonnegative weights
up to 100, known endpoints and valid node IDs. It never executes generated Python,
shell or network commands. BFS snapshots and a Dijkstra comparison are computed
by ordinary deterministic code. Equal-weight mode uses unit costs; weighted mode
uses the edited edge costs. Negative weights are unsupported.

Changing to unequal weights is labelled outside the equal-edge assumption. This
does not refute a correct lecture claim about unweighted graphs. Computation on
one example also does not prove a general theorem or semantic interpretation.

`LabStore` revalidates saved source/spec identities. Each prediction stores the
actual graph, weight mode, hash, answer, computed paths/costs and time. Scoring
is recomputed locally; model-supplied correctness is never trusted.

## Observed validation

- **395 isolated source tests passed**, including 17 engine tests, 21 source/store
  tests, 10 native lab tests and saved study-context integration.
- One engine test compares 120 fixed-seed small graphs against independently
  enumerated simple paths for hop minima, minimum costs and reachability.
- A **real Muse Spark 1.3** medium-effort request on two authored English segments
  produced a 4-node constructed lab with one locally verified source quote.
  Usage: 721 input + 1,701 completion tokens (2,422 total); complete local check
  9.793 seconds. This is one example, not a model-accuracy or classroom study.
- A separate authored edited graph demonstrated BFS cost 10 versus minimum cost
  2. Predicting 2 for the BFS route failed, predicting 10 passed; attempts and the
  source-grounded lab survived reopening. These specific graph numbers were a
  controlled experimental variant, not attributed to the teacher or the model.
- Five actual native captures cover source review, equal/weighted execution and
  prediction at 1180×820 and 720×820. The capture replays saved fictional output
  from the real model check, makes no API call and reads no private lectures.

Microphone-to-lab acceptance, other subjects, arbitrary programs, slide/board
extraction, broad model evaluation and learning efficacy remain unverified or
unsupported. Hackathon credit balance was not checked. Previous app versions and
personal tracker/source data are preserved.

## Reproduce

```powershell
python -B tools/check_studio.py
python -B tools/check_executable_lecture.py
python -B tools/capture_executable_lecture.py
```

Only the explicit live command makes one paid API request, using authored inputs
and a temporary LabStore rather than personal lectures:

```powershell
python -B tools/check_executable_lecture.py --live
```

Local reports: ignored `review_artifacts/executable-lecture/` and
`review_artifacts/executable-native/`. No public release upload or hackathon
submission is implied by these local checks.

## Local package

- Runnable: `releases/LectureStudio-0.7.0-local/LectureStudio.exe`.
- ZIP: `releases/LectureStudio-Windows-x64-20261028-161210.zip`.
- SHA-256: `e5384955fc24c4bb8adde4dcba6edf6dafbfdce14c638cb4d4fb3b995b59fbf9`.

The frozen package and relocated copy passed fresh-profile self-tests, including
the 12-workspace check and the actual weighted graph counterexample. ZIP CRC and
source-stage identity checks passed. This does not substitute for microphone or
classroom acceptance. Older 0.5.0 and 0.6.0 local packages remain available.
