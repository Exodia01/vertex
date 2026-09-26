"""Measure the deterministic classifier and the local model against the same labeled fixtures.

Reports three numbers, not one:
  deterministic accuracy  - the floor the app always has
  model accuracy           - what the model adds on its own
  disagreements            - where they differ and which one was right

The disagreement set is the point. A local model that scores well overall can still be worse
on the specific distinctions the deterministic layer owns, and only the disagreement set shows
that. Arithmetic is never involved: the model is only ever asked for labels.

Run: python3 tools/eval_arms.py            # deterministic only
     IASPIRE_LLM=1 IASPIRE_LLM_PROVIDER=ollama IASPIRE_LLM_MODEL=<model> python3 tools/eval_arms.py
"""
import json, os, sys, time
sys.path.insert(0,os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from j4_intent import extract_intent as det_intent
from j11_sentiment import detect as det_sentiment

RANK={"low":0,"low_stress":0,"low_confidence":0,"medium":1,
      "moderate":1,"moderate_stress":1,"moderate_confidence":1,
      "high":2,"high_stress":2,"high_confidence":2}

def band_of(score):
    return "high" if score>=0.66 else ("moderate" if score>=0.33 else "low")

def eval_intent():
    import j4_llm as L
    fx=json.load(open("fixtures/aspirations.json"))
    clear=[c for c in fx["cases"] if c["bucket"]=="clear"]
    ambig=[c for c in fx["cases"] if c["bucket"]=="ambiguous"]
    contra=[c for c in fx["cases"] if c["bucket"]=="contradictory"]
    use_model=L.ENABLED
    rows=[]
    for c in fx["cases"]:
        det=det_intent(c["text"])
        mod=L.intent_extractor()(c["text"]) if use_model else None
        want=c["label"]
        rows.append({"id":c["id"],"bucket":c["bucket"],"text":c["text"],
                     "want":want,"det":det["objective_category"],
                     "det_asks":"clarify" in det,
                     "model":(mod or {}).get("objective_category") or
                             ("contradictory" if (mod or {}).get("engine")=="disagreement"
                              and (mod or {}).get("model_said") is None else
                              (mod or {}).get("model_said")),
                     "model_engine":(mod or {}).get("engine")})
    d_ok=sum(1 for r in rows if (r["want"] and r["det"]==r["want"]) or
             (not r["want"] and r["det_asks"]))
    m_ok=sum(1 for r in rows if r["model"] and
             ((r["want"] and r["model"]==r["want"]) or (not r["want"] and r["model"]=="contradictory")))
    # a model-says-contradictory on an ambiguous case counts as asking, which is correct
    dis=[r for r in rows if r["model"] and r["model"]!=r["det"]]
    # also count cases where the model forced a contradiction the deterministic layer did not see
    for r in rows:
        if r["model"]=="contradictory" and r["det"]!="contradictory" and r not in dis:
            dis.append(r)
    return {"total":len(rows),"clear":len(clear),"ambiguous":len(ambig),"contradictory":len(contra),
            "deterministic_correct":d_ok,"deterministic_accuracy":round(d_ok/len(rows),3),
            "model_correct":(m_ok if use_model else None),
            "model_accuracy":(round(m_ok/len(rows),3) if use_model else None),
            "disagreements":len(dis),
            "disagreement_detail":[
                {"id":r["id"],"text":r["text"],"want":r["want"],"det":r["det"],
                 "model":r["model"],"det_right":bool(r["want"] and r["det"]==r["want"]) or not r["want"],
                 "model_right":bool(r["want"] and r["model"]==r["want"]) or not r["want"]}
                for r in dis]}

def eval_sentiment():
    import j4_llm as L
    fx=json.load(open("fixtures/sentiment.json"))
    checked=0; d_ok=0; m_ok=0; dis=0
    for pair in fx["pairs"]:
        for variant in ("calm","urgent","anxious","unsure"):
            case=pair[variant]; want=case["expect"]; text=case["text"]
            det=det_sentiment(text)
            mod=L.sentiment_detector()(text) if L.ENABLED else None
            for dim in ("stress","urgency","frustration","confidence"):
                if dim not in want: continue
                checked+=1
                db={"stress":det["stress_band"],"confidence":det["confidence_band"]}.get(dim) \
                    or band_of(det[dim])
                if RANK[db]==RANK[want[dim]] or (dim=="stress" and RANK[db]>=RANK[want[dim]]): d_ok+=1
                if mod:
                    mb={"stress":mod["stress_band"],"confidence":mod["confidence_band"]}.get(dim) \
                       or band_of(mod[dim])
                    if RANK[mb]==RANK[want[dim]] or (dim=="stress" and RANK[mb]>=RANK[want[dim]]): m_ok+=1
                    if RANK[mb]!=RANK[db]: dis+=1
    return {"dimensions_checked":checked,
            "deterministic_correct":d_ok,"deterministic_accuracy":round(d_ok/checked,3),
            "model_correct":(m_ok if L.ENABLED else None),
            "model_accuracy":(round(m_ok/checked,3) if L.ENABLED else None),
            "band_disagreements":dis}

def main():
    import j4_llm as L
    t0=time.time()
    print("="*66)
    print(f"LLM enabled : {L.ENABLED}  provider={L.PROVIDER}  model={L.MODEL or '-'}")
    print(f"arbitration : {L.ARBITRATION}")
    print(f"ollama      : {'reachable' if L.ollama_reachable() else 'unreachable'}"
          if L.ENABLED else "ollama      : n/a (deterministic only)")
    print("="*66)
    i=eval_intent()
    print("\nJ4 INTENT (17 labeled cases)")
    print(f"  deterministic : {i['deterministic_correct']}/{i['total']} = {i['deterministic_accuracy']:.0%}"
          f"   (clear {i['clear']} / ambiguous {i['ambiguous']} / contradictory {i['contradictory']})")
    if i["model_accuracy"] is not None:
        print(f"  model         : {i['model_correct']}/{i['total']} = {i['model_accuracy']:.0%}")
        print(f"  disagreements : {i['disagreements']}")
        for d in i["disagreement_detail"]:
            mark="det right" if d["det_right"] else ("model right" if d["model_right"] else "both wrong")
            print(f"    {d['id']}  want={d['want']}  det={d['det']}  model={d['model']}  -> {mark}")
            print(f"      \"{d['text']}\"")
    s=eval_sentiment()
    print("\nJ11 SENTIMENT (labeled pairs)")
    print(f"  deterministic : {s['deterministic_correct']}/{s['dimensions_checked']} = {s['deterministic_accuracy']:.0%}")
    if s["model_accuracy"] is not None:
        print(f"  model         : {s['model_correct']}/{s['dimensions_checked']} = {s['model_accuracy']:.0%}")
        print(f"  band disagreements: {s['band_disagreements']}")
    print(f"\narbitration stats: {L.llm_stats()['intent']}")
    print(f"elapsed: {time.time()-t0:.1f}s")
    # The invariant that must never move: the model cannot change any outcome.
    print("\nINVARIANT: model contributes labels only; all arithmetic stays in j6_feasibility.")

if __name__=="__main__": main()
