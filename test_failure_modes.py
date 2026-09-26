"""Anchor 1 §15 failure-mode and security tests that need deliberate fault injection.

Run: python3 test_failure_modes.py
"""
import json, os, sys
sys.path.insert(0,".")
import pipeline as PL
from pipeline import Pipeline
from j6_feasibility import compute
from j9_memory import MemoryStore, MemoryAccessError, CRYPTO_NOTE
fails=[]
def check(n,c,i=""):
    print(("PASS " if c else "FAIL ")+n,i)
    if not c: fails.append(n)

def fresh(name):
    p=f"/tmp/{name}.jsonl"
    if os.path.exists(p): os.remove(p)
    return p

print("=== S15: feasibility engine unavailable -> analysis_pending, never a guess ===")
orig=PL.compute
def boom(*a,**k): raise RuntimeError("feasibility engine offline")
PL.compute=boom
try:
    p=Pipeline(memory_path=fresh("fm1"))
    r=p.submit("Japan trip 2.5L in 2 months")
    check("engine failure does not crash the request",r["status"]=="analysis_pending",r["status"])
    check("no verdict fabricated",r["results"]==[],str(r["results"]))
    check("customer is informed, not left guessing",bool(r.get("note")))
    check("no challenge issued while deferred","challenge" not in r)
    check("deferral is audited",p.audit_log.count_action("feasibility.deferred")==1)
    PL.compute=orig
    p2=Pipeline(memory_path=fresh("fm2"))
    r2=p2.submit("Japan trip 2.5L in 2 months")
    check("recovers once the engine returns",r2["status"]=="analysed" and r2["results"][0]["outcome"]=="gap")
finally:
    PL.compute=orig

print("=== S15: nudge governor fails closed ===")
from j7_challenge import NudgeLog, CAP
nl=NudgeLog()
for _ in range(CAP): nl.issue("x",{"outcome":"gap","monthly_need":1,"avail_monthly":0,
                                     "avail_stress_monthly":0,"gap_amount":1,"stress_applied":False})
check("over cap returns None rather than spamming",nl.issue("x",{"outcome":"gap","monthly_need":1,
      "avail_monthly":0,"avail_stress_monthly":0,"gap_amount":1,"stress_applied":False}) is None)

print("=== S15: consent withdrawal retracts downstream-eligible records ===")
p=Pipeline(memory_path=fresh("fm3"))
a=p.submit("Dubai 1.2L in 3 months"); r=p.respond(a["aspiration_id"],"accept")
gid=r["goal"]["goal_id"]
check("goal live before withdrawal",len(p.memory.revisions(gid))==1)
retracted=p.memory.tombstone(gid)
check("prior version retracted",retracted==["v1"],str(retracted))
check("no live revisions after tombstone",len(p.memory.revisions(gid))==0)
check("history is append-only, not rewritten",len(p.memory.history(gid))==2)
check("tombstone does not delete the audit trail",p.audit_log.count_action("goal.stabilized")==1)

print("=== S9: memory access restricted to the owning customer ===")
if os.path.exists("/tmp/fm4.jsonl"): os.remove("/tmp/fm4.jsonl")
m=MemoryStore("/tmp/fm4.jsonl")
m.add("g1","cust_opaque_aaa","travel","savings goal",100000,3)
check("owner can read",len(m.query("cust_opaque_aaa",requester="cust_opaque_aaa"))==1)
for bad in ["cust_opaque_bbb","somebody",""]:
    try:
        m.query("cust_opaque_aaa",requester=bad)
        check(f"non-owner {bad!r} refused",False)
    except MemoryAccessError:
        check(f"non-owner {bad!r} refused",True)
check("auditor role permitted",len(m.query("cust_opaque_aaa",requester="human_auditor"))==1)

print("=== S13: at-rest confidentiality and tenant isolation ===")
if os.path.exists("/tmp/fm5.jsonl"): os.remove("/tmp/fm5.jsonl")
s=MemoryStore("/tmp/fm5.jsonl",master_secret="master",tenant="cust_opaque_aaa")
s.add("g1","cust_opaque_aaa","protection","insurance+reserve",300000,12)
blob=open("/tmp/fm5.jsonl").read()
check("no plaintext objective on disk","protection" not in blob)
check("no plaintext amount on disk","300000" not in blob)
check("round-trips with the right key",s.revisions("g1")[0]["objective"]=="protection")
other=MemoryStore("/tmp/fm5.jsonl",master_secret="master",tenant="cust_opaque_bbb")
try:
    other.revisions("g1"); check("other tenant cannot read",False)
except ValueError: check("other tenant cannot read",True)
tampered=blob.replace("v1.","v1.A",1)
open("/tmp/fm5.jsonl","w").write(tampered+"\n")
try:
    MemoryStore("/tmp/fm5.jsonl",master_secret="master",tenant="cust_opaque_aaa").revisions("g1")
    check("tampering detected",False)
except ValueError: check("tampering detected",True)
check("crypto limitation is documented, not hidden",
      "DOES_NOT_PROVIDE" in json.dumps(CRYPTO_NOTE).upper() and "AEAD" in CRYPTO_NOTE["production_path"])

print("=== S13: every read of financial data is audited ===")
p=Pipeline(memory_path=fresh("fm6"))
p.submit("Dubai 1.2L in 3 months")
before=p.audit_log.count_action("financial_data.read")
p.memory_view(); p.memory_view()
check("two reads produced two audit events",
      p.audit_log.count_action("financial_data.read")==before+2,
      str(p.audit_log.count_action("financial_data.read")))
ev=p.audit_log.read_events()[0]
check("read event names the fields touched",bool(ev["detail"]["fields"]),str(ev["detail"]))
check("read event names the purpose",ev["detail"]["purpose"]=="journal_analysis")

print("=== S16: single audit store, no competing log ===")
p=Pipeline(memory_path=fresh("fm7"))
a=p.submit("Dubai 1.2L in 3 months"); p.respond(a["aspiration_id"],"accept")
check("pipeline exposes no parallel flat audit list",not hasattr(p,"audit"))
check("all history queryable from the one store",p.audit_log.count_action("intent.extracted")==1)
check("store is queryable by trace",len(p.audit_log.by_trace(
      p.audit_log.records[0]["trace_id"]))>=1)

print("=== S15: sentiment failure degrades, never blocks ===")
import j11_sentiment as J
orig_detect=J.detect
def dead(*a,**k): raise RuntimeError("sentiment model offline")
p=Pipeline(memory_path=fresh("fm8"))
J.detect=dead
PL.detect_sentiment=dead
try:
    r=p.submit("Japan trip 2.5L in 2 months")
    check("pipeline still analyses with sentiment dead",r["status"]=="analysed",r["status"])
    check("outcome unaffected by sentiment failure",r["results"][0]["outcome"]=="gap")
finally:
    PL.detect_sentiment=orig_detect
    J.detect=orig_detect


print("=== S15/S11: LLM seam degrades to deterministic, never to a guess ===")
import j4_llm as L
from j4_intent import extract_intent as det_intent
check("LLM layer is off by default",L.ENABLED is False)
check("no client without a key",L._client() is None)
check("ask returns None with no client",L._ask("x") is None)
# a model that returns numbers must have them discarded
class Sneaky:
    def extract_intent(self,text):
        d={"objective_category":"travel","confidence":0.9,
           "amount":9999999,"monthly_need":1,"gap_amount":0,"target":5000000}
        return L._strip_numbers(d)
s=Sneaky().extract_intent("Dubai 1.2L")
check("numeric fields from a model are stripped",not (set(s) & L.NUMERIC_KEYS),str(s))
check("categorical fields survive",s["objective_category"]=="travel")
# malformed / hostile responses fall back
check("malformed json -> None",L._parse("not json at all") is None)
check("prose around json is tolerated",L._parse('here you go: {"objective_category":"travel"}')["objective_category"]=="travel")
li=L.LLMIntent(det_intent)
base=li.extract_intent("Dubai family trip 1.2L in 3 months")
check("with no model, deterministic answer is returned unchanged",
      base["objective_category"]=="travel" and base["amount"]==120000,str(base))
# an out-of-vocabulary category must not override a good deterministic answer
import unittest.mock as mock
with mock.patch.object(L,"_ask",return_value='{"objective_category":"crypto","confidence":0.9}'):
    r=li.extract_intent("Dubai family trip 1.2L in 3 months")
check("out-of-vocabulary model output is rejected",r["objective_category"]=="travel",r["objective_category"])
with mock.patch.object(L,"_ask",return_value='{"objective_category":"unknown","confidence":0.9}'):
    r=li.extract_intent("Dubai family trip 1.2L in 3 months")
check("model cannot downgrade a clear answer to unknown",r["objective_category"]=="travel")
with mock.patch.object(L,"_ask",side_effect=RuntimeError("model down")):
    r=li.extract_intent("Japan 2.5L in 2 months")
check("model exception falls back to deterministic",r["objective_category"]=="travel")
ls=L.LLMSentiment(__import__("j11_sentiment").detect)
with mock.patch.object(L,"_ask",side_effect=RuntimeError("down")):
    s=ls.detect("I am terrified about money")
check("sentiment model failure degrades to baseline",s["stress_band"] in ("low_stress","moderate_stress","high_stress"))
check("pipeline defaults to the deterministic path",
      "engine" not in det_intent("Dubai 1.2L in 3 months"))

print("\nFAILURE MODES / SECURITY:","ALL PASS" if not fails else f"{len(fails)} FAILURES {fails}")
sys.exit(1 if fails else 0)
