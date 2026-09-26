"""Shared audit event envelope (Master §3.6, Anchor 1 §17).

ONE store, one structure, every action - including every READ of raw financial data, which
Anchor 1 §13 requires. Schema-validated on emit. This is the single queryable audit store;
nothing else keeps a competing parallel log.
"""
import itertools, json
from contracts import validate_event

PRINCIPALS=("customer","ai","deterministic_engine","human_auditor",
            "anchor1","anchor2","anchor3","anchor4")
ACTOR_ALIASES={"engine":"deterministic_engine","system":"deterministic_engine",
               "human":"human_auditor","anchor":"ai","intruder":"ai"}
_ctr=itertools.count(1)

def _norm_actor(a):
    a=ACTOR_ALIASES.get(a,a)
    base=a.split(".")[0]
    if base not in PRINCIPALS:
        raise ValueError(f"illegal audit actor {a!r}")
    return a

def _norm_action(a):
    a=a.lower()
    if not all(c.islower() or c.isdigit() or c in "._" for c in a):
        raise ValueError(f"illegal audit action {a!r}")
    return a

class AuditLog:
    def __init__(self, anchor=1):
        self.anchor=anchor; self.records=[]; self._seq=itertools.count(1)
    def emit(self, actor, action, evidence_ref, trace_id, contract_version="v1", detail=None):
        env={"actor":_norm_actor(actor),"action":_norm_action(action),
             "evidence_ref":evidence_ref,"timestamp":"2026-09-26T10:00:00Z",
             "trace_id":trace_id,"anchor":self.anchor,"contract_version":contract_version}
        if detail: env["detail"]=detail
        n=next(self._seq)
        env["timestamp"]=f"2026-09-26T{10+n%12:02d}:{(n//12)%60:02d}:00Z"
        errs=validate_event(env,"AUDIT")
        if errs: raise ValueError(f"invalid audit envelope: {errs[:2]}")
        self.records.append(env)
        return env
    def record_read(self, actor, resource, trace_id, fields=None, purpose=None, subject=None):
        """Anchor 1 §13: full audit trail on every read of raw financial data.

        The actor is the ROLE, never the opaque customer_ref - the ref is PII-adjacent and
        belongs in detail, and it is not a legal actor value.
        """
        role=actor if actor in ("customer","ai","deterministic_engine","human_auditor") else "customer"
        return self.emit(role,"financial_data.read",resource,trace_id,
                         detail={"fields":sorted(fields or []),"purpose":purpose,
                                 "subject":subject})
    def for_goal(self,goal_id):
        """Match a goal across evidence_ref and detail, since the ref points at whichever
        identifier the acting step had available."""
        out=[]
        for r in self.records:
            blob=json.dumps({"ref":r["evidence_ref"],"detail":r.get("detail")},default=str)
            if goal_id in blob: out.append(r)
        return out
    def by_trace(self,trace_id):
        return [r for r in self.records if r["trace_id"]==trace_id]
    def by_actor(self,actor):
        return [r for r in self.records if r["actor"]==actor]
    def read_events(self):
        return [r for r in self.records if r["action"]=="financial_data.read"]
    def replay(self,goal_id):
        """§17: given a goal_id, reconstruct the entire decision path in order."""
        return [{"seq":i,"actor":r["actor"],"action":r["action"],"trace":r["trace_id"],
                 "at":r["timestamp"]} for i,r in enumerate(self.for_goal(goal_id),start=1)]
    def actions(self):
        return [r["action"] for r in self.records]
    def count_action(self,name): return sum(1 for a in self.actions() if a==name)
    def counts_by_action(self):
        out={}
        for r in self.records: out[r["action"]]=out.get(r["action"],0)+1
        return dict(sorted(out.items()))
