"""Pipeline orchestrator J1->J10. Deterministic math stays in J6; LLM never computes."""
import json, itertools
from j1_ingest import ingest, Quarantine
from j2_snapshot import build_snapshot
from j3_state import JournalStore
from j4_llm import intent_extractor, sentiment_detector
from j5_mechanism import candidates
from j6_feasibility import compute
from j7_challenge import NudgeLog
from j8_stabilize import stabilize
from j9_memory import MemoryStore
from j10_monitor import Monitor
from j11_sentiment import detect as detect_sentiment, is_contradictory, to_boundary_fields
from audit import AuditLog
from contracts import PINNED

CUSTOMER_REF="cust_opaque_7f3a"
MODIFIER_TO_STATED={"liquid reserve":"savings","insurance+reserve":"insurance",
                    "savings goal":"savings","investment allocation":"investment",
                    "EMI":"loan","auto loan":"loan"}
_ids=itertools.count(1)

class Pipeline:
    def __init__(self, mock_path="mock_aa.json", bench_path="benchmarks.json", memory_path="memory.jsonl",
                 master_secret=None, customer_ref=None):
        self.mock=json.load(open(mock_path)); self.bench=json.load(open(bench_path))
        self.behaviour=self.mock.get("summary_3mo",{})
        self.customer_ref=customer_ref or CUSTOMER_REF
        self.store=JournalStore(); self.nudges=NudgeLog()
        self.memory=MemoryStore(memory_path,master_secret=master_secret,tenant=self.customer_ref)
        self.monitor=Monitor(); self.audit_log=AuditLog(anchor=1)
        self.signals={}; self.priority={}
        self._trace_n=0
        self.snapshot=None; self.quarantine=Quarantine()
        self.baseline=None
        self.goal_seq=0
        self._ingest_and_snapshot()
    def _trace(self, ref):
        self._trace_n+=1
        return f"trc_{ref}_{self._trace_n:08d}"
    def _log(self, ev, actor="ai", **kw):
        """Single audit store. No parallel flat log."""
        # Anchor 1 §17 asks for replay by goal_id, so the goal is the primary ref when known
        # and the aspiration is retained alongside it in detail.
        ref=kw.get("goal_id") or kw.get("aspiration_id") or "system"
        detail={k:v for k,v in kw.items() if k not in ("goal_id",)}
        return self.audit_log.emit(actor,
            ev.replace("STABILIZED_JOURNAL_STATE","journal_state.stabilized"),
            ref, self._trace(ref), detail={"event":ev,**detail})
    def _ingest_and_snapshot(self):
        txns,accts,q,aud=ingest(self.mock["transactions"],self.mock["accounts"],
                                ["txn.read","bal.read","profile.read"],self.quarantine)
        self.txns=txns
        for a in aud: self._log(a["event"])
        pattern=self.mock.get("summary_3mo",{}).get("income_pattern") or self.mock.get("income_pattern","flat")
        self.snapshot,ev=build_snapshot(self.mock.get("persona_id","persona"),txns,accts,
                                        self.mock["as_of"],income_pattern=pattern,
                                        base_currency=self.mock.get("base_currency","INR"))
        self._log(ev["event"],reconciled=ev["reconciled"])
        if not ev["reconciled"]: raise ValueError("snapshot reconciliation failed")
        self.baseline=self.snapshot
    def submit(self, text, amount_override=None, horizon_override=None):
        aid=f"asp_{next(_ids):03d}"
        self.store.transition(aid,None,"raw_observation","observed_data",{"raw_text":text},text,"customer")
        self._log("aspiration.created",aspiration_id=aid)
        intent=intent_extractor()(text)
        signal=None
        try:
            signal=sentiment_detector()(text,aspiration_id=aid)
        except Exception:
            signal=None
        self.signals[aid]=signal
        self._log("sentiment.detected",aspiration_id=aid,
                  stress_band=(signal or {}).get("stress_band","unavailable"),
                  confidence_band=(signal or {}).get("confidence_band","unavailable"))
        if amount_override: intent["amount"]=amount_override
        if horizon_override: intent["horizon_mo"]=horizon_override
        if intent["objective_category"]=="unknown" or "clarify" in intent and intent["confidence"]<0.6:
            self.store.transition(aid,"raw_observation","interpreted_expectation","ai_hypothesis",intent,text,"ai")
            return {"aspiration_id":aid,"status":"needs_clarification","clarify":intent.get("clarify"),"intent":intent}
        self.store.transition(aid,"raw_observation","interpreted_expectation","ai_hypothesis",intent,text,"ai")
        self._log("intent.extracted",aspiration_id=aid,objective=intent["objective_category"],confidence=intent["confidence"])
        cands=candidates(intent)
        self.store.transition(aid,"interpreted_expectation","banking_equivalent","ai_hypothesis",{"candidates":cands},text,"ai")
        self._log("mechanism.candidates.generated",aspiration_id=aid,count=len(cands))
        try:
            results=[compute(c,self.snapshot,self.bench) for c in cands]
        except Exception as e:
            # Anchor 1 §15: engine unavailable -> challenge generation is DEFERRED, the
            # aspiration stays in analysis_pending, and the customer is told. Never a guess.
            self._log("feasibility.deferred",actor="deterministic_engine",
                      aspiration_id=aid,reason=type(e).__name__)
            self.store.transition(aid,"banking_equivalent","analysis","observed_data",
                                  {"results":[],"deferred":True},type(e).__name__,"deterministic_engine")
            return {"aspiration_id":aid,"status":"analysis_pending","candidates":cands,
                    "results":[],"deferred":True,
                    "note":("Mera hisaab engine abhi available nahi hai, isliye main koi "
                            "bhi andaaza nahi laga raha. Thodi der me dubara puchh lena.")}
        for r in results: self._log("feasibility.computed",aspiration_id=aid,mechanism=r["mechanism"],outcome=r["outcome"],gap=r["gap_amount"])
        best=results[0]
        self.store.transition(aid,"banking_equivalent","analysis","observed_data",{"results":results},self.snapshot.balances and "mock_aa","deterministic_engine")
        packet={"aspiration_id":aid,"status":"analysed","intent":intent,"candidates":cands,"results":results}
        if best["outcome"]!="feasible":
            ch=self.nudges.issue(aid,best,all_results=results,signal=signal)
            if ch:
                self.store.transition(aid,"analysis","challenge","ai_hypothesis",{"challenge":ch["challenge"],"alternatives":ch["alternatives"]},best["mechanism"],"ai")
                self._log("challenge.issued",aspiration_id=aid,nudge_count=ch["nudge_count"])
                packet.update(ch)
            else:
                packet["status"]="analysis_pending"
                packet["note"]="nudge cap reached, challenge deferred"
        return packet
    def respond(self, aspiration_id, response, modified=None, sentiment=None):
        hist=self.store.history(aspiration_id)
        signal=self.signals.get(aspiration_id)
        def latest(state):
            for e in reversed(hist):
                if e["state"]==state: return e
            return None
        intent=latest("interpreted_expectation")["payload"]
        latest_be=latest("banking_equivalent")
        cands=latest_be["payload"]["candidates"]
        results=latest("analysis")["payload"]["results"]
        if response=="reject":
            self.store.transition(aspiration_id,"analysis","customer_response","customer_rejected_interpretation",{"response":"reject"},"customer","customer")
            return {"aspiration_id":aspiration_id,"status":"abandoned"}
        if response=="modify":
            # Anchor 1 J8: modify loops back to J5 AND J6, not J6 alone. Re-derive the
            # candidate set from the modified intent so the mechanism itself is reconsidered -
            # a different target or horizon can legitimately change which construct is right.
            self.store.transition(aspiration_id,"analysis","customer_response","customer_confirmed_data",{"response":"modify","modified":modified or {}},modified or "customer","customer")
            new_intent=dict(intent)
            if modified and "target" in modified: new_intent["amount"]=modified["target"]
            if modified and "timeline_mo" in modified: new_intent["horizon_mo"]=modified["timeline_mo"]
            if modified and "mechanism" in modified:
                new_intent["stated_mechanism"]=MODIFIER_TO_STATED.get(modified["mechanism"])
            newc=candidates(new_intent)
            if not newc:
                newc=[dict(c) for c in cands]
                if modified and "target" in modified: newc[0]["required_capital"]=modified["target"]
                if modified and "timeline_mo" in modified: newc[0]["horizon_mo"]=modified["timeline_mo"]
            self._log("mechanism.candidates.regenerated",aspiration_id=aspiration_id,count=len(newc))
            self.store.transition(aspiration_id,"customer_response","banking_equivalent","customer_confirmed_data",
                                  {"candidates":newc,"regenerated_from":"j5"},modified or "customer","ai")
            newres=[compute(c,self.snapshot,self.bench) for c in newc]
            self.store.transition(aspiration_id,"banking_equivalent","analysis","observed_data",{"results":newres},"mock_aa","deterministic_engine")
            out={"aspiration_id":aspiration_id,"status":"re-analysed","results":newres,
                 "candidates":newc,"regenerated_from":"j5"}
            if newres[0]["outcome"]!="feasible":
                ch=self.nudges.issue(aspiration_id,newres[0],all_results=newres,signal=signal)
                if ch:
                    self.store.transition(aspiration_id,"analysis","challenge","ai_hypothesis",{"challenge":ch["challenge"],"alternatives":ch["alternatives"]},newres[0]["mechanism"],"ai")
                    out.update(ch)
            return out
        feas=results[0]; cand=cands[0]
        self.store.transition(aspiration_id,"analysis","customer_response","customer_confirmed_data",{"response":"accept"},"customer","customer")
        self.goal_seq+=1; goal_id=f"goal_{self.goal_seq:03d}"
        rec=self.memory.add(goal_id,self.customer_ref,intent["objective_category"],cand["mechanism"],
                            cand["required_capital"],cand["horizon_mo"],
                            extra={"feasibility_outcome":feas["outcome"],"aspiration_id":aspiration_id,
                                   "contract_version":PINNED})
        prior=[s for s in [self.signals.get(aspiration_id)] if s]
        note=None
        if sentiment is not None: prior.append(sentiment)
        try: note=is_contradictory(prior,"accept")
        except Exception: note=None
        res=stabilize(aspiration_id,self.customer_ref,intent,cand,feas,"accept",
                      version=rec["state_version"],
                      sentiment_band=(sentiment or {}).get("stress_band"),
                      confidence_band=(sentiment or {}).get("confidence_band"),
                      contradiction_note=(note or {}).get("contradiction_note") if note else None,
                      follow_up_at=(note or {}).get("follow_up_at") if note else None)
        if not res["stabilized"]: return {"aspiration_id":aspiration_id,"status":"not_stabilized"}
        self.store.transition(aspiration_id,"customer_response","stabilized_state","customer_confirmed_data",res["payload"],"customer","deterministic_engine")
        self._log("goal.stabilized",aspiration_id=aspiration_id,goal_id=goal_id,actor="customer")
        self._log("STABILIZED_JOURNAL_STATE",aspiration_id=aspiration_id,goal_id=goal_id,
                  actor="deterministic_engine",state_version=rec["state_version"])
        self.store.transition(aspiration_id,"stabilized_state","monitoring","observed_data",{"goal_id":goal_id},"memory","deterministic_engine")
        out={"aspiration_id":aspiration_id,"status":"stabilized","goal":rec,"event":res["payload"]}
        if "internal" in res: out["internal"]=res["internal"]
        return out
    def revise(self, goal_id, target=None, timeline_mo=None, sentiment=None):
        """J9 multi-revision path: re-run deterministic feasibility for an already
        stabilized goal and append a new version of the SAME goal_id."""
        revs=self.memory.revisions(goal_id)
        if not revs: return {"status":"not_found"}
        cur=revs[-1]
        cand={"mechanism":cur["mechanism"],"required_capital":target or cur["target"],
              "horizon_mo":timeline_mo or cur["timeline"],
              "liquidity_need":"high" if cur["objective"] in ("protection","liquidity") else "med",
              "financing_need":("loan" in cur["mechanism"].lower() or "emi" in cur["mechanism"].lower())}
        feas=compute(cand,self.snapshot,self.bench)
        self._log("feasibility.computed",actor="deterministic_engine",
                  goal_id=goal_id,mechanism=feas["mechanism"],outcome=feas["outcome"])
        rec=self.memory.add(goal_id,cur["customer_ref"],cur["objective"],cand["mechanism"],
                            cand["required_capital"],cand["horizon_mo"],
                            extra={"feasibility_outcome":feas["outcome"],
                                   "aspiration_id":cur.get("aspiration_id"),
                                   "contract_version":PINNED,
                                   "revision_reason":cur.get("revision_reason","customer_revised")})
        intent={"objective_category":cur["objective"]}
        res=stabilize(cur.get("aspiration_id","asp_000"),cur["customer_ref"],intent,cand,feas,
                      "accept",version=rec["state_version"],
                      sentiment_band=(sentiment or {}).get("stress_band"),
                      confidence_band=(sentiment or {}).get("confidence_band"))
        self._log("goal.stabilized",actor="customer",goal_id=goal_id,state_version=rec["state_version"])
        self._log("STABILIZED_JOURNAL_STATE",actor="deterministic_engine",goal_id=goal_id,
                  state_version=rec["state_version"])
        out={"status":"revised","goal":rec,"event":res["payload"],
             "revisions":[r["state_version"] for r in self.memory.revisions(goal_id)]}
        if "internal" in res: out["internal"]=res["internal"]
        return out

    def raise_priority(self, goal_id, reason, actor="deterministic_engine"):
        """J10 priority.raised has to change behaviour to be worth emitting. A raised goal
        jumps ahead of routine goals when the next check-in is ordered, and its pending
        challenge is re-surfaced rather than left to expire silently."""
        cur=self.priority.get(goal_id,0)
        self.priority[goal_id]=cur+1
        self._log("priority.raised",goal_id=goal_id,reason=reason,level=cur+1,actor=actor)
        return {"goal_id":goal_id,"priority":cur+1,"reason":reason}

    def ordered_checkins(self):
        """Goals ordered for the next customer contact. Raised goals come first, then by the
        size of the shortfall, then oldest."""
        rows=[]
        for g in self.memory.revisions_of(self.customer_ref) if hasattr(self.memory,"revisions_of") \
                 else [r for r in self.memory.query(self.customer_ref) if r.get("record_type")=="goal" and not r.get("tombstone")]:
            rows.append({"goal_id":g["goal_id"],"priority":self.priority.get(g["goal_id"],0),
                         "target":g.get("target",0),"timeline":g.get("timeline",0),
                         "feasibility_outcome":g.get("feasibility_outcome")})
        return sorted(rows,key=lambda r:(-r["priority"],r["feasibility_outcome"]!="gap",-r["target"]))

    def simulate_material_change(self, kind):
        from dataclasses import replace
        if kind=="income_drop":
            prev=self.baseline
            self.snapshot=replace(self.snapshot,income_monthly_avg=round(self.snapshot.income_monthly_avg*0.6,2))
            events=self.monitor.detect(self.customer_ref,prev,self.snapshot,[],signal=self.signals.get("last"))
        elif kind=="large_withdrawal":
            class T: amount=85000; id="txn_090"
            events=self.monitor.detect(self.customer_ref,self.baseline,self.snapshot,[T()],signal=self.signals.get("last"))
        else:
            return []
        out=[]
        for e in events:
            if e["event"]=="priority.raised":
                self._log(e["event"],trigger=e["trigger"])
                for g in self.memory.query(self.customer_ref):
                    if g.get("record_type")=="goal" and not g.get("tombstone"):
                        self.raise_priority(g["goal_id"],e["trigger"]["type"])
                        e["goal_id"]=g["goal_id"]
                out.append(e); continue
            self._log(e["event"],trigger=e["trigger"])
            goals=self.memory.query(self.customer_ref)
            for g in goals:
                if g.get("tombstone"): continue
                feas={"mechanism":g["mechanism"],"required_capital":g["target"],
                      "horizon_mo":g["timeline"],"liquidity_need":"med","financing_need":False}
                newr=compute(feas,self.snapshot,self.bench)
                if newr["outcome"]!="feasible":
                    ch=self.nudges.issue(g["aspiration_id"],newr,all_results=[newr])
                    out.append({"goal_id":g["goal_id"],"new_outcome":newr["outcome"],
                                "monthly_need":newr["monthly_need"],"challenge":(ch or {}).get("challenge"),
                                "alternatives":(ch or {}).get("alternatives",[])})
                else:
                    out.append({"goal_id":g["goal_id"],"new_outcome":newr["outcome"]})
        return out
    def memory_view(self, requester=None):
        """Customer-facing read (§9). Access is scoped to the owning customer, and every read of
        financial data is written to the audit trail (§13)."""
        self.audit_log.record_read(requester or "customer","financial_memory",
                                   self._trace("mem"),
                                   fields=["goal_id","objective","mechanism","target"],
                                   purpose="journal_analysis",subject=self.customer_ref)
        return self.memory.query(self.customer_ref,requester=requester)
    def funnel(self):
        f={}
        for e in self.store.entries:
            f[e["state"]]=f.get(e["state"],0)+1
        f["audit_events"]=len(self.audit_log.records)
        f["read_events"]=len(self.audit_log.read_events())
        f["quarantined"]=self.quarantine.count()
        f["nudges_issued"]=sum(v["n"] for v in self.nudges.d.values())
        return f
