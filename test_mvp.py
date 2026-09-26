"""MVP tests J1-J8: unit + integration + privacy + demo. Run: python3 test_mvp.py"""
import json, sys
sys.path.insert(0,".")
from j1_ingest import ingest
from j2_snapshot import build_snapshot
from j3_state import JournalStore
from j4_intent import extract_intent
from j5_mechanism import candidates
from j6_feasibility import compute
from j7_challenge import NudgeLog, CAP
from j8_stabilize import stabilize

mock=json.load(open("mock_aa.json")); bench=json.load(open("benchmarks.json"))
fails=[]
def check(name,cond,info=""):
    print(("PASS " if cond else "FAIL ")+name,info)
    if not cond: fails.append(name)

# J1: bad record quarantined, zero silent drop, consent tag
tx,ac,q,a=ingest(mock["transactions"]+[{"id":"bad"}], mock["accounts"], ["txn.read","bal.read"])
check("J1 quarantine", q.count()==1 and len(tx)==len(mock["transactions"]))
check("J1 reason code", "missing" in q.reason_codes(), str(q.reason_codes()))
try:
    q.read("intruder"); check("J1 quarantine access-controlled",False)
except PermissionError: check("J1 quarantine access-controlled",True)
q.grant("data_quality_officer")
check("J1 granted principal can read",len(q.read("data_quality_officer"))==1)
check("J1 consent tag", all("txn.read" in t.consent_scope for t in tx))

# J2: snapshot reconciles
snap,ev=build_snapshot("ramesh44",tx,ac,"2026-09-26")
check("J2 reconcile", ev["reconciled"] and snap.balances["savings"]==420000.0)
check("J2 no acct numbers", "HDFC" not in str(snap.balances))

# J3: legal + illegal transitions, data-class enforced
js=JournalStore()
js.transition("a1",None,"raw_observation","observed_data",{},"mock","customer")
js.transition("a1","raw_observation","interpreted_expectation","ai_hypothesis",{},"j4","ai")
try: js.transition("a1","raw_observation","stabilized_state","ai_hypothesis",{},"x","ai"); check("J3 illegal blocked",False)
except ValueError: check("J3 illegal blocked",True)
try: js.transition("a1","interpreted_expectation","banking_equivalent","bogus",{},"x","ai"); check("J3 dataclass enforced",False)
except ValueError: check("J3 dataclass enforced",True)

# J4: 6 fixtures + ambiguous clarifies
fix={"Japan next year":"travel","15L car":"asset","3L medical":"protection","25L house":"asset","parents protected":"protection","save 2L":"liquidity"}
for t,exp in fix.items():
    check(f"J4 {t}", extract_intent(t)["objective_category"]==exp)
check("J4 clarify", "clarify" in extract_intent("hmm money"))

# J5: protection gives insurance+reserve candidate
c=candidates(extract_intent("parents medical protection 3L"))
check("J5 multi-mech", any("insurance" in m["mechanism"] for m in c))

# J6: exact reproducibility + Dubai realistic / Japan gap / health at-risk
d_dubai={"mechanism":"savings goal","required_capital":120000,"horizon_mo":3,"liquidity_need":"med","financing_need":False}
f1=compute(d_dubai,snap,bench); f2=compute(d_dubai,snap,bench)
check("J6 reproducible", f1==f2 and f1["computed_by"]=="deterministic_engine", str(f1["monthly_need"]))
check("J6 Dubai feasible", f1["outcome"]=="feasible", str(f1))
fj=compute({"mechanism":"savings goal","required_capital":250000,"horizon_mo":2,"liquidity_need":"med","financing_need":False},snap,bench)
check("J6 Japan gap", fj["outcome"]=="gap" and fj["gap_amount"]>0, str(fj["gap_amount"]))
fh=compute({"mechanism":"liquid reserve","required_capital":300000,"horizon_mo":12,"liquidity_need":"high","financing_need":False},snap,bench)
check("J6 health at-risk", fh["outcome"]=="at-risk")

# J7: cap enforced (5th ok, 6th None)
nl=NudgeLog()
outs=[nl.issue("a1",fj) for _ in range(6)]
check("J7 cap", outs[4] is not None and outs[5] is None and outs[0]["nudge_count"]==1)

# J8: accept emits valid event, no raw leak; modify loops back
e=stabilize("a1","cust_opaque_001",extract_intent("Dubai 1.2L"),d_dubai,f1,"accept")
check("J8 event contract", e["stabilized"] and e["payload"]["coarse_target_band"]=="0-1.5L" and "txn_" not in str(e))
check("J8 modify loopback", stabilize("a1","c",extract_intent("Dubai"),d_dubai,f1,"modify")["next"]=="j5/j6")

# Full J1->J8 demo: Japan insufficient -> challenge -> modify -> stabilize
i=extract_intent("Japan ₹2.5L in 2 months"); ms=candidates(i); f=compute(ms[0],snap,bench)
check("demo Japan challenged", f["outcome"]=="gap")
print("\nRESULT:", "ALL PASS" if not fails else f"{len(fails)} FAILS {fails}")
sys.exit(1 if fails else 0)
