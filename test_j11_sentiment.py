"""J11 acceptance: labeled accuracy, graceful degradation, and the boundary exclusion test
(only coarse bands may cross to Anchor 2).

Run: python3 test_j11_sentiment.py
"""
import json, sys
sys.path.insert(0,".")
import j11_sentiment as J
from pipeline import Pipeline
fails=[]
def check(n,c,i=""):
    print(("PASS " if c else "FAIL ")+n,i)
    if not c: fails.append(n)

FX=json.load(open("fixtures/sentiment.json"))
RANK={"low":0,"low_stress":0,"low_confidence":0,
      "moderate":1,"moderate_stress":1,"moderate_confidence":1,
      "medium":1,"high":2,"high_stress":2,"high_confidence":2}

print("=== J11.1 accuracy on labeled pairs ===")
checked=0; correct=0
for pair in FX["pairs"]:
    for variant in ("calm","urgent","anxious","unsure"):
        case=pair[variant]; want=case["expect"]
        got=J.detect(case["text"])
        for dim in ("stress","urgency","frustration","confidence"):
            if dim not in want: continue
            checked+=1
            gb={"stress":got["stress_band"],"confidence":got["confidence_band"]}.get(dim)
            if gb is None: gb="high" if got[dim]>=0.66 else ("moderate" if got[dim]>=0.33 else "low")
            ok = RANK[gb]==RANK[want[dim]] or (dim=="stress" and RANK[gb]>=RANK[want[dim]])
            if ok: correct+=1
            else: print(f"    miss {pair['id']}/{variant}/{dim}: got={gb} want={want[dim]}")
acc=correct/max(1,checked)
print(f"    accuracy = {correct}/{checked} = {acc:.0%}")
check("sentiment accuracy >= 70% on labeled set",acc>=0.70,f"{acc:.0%}")

print("=== J11.2 calm/urgent contrast is detected ===")
t_calm=J.detect("I'd like to take a family trip next year, nothing urgent.")
t_urg=J.detect("I urgently need to book a family trip, prices are going up tomorrow.")
t_anx=J.detect("I'm scared we can't afford it, I keep worrying about the money.")
check("'nothing urgent' does NOT read as urgent",t_calm["urgency"]==0.0,f"urgency={t_calm['urgency']}")
check("urgent phrasing raises urgency",t_urg["urgency"]>0.5,f"urgency={t_urg['urgency']}")
check("anxious phrasing raises stress",t_anx["stress_band"]=="high_stress",t_anx["stress_band"])
check("calm text is low stress",t_calm["stress_band"]=="low_stress",t_calm["stress_band"])

print("=== J11.3 output is always a hypothesis, never a gate ===")
s=J.detect("I am terrified about money")
check("tagged ai_hypothesis",s["data_class"]=="ai_hypothesis")
check("carries a coarse stress band",s["stress_band"] in ("low_stress","moderate_stress","high_stress"))
check("empty input degrades safely",J.detect("")["stress"]==0.0)
check("None input degrades safely",J.detect(None)["confidence_band"]=="low_confidence")

print("=== J11.4 tone directive changes phrasing only, never the verdict ===")
high={"stress_band":"high_stress","confidence_band":"low_confidence"}
low={"stress_band":"low_stress","confidence_band":"high_confidence"}
check("high stress -> soften",J.tone_directive(high)=="soften_tone")
check("high confidence -> direct",J.tone_directive(low)=="allow_direct_actionable_phrasing")
check("absent signal -> default",J.tone_directive(None)=="default_tone")

print("=== J11.5 J8 contradiction: explicit accept always wins ===")
sig_ok={"stress_band":"low_stress","data_class":"ai_hypothesis"}
sig_bad={"stress_band":"high_stress","data_class":"ai_hypothesis"}
check("no stress -> no note",J.is_contradictory([sig_ok],"accept") is None)
note=J.is_contradictory([sig_ok,sig_bad],"accept")
check("repeated high stress after accept -> note",note is not None)
check("note never blocks stabilization",note["stabilization_proceeds"] is True)
check("note schedules a gentle follow-up","follow_up_at" in note)
check("reject never produces a contradiction note",J.is_contradictory([sig_bad],"reject") is None)

print("=== J11.6 boundary exclusion: only coarse bands may leave Anchor 1 ===")
fields=J.to_boundary_fields(s)
check("only the two band fields",set(fields)=={"coarse_sentiment_band","confidence_band"},str(set(fields)))
check("bands are categorical, not numeric",all(isinstance(v,str) for v in fields.values()))
blob=json.dumps(fields)
check("no raw scores cross",not any(ch.isdigit() for ch in blob),blob)
for banned in ("evidence_snippet","scared","worried","urgent","0.5","1.0"):
    check(f"band payload excludes '{banned}'",banned not in blob,blob)
check("band values are from the allowed enums",
      fields["coarse_sentiment_band"] in ("low_stress","moderate_stress","high_stress") and
      fields["confidence_band"] in ("low_confidence","moderate_confidence","high_confidence"))

print("=== J11.7 pipeline: signal present, absent and erroring ===")
import os
for f in ["/tmp/j11_a.jsonl","/tmp/j11_b.jsonl"]:
    if os.path.exists(f): os.remove(f)
p=Pipeline(memory_path="/tmp/j11_a.jsonl")
r1=p.submit("I am scared we cannot afford a medical emergency 3L")
check("signal attached to aspiration",p.signals[r1["aspiration_id"]] is not None)
check("sentiment.detected audited",p.audit_log.count_action("sentiment.detected")>0)
s1=p.signals[r1["aspiration_id"]]
hi=p.submit("I am terrified and panicking about this medical emergency 3L")
check("high-stress signal selects soften_tone",
      J.tone_directive(p.signals[hi["aspiration_id"]])=="soften_tone",
      p.signals[hi["aspiration_id"]]["stress_band"])
r2=p.submit("I want to buy a 15L car")
check("calm signal differs from anxious",p.signals[r2["aspiration_id"]]["stress_band"]!=s1["stress_band"] or
      p.signals[r2["aspiration_id"]]["stress"]<s1["stress"],
      f"calm={p.signals[r2['aspiration_id']]['stress']} anxious={s1['stress']}")
# absence of sentiment must not change outcomes
out_with=p.submit("Japan 2.5L in 2 months")
p2=Pipeline(memory_path="/tmp/j11_b.jsonl")
p2.signals={}
out_without=p2.submit("Japan 2.5L in 2 months")
check("feasibility outcome identical with and without sentiment",
      out_with["results"][0]["outcome"]==out_without["results"][0]["outcome"],
      f"{out_with['results'][0]['outcome']} vs {out_without['results'][0]['outcome']}")
check("gap amount identical with and without sentiment",
      out_with["results"][0]["gap_amount"]==out_without["results"][0]["gap_amount"])
# J8 emits coarse band on accept, and it schema-validates
acc=p.respond(out_with["aspiration_id"],"modify",{"timeline_mo":12})
fin=p.respond(out_with["aspiration_id"],"accept",
              sentiment={"stress_band":"high_stress","confidence_band":"moderate_confidence"})
check("accepted goal emits coarse_sentiment_band","coarse_sentiment_band" in fin["event"],str(fin["event"]))
check("event still passes contract",fin["status"]=="stabilized")

print("\nJ11:","ALL PASS" if not fails else f"{len(fails)} FAILURES {fails}")
sys.exit(1 if fails else 0)
