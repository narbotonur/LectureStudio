# Deadline changes: frozen live development evaluation

Date: 27 October 2026. **10 of 12 authored English text cases passed** their predeclared scenario checks in one live run. Two failed. This is a small development evaluation, not a holdout result, an ASR benchmark, a user study or evidence of production accuracy.

## Reproducibility and boundaries

- Cases and expected outputs: [`tools/deadline_evaluation_cases.py`](../../tools/deadline_evaluation_cases.py), written and frozen before inference.
- Fixture source SHA-256: `5fd8c6dc576ea8024e20ea8b26fce05321a4d9d2c700850d4c757fc392b41831`.
- Runtime `annie/lecture_reconciliation.py` SHA-256 at import: `5fc207aabf30a13261f3c95bd14401ca017786b1a96a284d7f55fffe2c1a894a`.
- Runner [`tools/evaluate_deadline_changes.py`](../../tools/evaluate_deadline_changes.py) SHA-256: `fdcc1f2285831f2ea9185dd2861a5a6b94c26c885ff54cb4e1c00c8a5ac1abe1`.
- Model: `muse-spark-1.3`; reasoning effort `medium`; strict JSON schema; 4,096 maximum output tokens; 45-second request timeout; one attempt per case.
- Exactly 12 real API requests, one per case. No retries, repairs, reruns or prompt/expectation changes after seeing results.
- Inputs are author-created fictional snippets and fictional current assignments. No private transcripts, calendars, messages or recordings were used. Application configuration was read only to obtain the already configured credential; no credential values or headers appear in the report.
- No assignment/profile store is instantiated by this runner. Its analysis is read-only and its guard rejects calls to the shared profile atomic writer. It writes evaluation artifacts only, and never approves the proposals.
- This run evaluates the structured reconciliation pipeline with one model call per case. It does not claim to evaluate an implemented tool-calling loop.
- Start: 18:40:04 UTC / 23:40:04 Asia/Qyzylorda. Finish: 18:41:44 UTC / 23:41:44 Asia/Qyzylorda.

Full structured local report: [`review_artifacts/deadline-evaluation/development.json`](../../review_artifacts/deadline-evaluation/development.json). It contains authored expected outputs, validated output summaries, counters and timings. Provider response bodies and authentication material are not dumped. The JSON artifact is excluded from Git by the repository's existing ignore rules.

## Results

| Case | Predeclared expected outcome | Observed result | Pass | Seconds |
| --- | --- | --- | --- | --- |
| Explicit deadline | One Lab 1 proposal, 3 Nov 2026 17:00 UTC+05 | Correct title, date and `new` relation | Yes | 9.537 |
| Explicit correction | One Lab 1 proposal, 6 Nov 17:00; preserve old date and both quotes | Correct new/old dates, two evidence quotes, `explicit_correction` | Yes | 7.253 |
| Unchanged confirmed date | Link confirmed Lab 1 revision 2, keep 3 Nov 17:00 | Correct assignment ID, revision and `unchanged` relation | Yes | 7.870 |
| Ambiguous next week | One unresolved Lab 1 review candidate with unknown date | No proposal returned; zero local rejections | **No** | 6.303 |
| Two assignments | Separate Lab 1 and Lab 2 deadlines | Two correctly separated titles/dates | Yes | 9.528 |
| Lab 2 versus Lab 20 | New Lab 20 must not link to existing Lab 2 | Lab 20 returned as new, assignment ID null | Yes | 5.388 |
| No obligation | No deadline from topic discussion or office hours | No deadline proposals | Yes | 11.896 |
| Negated date | No positive deadline from “NOT due” | No deadline proposals | Yes | 5.354 |
| Hypothetical | Imaginary example must not become a course obligation | No deadline proposals | Yes | 8.466 |
| Changed time | Existing Lab 1 shifts from 17:00 to 18:00 on 3 Nov | Correct ID, revision, old/new times and correction relation | Yes | 5.866 |
| Missing clock time | One review candidate: unknown time, or explicitly assumed 23:59 | No proposal survives; one local rejection | **No** | 11.486 |
| Unsupported exam prediction | No exam hint or exam date inferred from a denial | No deadline proposals or exam hints | Yes | 10.649 |

Title matching in the evaluator normalises case, punctuation and letter/number spacing, while retaining number boundaries: “Lab2” matches “Lab 2”, not “Lab 20”. Positive cases check proposal count, assignment identity, allowed date and relation; relevant cases also check revision, prior date and minimum evidence count. The missing-time case allows either an unknown date/time or 23:59 with an explicit assumption explanation. These expectations were not relaxed after failures.

## Failures and interpretation

1. **Ambiguous next week:** the desired product behaviour is to retain a review candidate for an assignment whose due date is unknown. The model returned no proposal. This misses an item for user review; it did not invent a date. Zero rejections indicates this case was not removed by the local proposal checker.
2. **Missing clock time:** the desired review candidate did not survive the pipeline. One proposal was rejected locally. The runner intentionally does not retain raw provider output or per-field rejection diagnostics, so this run cannot establish the precise rejected field. Do not attribute it to a particular model or validation error without another separately identified experiment.

The correction and changed-time examples demonstrate the intended behaviour on these specific inputs. Negative and hypothetical examples did not produce positive deadlines in this run. Neither observation establishes a general hallucination rate. There is no single-pass baseline comparison, repeated-run stability check or held-out set here. No active deadline persistence, crash recovery, UI action or audio capture is evaluated by these cases.

Follow-up: add safe per-field rejection categories and preserve ambiguous review candidates, then evaluate on a new versioned development run. Keep this original result and frozen expectations unchanged. A later tuned result must not be presented as independent holdout validation.

## Usage, latency and spending

- Prompt tokens: **9,939**.
- Completion tokens, including provider-reported reasoning usage: **19,321**.
- Total tokens: **29,260**.
- Median case latency: **8.168 s**.
- Nearest-rank sample p95: **11.896 s**, which is also the maximum among only 12 samples. It is not a production p95 estimate.
- Sum of case times: **99.596 s**.
- Token-rate estimate with all inputs charged at uncached Spark Standard rates: **$0.094538** (`9,939 × $1.25/M + 19,321 × $4.25/M`). Cached discounts or account billing adjustments are not inferred. [Official pricing](https://dev.meta.ai/docs/pricing-rate-limits).
- The runner uses a $0.25 pre-request budget guard with a conservative UTF-8 input bound and maximum output reservation. It refuses a second default report overwrite to avoid accidental rerun billing.
- A successful request proves API access, **not** that the $150 hackathon credit was granted. Balance and credits remain unverified.

## Commands

Offline fixture validation/listing, with no credential read or API call:

```powershell
python -B tools/evaluate_deadline_changes.py
```

The actual run used:

```powershell
python -B -u tools/evaluate_deadline_changes.py --live --expected-sha256 5fd8c6dc576ea8024e20ea8b26fce05321a4d9d2c700850d4c757fc392b41831
```

It exits with status 1 because two scenario checks failed. That is a recorded evaluation outcome, not a failed launch. A future paid rerun must explicitly choose a new report path; the fixture digest must still match, or the runner makes no calls.
