"""Observability (Anchor 1 §16).

Numeric correctness in the feasibility engine is safety-critical, so latency and error rate
are measured rather than assumed. Intent-classification confidence is tracked as a
distribution and flagged when it trends down.

Run: python3 tools/observability.py
"""
import json, sys, time
sys.path.insert(0,".")
from j1_ingest import ingest
from j2_snapshot import build_snapshot
from j4_intent import extract_intent
from j6_feasibility import compute
import j6_feasibility as J6

BUCKETS=[(0.0,0.2,"very_low"),(0.2,0.4,"low"),(0.4,0.6,"mid"),
         (0.6,0.8,"good"),(0.8,1.01,"high")]

def bucket(c):
    for lo,hi,name in BUCKETS:
        if lo<=c<hi: return name
    return "high"

class Observability:
    def __init__(self): self.reset()
    def reset(self):
        self.intent_conf=[]; self.latencies=[]; self.errors=0; self.calls=0
        self.nudges=[]
    def record_intent(self,conf,category=None):
        self.intent_conf.append({"confidence":conf,"bucket":bucket(conf),"category":category})
    def time_engine(self,fn,*a,**kw):
        self.calls+=1; t=time.perf_counter()
        try: r=fn(*a,**kw)
        except Exception:
            self.errors+=1; raise
        finally: self.latencies.append((time.perf_counter()-t)*1000.0)
        return r
    def record_nudge(self,aspiration_id,count,severity=None):
        self.nudges.append({"aspiration_id":aspiration_id,"count":count,"severity":severity})
    def confidence_distribution(self):
        d={}
        for r in self.intent_conf: d[r["bucket"]]=d.get(r["bucket"],0)+1
        return d
    def confidence_trend(self,window=10):
        """Flag when recent classifications sit materially below the earlier baseline."""
        if len(self.intent_conf)<window*2: return {"status":"insufficient_data"}
        older=[r["confidence"] for r in self.intent_conf[:-window]]
        recent=[r["confidence"] for r in self.intent_conf[-window:]]
        o=sum(older)/len(older); n=sum(recent)/len(recent)
        drop=round(o-n,3)
        return {"status":"degrading" if drop>0.15 else "stable",
                "baseline_mean":round(o,3),"recent_mean":round(n,3),"drop":drop}
    def engine_stats(self):
        if not self.latencies: return {"status":"no_data"}
        s=sorted(self.latencies)
        return {"calls":self.calls,"errors":self.errors,
                "error_rate":round(self.errors/max(1,self.calls),4),
                "latency_ms_mean":round(sum(s)/len(s),3),
                "latency_ms_p50":round(s[len(s)//2],3),
                "latency_ms_p95":round(s[int(len(s)*0.95)],3),
                "latency_ms_max":round(s[-1],3),
                "policy_version":J6.POLICY_VERSION}
    def report(self):
        return {"funnel_note":"see pipeline.funnel()",
                "intent_confidence":{"distribution":self.confidence_distribution(),
                                     "trend":self.confidence_trend()},
                "feasibility_engine":self.engine_stats(),
                "nudges":{"issued":len(self.nudges)}}

if __name__=="__main__":
    mock=json.load(open("mock_aa.json"))
    tx,ac,q,_=ingest(mock["transactions"],mock["accounts"],["txn.read","bal.read"])
    snap,_=build_snapshot("p",tx,ac,mock["as_of"],income_pattern=mock["income_pattern"])
    obs=Observability()
    cases=json.load(open("fixtures/aspirations.json"))["cases"]
    cands=[{"mechanism":"savings goal","required_capital":c["amount"] or 200000,
            "horizon_mo":c["horizon_mo"] or 12,"liquidity_need":"med","financing_need":False}
           for c in cases if c.get("amount") and c.get("horizon_mo")]
    for _ in range(50):
        for c in cases:
            r=extract_intent(c["text"]); obs.record_intent(r["confidence"],r["objective_category"])
        for cd in cands: obs.time_engine(compute,cd,snap)
    rep=obs.report()
    print(json.dumps(rep,indent=2))
    eng=rep["feasibility_engine"]; conf=rep["intent_confidence"]
    bad=[]
    if eng["error_rate"]>0: bad.append("engine errors present")
    if eng["calls"]<100: bad.append("too few engine calls measured")
    if not conf["distribution"]: bad.append("no confidence distribution")
    if conf["trend"]["status"]=="insufficient_data": bad.append("trend not computable")
    print("\nOBSERVABILITY:","ALL PASS" if not bad else f"FAILURES {bad}")
    sys.exit(1 if bad else 0)
