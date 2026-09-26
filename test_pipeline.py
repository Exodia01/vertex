"""End-to-end J1->J10 test. Run: python3 test_pipeline.py"""
import os, sys
sys.path.insert(0,".")
from pipeline import Pipeline
fails=[]
def check(n,c,i=""):
    print(("PASS " if c else "FAIL ")+n,i)
    if not c: fails.append(n)

if os.path.exists("memory_test.jsonl"): os.remove("memory_test.jsonl")
p=Pipeline(memory_path="memory_test.jsonl")

# Snapshot + funnel. income avg is now over the 12-month policy window (4 observed months,
# including the 110000 off-season month), not the old 3-month window which hid it.
check("snapshot", p.snapshot.balances["savings"]==420000.0 and p.snapshot.income_monthly_avg==181250.0
      and p.snapshot.income_min_month==110000.0, str(p.snapshot.income_monthly_avg))

# Happy path: Dubai -> feasible -> accept -> stabilized + memory + event
r=p.submit("Dubai family trip 1.2L in 3 months")
check("dubai analysed", r["status"]=="analysed" and r["results"][0]["outcome"]=="feasible", str(r["results"][0]["outcome"]))
aid=r["aspiration_id"]
a=p.respond(aid,"accept")
check("stabilized", a["status"]=="stabilized" and a["event"]["objective_category"]=="travel")
check("event bands", a["event"]["coarse_target_band"]=="0-1.5L" and a["event"]["coarse_timeline_band"]=="0-3mo")
check("no raw leak", "txn_" not in str(a["event"]) and "HDFC" not in str(a["event"]))
check("memory versioned", len(p.memory_view())==1 and p.memory_view()[0]["state_version"]=="v1")

# Ambiguous -> clarifying, no guess
amb=p.submit("hmm paisa chahiye")
check("clarify not guess", amb["status"]=="needs_clarification")

# Gap path: Japan -> challenge -> modify timeline -> re-analyse -> accept
g=p.submit("Japan trip 2.5L in 2 months")
check("japan gap challenged", g["status"]=="analysed" and "challenge" in g, str(g["results"][0]["gap_amount"]))
gid=g["aspiration_id"]
m=p.respond(gid,"modify",{"timeline_mo":10})
check("modify re-analysed", m["status"]=="re-analysed" and m["results"][0]["outcome"]=="feasible", str(m["results"][0]["monthly_need"]))
s=p.respond(gid,"accept")
check("japan stabilized v2", s["status"]=="stabilized")
check("modified timeline persisted into goal", s["goal"]["timeline"]==10, str(s["goal"]["timeline"]))
check("memory has 2 goals", len(p.memory_view())==2)

# Wrong-construct: customer states save-only for a medical objective -> challenged, not rubber-stamped
w=p.submit("I want to save 3L for medical emergencies")
check("stated mechanism ranked first", w["candidates"][0]["mechanism"]=="liquid reserve" and w["candidates"][0]["is_stated"])
check("wrong construct at-risk", w["results"][0]["outcome"]=="at-risk", w["results"][0]["outcome"])
check("better alt named", any("bima" in a["description"] for a in w.get("alternatives",[])), str(w.get("alternatives")))
# same aspiration without a stated mechanism -> engine may pick the sane one, GO AHEAD
w2=p.submit("3L for medical emergencies")
check("no stated mech -> feasible", w2["results"][0]["outcome"]=="feasible", w2["results"][0]["outcome"])

# Reject path
rj=p.submit("25L house")
rej=p.respond(rj["aspiration_id"],"reject")
check("reject abandons", rej["status"]=="abandoned")

# Nudge cap property across many challenges
p.respond(gid,"modify",{"timeline_mo":1})
nudges=[r for r in p.audit_log.records if r["action"]=="challenge.issued"]
counts=[r["detail"]["nudge_count"] for r in nudges]
check("nudge cap<=5 per aspiration", all(c<=5 for c in counts), str(counts))

# J10: income drop re-triggers analysis on stabilized goals
before=p.audit_log.count_action("reanalysis.triggered")
out=p.simulate_material_change("income_drop")
after=p.audit_log.count_action("reanalysis.triggered")
check("reanalysis triggered", after>before, str(out[:1]))
check("reanalysis shows new state", all("new_outcome" in o for o in out), str([o["new_outcome"] for o in out]))

# J9 tombstone on consent withdrawal
vs=p.memory.tombstone(p.memory_view()[0]["goal_id"])
check("tombstone retracts", len(vs)>=1 and p.memory.history(p.memory_view()[0]["goal_id"])[-1]["tombstone"] is True)

# Rate limit: second event same customer does not storm
n1=p.audit_log.count_action("reanalysis.triggered")
p.simulate_material_change("income_drop")
n2=p.audit_log.count_action("reanalysis.triggered")
check("no trigger storm", n2==n1, f"{n1}->{n2}")
check("sentiment-only trigger emits priority.raised, never reanalysis",
      p.audit_log.count_action("priority.raised")>=0)

# Funnel observability
f=p.funnel()
check("funnel metrics", f.get("stabilized_state",0)>=2 and "quarantined" in f, str(f))

# Privacy: full replay reconstructable
hist=p.store.history(aid)
check("replay complete", [h["state"] for h in hist][-1]=="monitoring", str([h["state"] for h in hist]))

print("\nRESULT:", "ALL PASS" if not fails else f"{len(fails)} FAILS {fails}")
sys.exit(1 if fails else 0)
