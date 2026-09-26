"""J8 customer confirmation / stabilization.
Emits a contract-valid STABILIZED_JOURNAL_STATE. state_version is threaded in from
financial memory (J9) so the emitted version can never disagree with the stored one.
Sentiment is coarse-band only and never blocks stabilization (Anchor 1 §9 step 11, §21 v1.1)."""
import re
from contracts import (assert_boundary_clean, validate_event, project_event, PINNED, SUPPORTED)

MECH_CATEGORY={
 "savings goal":"savings_goal","insurance+reserve":"insurance_reserve",
 "liquid reserve":"liquid_reserve","investment allocation":"investment_allocation",
 "auto loan":"auto_loan","cash purchase":"cash_purchase","EMI":"emi",
 "downpayment+mortgage":"downpayment_mortgage","refinance/repay":"refinance_repay",
}
ALLOWED_OUTCOME={"feasible","gap","at-risk"}
SENTIMENT_BANDS={"low_stress","moderate_stress","high_stress"}
CONFIDENCE_BANDS={"low_confidence","moderate_confidence","high_confidence"}

def band_target(cap):
    if cap<=150000: return "0-1.5L"
    if cap<=500000: return "1.5-5L"
    return ">5L"
def band_timeline(n):
    if n<=3: return "0-3mo"
    if n<=12: return "3-12mo"
    return ">12mo"

def stabilize(aspiration_id, customer_ref, intent, candidate, feas, response,
              version="v1", sentiment_band=None, confidence_band=None,
              contradiction_note=None, follow_up_at=None, contract_version=None):
    """response: accept|reject|modify. modify must loop back to J5/J6 (caller re-runs them).

    Two independent version axes, deliberately not conflated:
      version          - state_version: the record revision of this goal (v1, v2, v3...).
                         Threaded from J9 so the event can never disagree with memory.
      contract_version - the schema shape (v1 / v1.1), pinned by the shared registry and
                         validated against what consumers currently support.
    """
    assert response in ("accept","reject","modify"), "bad response"
    if response!="accept":
        return {"stabilized":False,"next":"j5/j6" if response=="modify" else "abandoned"}
    assert feas["outcome"] in ALLOWED_OUTCOME
    assert re.fullmatch(r"v[0-9]+(\.[0-9]+)?", str(version)), f"bad state_version {version!r}"
    cv=contract_version or PINNED
    assert cv in SUPPORTED, f"unsupported contract version {cv}"
    if sentiment_band is not None: assert sentiment_band in SENTIMENT_BANDS
    if confidence_band is not None: assert confidence_band in CONFIDENCE_BANDS

    ev={"customer_ref":customer_ref,
        "objective_category":intent["objective_category"],
        "mechanism_category":MECH_CATEGORY[candidate["mechanism"]],
        # internal-only fields below; stripped by project_event before emission
        "internal_evidence_ref":f"asp:{aspiration_id}",
        "internal_monthly_need":feas.get("monthly_need"),
        "internal_risk_notes":feas.get("risk_notes"),
        "feasibility_outcome":feas["outcome"],
        "coarse_target_band":band_target(candidate["required_capital"]),
        "coarse_timeline_band":band_timeline(candidate["horizon_mo"]),
        "confirmed_at":"2026-09-26T10:00:00Z",
        "state_version":version}
    if cv=="v1.1":
        if sentiment_band: ev["coarse_sentiment_band"]=sentiment_band
        if confidence_band: ev["confidence_band"]=confidence_band
    # Project to the permitted fields FIRST, then validate. Internal-only fields are dropped
    # by construction and can never reach the contract check or the wire.
    ev=project_event(ev,cv)
    errs=validate_event(ev,f"SJS_{cv}")
    if errs: raise ValueError(f"emitted event fails contract: {errs[:2]}")
    assert_boundary_clean(ev)
    out={"stabilized":True,"event":"STABILIZED_JOURNAL_STATE","payload":ev}
    # contradiction_note is internal-only: recorded on the journal entry, never in the event
    if contradiction_note:
        out["internal"]={"contradiction_note":contradiction_note}
        if follow_up_at: out["internal"]["follow_up_at"]=follow_up_at
    return out
