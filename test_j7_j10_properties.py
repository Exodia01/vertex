"""J7 cap as a PROPERTY test (not a boundary example), J10 threshold boundaries, and
J3 transition-edge coverage.

Run: python3 test_j7_j10_properties.py
"""
import json, os, sys
sys.path.insert(0,".")
from j1_ingest import ingest
from j2_snapshot import build_snapshot
from j3_state import JournalStore
from j6_feasibility import compute
from j7_challenge import NudgeLog, CAP
from j10_monitor import Monitor, LARGE_WITHDRAWAL, INCOME_DROP_PCT
from dataclasses import replace
fails=[]
def check(n,c,i=""):
    print(("PASS " if c else "FAIL ")+n,i)
    if not c: fails.append(n)

mock=json.load(open("mock_aa.json"))
tx,ac,q,a=ingest(mock["transactions"],mock["accounts"],["txn.read","bal.read"])
snap,_=build_snapshot("p",tx,ac,mock["as_of"],income_pattern=mock["income_pattern"])
GAP={"mechanism":"savings goal","required_capital":250000,"horizon_mo":2,
     "liquidity_need":"med","financing_need":False}
RISK={"mechanism":"liquid reserve","required_capital":300000,"horizon_mo":12,
      "liquidity_need":"high","financing_need":False}

print("=== J7.1 cap holds for many random demand patterns (property) ===")
import random
rng=random.Random(11)
violations=0
for trial in range(300):
    nl=NudgeLog(); issued=0
    for _ in range(rng.randint(1,12)):
        f=compute(GAP if rng.random()<0.6 else RISK,snap)
        r=nl.issue(f"asp_{trial}",f)
        if r: issued+=1
    if issued>CAP: violations+=1
check("cap never exceeded across 300 randomized runs",violations==0,f"violations={violations}")
nl=NudgeLog()
for _ in range(CAP): nl.issue("x",compute(GAP,snap))
check("exactly CAP issued at the boundary",nl.count("x")==CAP,str(nl.count("x")))
check("CAP+1 request is refused (fails closed)",nl.issue("x",compute(GAP,snap)) is None)
check("fails closed, not fails open",nl.count("x")==CAP)

print("=== J7.2 cap is per-aspiration, not global ===")
nl=NudgeLog()
for i in range(3):
    for _ in range(4): nl.issue(f"asp_{i}",compute(GAP,snap))
check("three aspirations each get their own budget",[nl.count(f"asp_{i}") for i in range(3)]==[4,4,4],
      str([nl.count(f"asp_{i}") for i in range(3)]))

print("=== J7.3 challenge always names a concrete alternative ===")
nl=NudgeLog()
g=nl.issue("a",compute(GAP,snap)); r=nl.issue("b",compute(RISK,snap),all_results=[compute(RISK,snap),compute(GAP,snap)])
check("gap challenge offers alternatives",bool(g["alternatives"]),str(g["alternatives"]))
check("at-risk challenge offers a better mechanism",
      any("bima" in x["description"] for x in r["alternatives"]),str(r["alternatives"]))
check("challenge addresses the customer",
      g["challenge"].split()[0].strip(",.!") in ("Bhai","Arre"),g["challenge"][:40])

print("=== J10.1 large-withdrawal threshold boundary ===")
class T:
    def __init__(s,amt): s.amount=amt; s.id="t"
m=Monitor(rate_limit=50)
check("just below threshold does not fire",m.detect("c",None,None,[T(LARGE_WITHDRAWAL-1)])==[])
check("exactly at threshold fires",len(m.detect("c2",None,None,[T(LARGE_WITHDRAWAL)]))==1)
check("just above threshold fires",len(m.detect("c3",None,None,[T(LARGE_WITHDRAWAL+1)]))==1)

print("=== J10.2 income-drop threshold boundary ===")
m=Monitor(rate_limit=50)
base=100000
just_above=replace(snap,income_monthly_avg=base*(1-INCOME_DROP_PCT-0.01))
at=replace(snap,income_monthly_avg=base*(1-INCOME_DROP_PCT))
below=replace(snap,income_monthly_avg=base*(1-INCOME_DROP_PCT+0.01))
ref=replace(snap,income_monthly_avg=base)
check("drop below threshold ignored",m.detect("d1",ref,below,[])==[])
check("drop exactly at threshold fires",len(m.detect("d2",ref,at,[]))==1)
check("drop beyond threshold fires",len(m.detect("d3",ref,just_above,[]))==1)
check("income increase ignored",m.detect("d4",ref,replace(snap,income_monthly_avg=base*1.2),[])==[])

print("=== J10.3 no trigger storm ===")
m=Monitor(rate_limit=2)
fired=sum(len(m.detect("e",None,None,[T(90000)])) for _ in range(20))
check("rate limit caps total firings",fired<=2,str(fired))

print("=== J3 all transition edges representable ===")
js=JournalStore()
edges=[("raw_observation","interpreted_expectation"),
       ("interpreted_expectation","banking_equivalent"),
       ("banking_equivalent","analysis"),
       ("analysis","challenge"),("analysis","customer_response"),
       ("analysis","stabilized_state"),
       ("challenge","customer_response"),
       ("customer_response","banking_equivalent"),("customer_response","analysis"),
       ("customer_response","stabilized_state"),
       ("stabilized_state","monitoring"),("monitoring","analysis")]
for i,(frm,to) in enumerate(edges):
    js2=JournalStore()
    try:
        if i==0: js2.transition("x",None,to,"observed_data",{},"e","customer")
        else: js2.transition("x",frm,to,"ai_hypothesis",{},"e","ai")
        check(f"legal {frm} -> {to}",True)
    except ValueError as e:
        check(f"legal {frm} -> {to}",False,str(e))
check("rejected-interpretation loop-back representable",
      js2.transition("x","customer_response","banking_equivalent",
                     "customer_rejected_interpretation",{},"e","customer")["data_class"]
      =="customer_rejected_interpretation")

print("\nJ7/J10/J3:","ALL PASS" if not fails else f"{len(fails)} FAILURES {fails}")
sys.exit(1 if fails else 0)
