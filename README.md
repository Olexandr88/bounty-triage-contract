# Bug Bounty Triage: GenLayer Intelligent Contract

An AI-assisted triage contract for bug-bounty reports. A reporter files a
finding, the maintainer responds, and validators agree on **one consequential
outcome**: a verdict from a fixed enum. The payout is derived from that verdict
by a table, never negotiated, so there is no tolerance window on the money.

## Lifecycle

`SUBMITTED -> RESPONDED -> ADJUDICATED -> (appeal) -> FINALIZED`

- `submit_report(maintainer, project, evidence_url, summary, bounty)` returns a sequential report id.
- `respond(report_id, response)` is callable only by the maintainer.
- `adjudicate(report_id)` fetches the evidence URL, asks the LLM for a verdict, and records it.
- `appeal(report_id, reason)` is allowed once, by either party, and its result is final.
- `finalize(report_id)` accepts the verdict without appealing.
- `get_report(report_id)` is a view returning status, verdict, rationale, payout and appeal flag.

## Verdicts and payouts

| Verdict | Payout (share of bounty) |
|---|---|
| CONFIRMED_CRITICAL | 100% |
| CONFIRMED_HIGH | 50% |
| CONFIRMED_LOW | 10% |
| FALSE_POSITIVE | 0% |
| NEEDS_EVIDENCE | 0% |

## Consensus design

Leader and validators run `gl.vm.run_nondet_default`. The validator re-runs the
judgement and compares **only the verdict enum**; the free-text rationale is
stored but never compared. Malformed or unknown model output falls back to
`NEEDS_EVIDENCE`, which pays nothing, so a bad answer can never release funds.

## Setup and tests

    python3.12 -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt
    pytest tests -v

Tests use the `gltest` Direct Mode fixtures (`direct_vm`, `direct_deploy`), so
no Docker, network or API key is needed. The LLM is mocked per test.
`pytest.ini` pins the contracts directory.

## Status and limitations

- Payouts are accounting only: the contract records `payout` but does not transfer funds. An escrow layer is future work.
- The response deadline is a documented TODO; adjudication is currently allowed from `SUBMITTED` or `RESPONDED`.
- Tests run in Direct Mode with a mocked LLM. The contract has not been exercised against a live validator network.
- The contract header uses `# { "Depends": "py-genlayer:latest" }` and the tests run on `genlayer-test` 0.30.0 (exact versions in `requirements.txt`).
