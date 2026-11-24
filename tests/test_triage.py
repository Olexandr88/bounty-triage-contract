"""Direct-mode tests for the bug-bounty triage contract.

No network or Docker needed: the LLM is mocked via direct_vm.mock_llm.
Each test uses a unique marker in the report text so the mock matches only
that test's prompt.
"""
import json

CONTRACT = "contracts/bounty_triage.py"
EVIDENCE = "https://example.com/evidence"


def verdict_json(verdict, rationale="mocked rationale"):
    return "```json\n" + json.dumps({"verdict": verdict, "rationale": rationale}) + "\n```"


def deploy(direct_deploy):
    return direct_deploy(CONTRACT)


def submit(contract, vm, reporter, maintainer, marker, bounty=1000):
    vm.sender = reporter
    return contract.submit_report(
        maintainer, "demo-project", EVIDENCE, f"report {marker}", bounty
    )


def test_confirmed_critical_pays_full_bounty(
    direct_vm, direct_deploy, direct_alice, direct_bob
):
    c = deploy(direct_deploy)
    rid = submit(c, direct_vm, direct_alice, direct_bob, "case-critical")
    direct_vm.mock_llm("case-critical", verdict_json("CONFIRMED_CRITICAL"))

    with direct_vm.prank(direct_bob):
        c.respond(rid, "Acknowledged, looking into it")
    c.adjudicate(rid)

    r = c.get_report(rid)
    assert r["status"] == "ADJUDICATED"
    assert r["verdict"] == "CONFIRMED_CRITICAL"
    assert r["payout"] == 1000


def test_false_positive_pays_nothing(
    direct_vm, direct_deploy, direct_alice, direct_bob
):
    c = deploy(direct_deploy)
    rid = submit(c, direct_vm, direct_alice, direct_bob, "case-falsepos")
    direct_vm.mock_llm("case-falsepos", verdict_json("FALSE_POSITIVE"))

    c.adjudicate(rid)

    r = c.get_report(rid)
    assert r["verdict"] == "FALSE_POSITIVE"
    assert r["payout"] == 0


def test_appeal_can_change_verdict_and_is_final(
    direct_vm, direct_deploy, direct_alice, direct_bob
):
    c = deploy(direct_deploy)
    rid = submit(c, direct_vm, direct_alice, direct_bob, "case-appeal")

    direct_vm.mock_llm("case-appeal", verdict_json("NEEDS_EVIDENCE"))
    c.adjudicate(rid)
    assert c.get_report(rid)["verdict"] == "NEEDS_EVIDENCE"
    assert c.get_report(rid)["payout"] == 0

    direct_vm.clear_mocks()
    direct_vm.mock_llm("case-appeal", verdict_json("CONFIRMED_LOW"))
    direct_vm.sender = direct_alice
    c.appeal(rid, "Added a full reproduction")

    r = c.get_report(rid)
    assert r["status"] == "FINALIZED"
    assert r["appealed"] is True
    assert r["verdict"] == "CONFIRMED_LOW"
    assert r["payout"] == 100  # 10% of 1000

    with direct_vm.expect_revert("bad state"):
        c.appeal(rid, "Second appeal must be rejected")


def test_garbage_model_output_falls_back_to_needs_evidence(
    direct_vm, direct_deploy, direct_alice, direct_bob
):
    c = deploy(direct_deploy)
    rid = submit(c, direct_vm, direct_alice, direct_bob, "case-garbage")
    direct_vm.mock_llm("case-garbage", "this is not json at all")

    c.adjudicate(rid)

    r = c.get_report(rid)
    assert r["verdict"] == "NEEDS_EVIDENCE"
    assert r["payout"] == 0


def test_unknown_verdict_is_never_paid(
    direct_vm, direct_deploy, direct_alice, direct_bob
):
    c = deploy(direct_deploy)
    rid = submit(c, direct_vm, direct_alice, direct_bob, "case-unknown")
    direct_vm.mock_llm("case-unknown", verdict_json("PAY_EVERYTHING"))

    c.adjudicate(rid)

    r = c.get_report(rid)
    assert r["verdict"] == "NEEDS_EVIDENCE"
    assert r["payout"] == 0


def test_only_maintainer_can_respond(
    direct_vm, direct_deploy, direct_alice, direct_bob
):
    c = deploy(direct_deploy)
    rid = submit(c, direct_vm, direct_alice, direct_bob, "case-auth")
    with direct_vm.expect_revert("only maintainer"):
        c.respond(rid, "I am the reporter, not the maintainer")


def test_stranger_cannot_appeal(
    direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie
):
    c = deploy(direct_deploy)
    rid = submit(c, direct_vm, direct_alice, direct_bob, "case-stranger")
    direct_vm.mock_llm("case-stranger", verdict_json("CONFIRMED_HIGH"))
    c.adjudicate(rid)

    direct_vm.sender = direct_charlie
    with direct_vm.expect_revert("not a party"):
        c.appeal(rid, "I have nothing to do with this report")


def test_report_ids_are_unique_and_sequential(
    direct_vm, direct_deploy, direct_alice, direct_bob
):
    c = deploy(direct_deploy)
    first = submit(c, direct_vm, direct_alice, direct_bob, "case-id-a")
    second = submit(c, direct_vm, direct_alice, direct_bob, "case-id-b")
    assert (first, second) == (0, 1)
