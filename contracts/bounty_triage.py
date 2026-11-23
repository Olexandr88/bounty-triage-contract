# { "Depends": "py-genlayer:1zr6nqk597d97kg0dyxg0shhrykx5v02zjgnyrajapy4wlqvfvwh" }
import genlayer as gl
from dataclasses import dataclass
import json

# Payout in basis points, derived only from the verdict (no tolerance window).
VERDICT_BPS = {
    "CONFIRMED_CRITICAL": 10000,
    "CONFIRMED_HIGH": 5000,
    "CONFIRMED_LOW": 1000,
    "FALSE_POSITIVE": 0,
    "NEEDS_EVIDENCE": 0,
}

SUBMITTED = "SUBMITTED"
RESPONDED = "RESPONDED"
ADJUDICATED = "ADJUDICATED"
FINALIZED = "FINALIZED"

RUBRIC = """You are a bug-bounty triage judge. Decide ONE verdict:
CONFIRMED_CRITICAL: concrete exploit path, loss of funds or full takeover, reproducible.
CONFIRMED_HIGH: concrete exploit path, significant impact, preconditions realistic.
CONFIRMED_LOW: real defect, limited impact or hard preconditions.
FALSE_POSITIVE: claim contradicted by code/evidence or maintainer response.
NEEDS_EVIDENCE: no reproduction or the evidence cannot be verified.
Rules: unverified claims are never CONFIRMED. Prefer NEEDS_EVIDENCE over guessing.
Reply with JSON only: {"verdict": "<ONE OF THE FIVE>", "rationale": "<max 300 chars>"}"""


@gl.allow
@dataclass
class Report:
    reporter: gl.Address
    maintainer: gl.Address
    project: str
    evidence_url: str
    summary: str
    bounty: gl.u256
    status: str
    response: str
    verdict: str
    rationale: str
    payout: gl.u256
    appealed: bool


class BountyTriage(gl.contract.Contract):
    next_id: gl.u256
    reports: gl.TreeMap[gl.u256, Report]

    def __init__(self):
        self.next_id = 0

    @gl.public.write
    def submit_report(
        self, maintainer: gl.Address, project: str, evidence_url: str,
        summary: str, bounty: int,
    ) -> int:
        # Monotonic counter id: no string-concatenated keys, no collisions.
        rid = self.next_id
        self.next_id = rid + 1
        self.reports[rid] = Report(
            reporter=gl.message.sender_address,
            maintainer=maintainer,
            project=project,
            evidence_url=evidence_url,
            summary=summary,
            bounty=bounty,
            status=SUBMITTED,
            response="",
            verdict="",
            rationale="",
            payout=0,
            appealed=False,
        )
        return rid

    @gl.public.write
    def respond(self, report_id: int, response: str) -> None:
        r = self._get(report_id)
        assert gl.message.sender_address == r.maintainer, "only maintainer"
        assert r.status == SUBMITTED, "bad state"
        r.response = response
        r.status = RESPONDED

    @gl.public.write
    def adjudicate(self, report_id: int) -> None:
        r = self._get(report_id)
        assert r.status in (SUBMITTED, RESPONDED), "bad state"
        # TODO: enforce a response deadline before SUBMITTED -> adjudicate
        self._run_judgement(r, "")
        r.status = ADJUDICATED

    @gl.public.write
    def appeal(self, report_id: int, reason: str) -> None:
        r = self._get(report_id)
        sender = gl.message.sender_address
        assert sender == r.reporter or sender == r.maintainer, "not a party"
        assert r.status == ADJUDICATED and not r.appealed, "bad state"
        r.appealed = True
        self._run_judgement(r, reason)
        r.status = FINALIZED  # one appeal only, result is final

    @gl.public.write
    def finalize(self, report_id: int) -> None:
        r = self._get(report_id)
        sender = gl.message.sender_address
        assert sender == r.reporter or sender == r.maintainer, "not a party"
        assert r.status == ADJUDICATED, "bad state"
        r.status = FINALIZED

    @gl.public.view
    def get_report(self, report_id: int) -> dict:
        r = self._get(report_id)
        return {
            "project": r.project,
            "status": r.status,
            "verdict": r.verdict,
            "rationale": r.rationale,
            "payout": r.payout,
            "appealed": r.appealed,
        }

    def _get(self, report_id: int) -> Report:
        assert report_id in self.reports, "unknown report"
        return self.reports[report_id]

    def _run_judgement(self, r: Report, appeal_reason: str) -> None:
        # Copy storage into locals: storage is not readable inside nondet blocks.
        url, summary, response = r.evidence_url, r.summary, r.response
        bounty = r.bounty

        def leader_fn() -> dict:
            try:
                evidence = gl.nondet.web.render(url, mode="text")[:6000]
            except Exception:
                evidence = "(evidence URL could not be fetched)"
            prompt = (
                f"{RUBRIC}\n\nREPORT:\n{summary}\n\nEVIDENCE:\n{evidence}\n\n"
                f"MAINTAINER RESPONSE:\n{response or '(none)'}\n\n"
                f"APPEAL REASON:\n{appeal_reason or '(none)'}\n"
            )
            raw = gl.nondet.exec_prompt(prompt)
            return _parse(raw)

        def validator_fn(leader_result) -> bool:
            if not isinstance(leader_result, gl.vm.Return):
                return False
            mine = leader_fn()
            # Compare ONLY the enum verdict. Rationale is never compared.
            return mine["verdict"] == leader_result.calldata["verdict"]

        result = gl.vm.run_nondet_default(leader_fn, validator_fn)
        r.verdict = result["verdict"]
        r.rationale = result["rationale"]
        r.payout = bounty * VERDICT_BPS[r.verdict] // 10000
        # TODO: real fund transfer; accounting-only until escrow is added.


def _parse(raw: str) -> dict:
    text = raw.strip().replace("```json", "").replace("```", "").strip()
    try:
        data = json.loads(text)
        verdict = str(data.get("verdict", ""))
        rationale = str(data.get("rationale", ""))[:300]
    except Exception:
        verdict, rationale = "NEEDS_EVIDENCE", "unparseable model output"
    if verdict not in VERDICT_BPS:
        verdict = "NEEDS_EVIDENCE"
    return {"verdict": verdict, "rationale": rationale}
