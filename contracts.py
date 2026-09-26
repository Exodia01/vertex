"""Runtime contract helpers: schema loading, boundary exclusion, event validation."""
import json, os, sys
sys.path.insert(0,os.path.join(os.path.dirname(os.path.abspath(__file__)),"tools"))
from schema_validator import validate

ROOT=os.path.dirname(os.path.abspath(__file__))
C=os.path.join(ROOT,"contracts","iaspire-contracts")
def _s(n):
    with open(os.path.join(C,n)) as f: return json.load(f)

SCHEMAS={
 "SJS_v1":_s("stabilized_journal_state.v1.schema.json"),
 "SJS_v1.1":_s("stabilized_journal_state.v1.1.schema.json"),
 "CSI":_s("customer_segment_insight.v1.schema.json"),
 "POLICY":_s("policy_proposal.v1.schema.json"),
 "DECISION":_s("validated_policy_decision.v1.schema.json"),
 "CONSENT":_s("identity_consent_envelope.v1.schema.json"),
 "AUDIT":_s("audit_event_envelope.v1.schema.json"),
}
REGISTRY=_s("registry.json")
PINNED=REGISTRY["pinned_version"]
SUPPORTED=REGISTRY["consumers"]["STABILIZED_JOURNAL_STATE"]["supported"]

# Anchor 1 §21 enumerates exactly what may cross the boundary. Events are therefore BUILT from
# this projection rather than scanned for banned content, so a field added anywhere inside
# Anchor 1 cannot leak by default - it has to be added here deliberately.
PERMITTED_EVENT_FIELDS={
 "v1":["customer_ref","objective_category","mechanism_category","feasibility_outcome",
       "coarse_target_band","coarse_timeline_band","confirmed_at","state_version"],
 "v1.1":["customer_ref","objective_category","mechanism_category","feasibility_outcome",
         "coarse_target_band","coarse_timeline_band","confirmed_at","state_version",
         "coarse_sentiment_band","confidence_band"],
}
# Belt-and-braces only. The projection above is the actual guarantee; this catches a caller
# that hand-rolls a payload instead of using project_event().
FORBIDDEN_IN_EVENT=["txn_","HDFC","ICICI","SBI","axis bank","kotak","Ramesh","Bhopal",
                    "raw_text","contradiction_note","evidence_snippet","stress_score",
                    "urgency_score","frustration_score","420000","1200000"]

def project_event(source, contract_version="v1.1"):
    """Construct a boundary payload by explicit allow-list. Anything not named here is dropped
    by construction, not by detection."""
    allowed=set(PERMITTED_EVENT_FIELDS.get(contract_version,
                                            PERMITTED_EVENT_FIELDS["v1.1"]))
    return {k:v for k,v in source.items() if k in allowed}

def assert_boundary_clean(payload):
    """Secondary assertion for hand-rolled payloads. Also rejects any field outside the
    projection, so an unexpected key fails loudly instead of passing unnoticed."""
    blob=json.dumps(payload,default=str)
    hits=[t for t in FORBIDDEN_IN_EVENT if t in blob]
    if hits: raise ValueError(f"boundary violation, forbidden content in event: {hits}")
    stray=[k for k in payload if k not in set(PERMITTED_EVENT_FIELDS["v1.1"])]
    if stray: raise ValueError(f"field(s) not permitted to cross the boundary: {stray}")
    return True

def validate_event(payload, contract="SJS"):
    key=contract if contract in SCHEMAS else f"SJS_{contract}"
    return validate(payload,SCHEMAS[key])
