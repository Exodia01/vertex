"""J10 continuous monitoring.

Financial triggers (large withdrawal, income drop) re-run the deterministic feasibility
engine. A sentiment spike from J11 is a SEPARATE, lower-weight trigger: it raises priority for
attention but must never re-run the feasibility engine on its own (Anchor 1 J10 scope).
Rate-limited per customer so triggers cannot storm.
"""
LARGE_WITHDRAWAL=50000
INCOME_DROP_PCT=0.20
STRESS_PRIORITY_BAND="high_stress"
class Monitor:
    def __init__(self, rate_limit=1):
        self.rate_limit=rate_limit; self.fired={}; self.priority={}
    def detect(self, customer_ref, prev_snapshot, new_snapshot, new_txns, signal=None):
        events=[]
        for t in new_txns or []:
            amt=t.amount if hasattr(t,"amount") else t.get("amount",0)
            if amt>=LARGE_WITHDRAWAL:
                events.append({"type":"large_withdrawal","amount":amt,"ref":getattr(t,"id",None)})
        if prev_snapshot and new_snapshot:
            p=prev_snapshot.income_monthly_avg; n=new_snapshot.income_monthly_avg
            if p>0 and (p-n)/p>=INCOME_DROP_PCT:
                events.append({"type":"income_drop","from":p,"to":n})
        out=[]
        for e in events:
            c=self.fired.get(customer_ref,0)
            if c>=self.rate_limit: continue
            self.fired[customer_ref]=c+1
            out.append({"event":"reanalysis.triggered","customer_ref":customer_ref,"trigger":e})
        out+=self.detect_priority(customer_ref,signal)
        return out
    def detect_priority(self, customer_ref, signal):
        """Sentiment-only trigger. Raises priority, never re-runs feasibility."""
        if not signal: return []
        if signal.get("stress_band")!=STRESS_PRIORITY_BAND: return []
        c=self.priority.get(customer_ref,0)
        if c>=self.rate_limit: return []
        self.priority[customer_ref]=c+1
        return [{"event":"priority.raised","customer_ref":customer_ref,
                 "trigger":{"type":"stress_spike","band":STRESS_PRIORITY_BAND},
                 "reruns_feasibility":False}]
