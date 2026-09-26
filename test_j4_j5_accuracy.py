"""J4/J5 acceptance: accuracy on the labeled fixture set, contradictory -> clarifying
question, stated-mechanism ranking, and J5's rubric validation.

Run: python3 test_j4_j5_accuracy.py
"""
import json, sys
sys.path.insert(0,".")
from j4_intent import extract_intent
from j5_mechanism import candidates
fails=[]
def check(n,c,i=""):
    print(("PASS " if c else "FAIL ")+n,i)
    if not c: fails.append(n)

ASP=json.load(open("fixtures/aspirations.json"))
cases=ASP["cases"]
clear=[c for c in cases if c["bucket"]=="clear"]
ambig=[c for c in cases if c["bucket"]=="ambiguous"]
contra=[c for c in cases if c["bucket"]=="contradictory"]

print("=== J4.1 accuracy on labeled clear fixtures ===")
correct=0
for c in clear:
    r=extract_intent(c["text"])
    ok = r["objective_category"]==c["label"]
    if ok: correct+=1
    else: print(f"    miss {c['id']}: {c['text']!r} -> {r['objective_category']} (want {c['label']})")
acc=correct/len(clear)
print(f"    accuracy = {correct}/{len(clear)} = {acc:.0%}")
check("accuracy >= 90% on labeled clear set",acc>=0.90,f"{acc:.0%}")
check("accuracy floor declared in fixture",len(clear)>0)

print("=== J4.1b small talk is conversation, not a failed query ===")
from j4_intent import is_small_talk
for s in ["hi","hello","hi kaise ho","how are you","thanks","sab badhiya","kaise ho","bye"]:
    check(f"small talk: {s!r}",is_small_talk(s))
for s in ["Japan trip 2.5L in 2 months","I want to save 3L for medical emergencies",
          "15L car next year","save 2L","car"]:
    check(f"NOT small talk: {s[:34]!r}",not is_small_talk(s))

print("=== J4.2 ambiguous -> clarifying question, never a guess ===")
for c in ambig:
    r=extract_intent(c["text"])
    check(f"ambiguous {c['id']} asks",  "clarify" in r, f"-> {r['objective_category']}")
    check(f"ambiguous {c['id']} not classified",r["objective_category"] in ("unknown","contradictory"))

print("=== J4.3 contradictory -> clarifying question (never silently picks) ===")
for c in contra:
    r=extract_intent(c["text"])
    check(f"contradictory {c['id']} flagged",r["objective_category"]=="contradictory",
          f"-> {r['objective_category']}")
    check(f"contradictory {c['id']} asks",  "clarify" in r)
    check(f"contradictory {c['id']} zero confidence",r["confidence"]==0.0)
    check(f"contradictory {c['id']} records the competing options",
          len(r.get("alternatives_considered",[]))>=2,str(r.get("alternatives_considered")))

print("=== J4.4 output is always a hypothesis ===")
for c in cases:
    r=extract_intent(c["text"])
    check(f"tagged ai_hypothesis {c['id']}",r["data_class"]=="ai_hypothesis")
    check(f"amount sane {c['id']}", r["amount"] is None or r["amount"]>0)

print("=== J4.5 stated mechanism extracted and ranked first (J5) ===")
for c in ASP["stated_mechanism_cases"]:
    r=extract_intent(c["text"])
    check(f"{c['id']} objective",r["objective_category"]==c["expect_objective"],r["objective_category"])
    check(f"{c['id']} stated",r.get("stated_mechanism")==c["expect_stated"],str(r.get("stated_mechanism")))
    cands=candidates(r)
    check(f"{c['id']} primary mechanism",cands[0]["mechanism"]==c["expect_primary_mechanism"],
          cands[0]["mechanism"])
    check(f"{c['id']} primary flagged as stated",
          cands[0]["is_stated"] == (c["expect_stated"] is not None),
          f"is_stated={cands[0]['is_stated']} expect_stated={c['expect_stated']}")

print("=== J5 rubric validation (J5 DoD: 'validated by rubric, not just present') ===")
RUBRIC=json.load(open("policy/mechanism_rubric.json"))
for rule in RUBRIC["rules"]:
    obj=rule["objective"]
    probe=rule["probe_text"]
    r=extract_intent(probe)
    cands=candidates(r)
    got=[c["mechanism"] for c in cands]
    must=rule["must_include_any"]
    check(f"rubric {rule['id']}: {obj}",any(m in got for m in must),f"got {got} need any of {must}")
    if "must_exclude" in rule:
        check(f"rubric {rule['id']} excludes {rule['must_exclude']}",
              all(rule["must_exclude"] not in g for g in got),f"got {got}")

print("\nJ4/J5:","ALL PASS" if not fails else f"{len(fails)} FAILURES {fails}")
sys.exit(1 if fails else 0)
