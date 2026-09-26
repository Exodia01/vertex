"""J7 challenge/nudge with cap 5 per aspiration. Fails closed.

J11 sentiment is an OPTIONAL input: it adjusts how a challenge is phrased, never whether the
underlying gap is real (Anchor 1 J7 scope). If sentiment is absent or raises, this module
degrades to default tone with no sentiment input.
"""
CAP=5
# Raw mechanism ids must never reach the customer. Every label here is reviewable copy.
MECH_DISPLAY={"insurance+reserve":"insurance plus a small reserve","liquid reserve":"savings alone",
              "savings goal":"a savings goal","investment allocation":"an investment plan",
              "EMI":"a loan/EMI plan","auto loan":"a car loan","cash purchase":"paying cash",
              "downpayment+mortgage":"a down payment plus mortgage",
              "refinance/repay":"refinancing or repaying"}
def _m(mech): return MECH_DISPLAY.get(mech,mech)

def _tone(tone,body):
    if tone=="soften_tone": return "Take a breath. "+body
    if tone=="allow_direct_actionable_phrasing": return "Straight to it. "+body
    return body

class NudgeLog:
    def __init__(self): self.d={}
    def count(self,a): return self.d.get(a,{"n":0})["n"]
    def issue(self, aspiration_id, feas, all_results=None, target=None, signal=None):
        st=self.d.get(aspiration_id,{"n":0})
        if st["n"]>=CAP: return None
        tone="default_tone"
        if signal is not None:
            try:
                from j11_sentiment import tone_directive
                tone=tone_directive(signal)
            except Exception:
                tone="default_tone"
        # J7 authors the customer-facing text, in the customer's language. Narration must not
        # re-derive it, or the journal and the screen disagree about what was actually said.
        need=f"Rs {feas['monthly_need']:,.0f}"
        # .get()'s default is evaluated eagerly, so read the fallback explicitly.
        limit_amt=feas.get("avail_stress_monthly")
        if limit_amt is None: limit_amt=feas.get("avail_monthly",0)
        limit=f"Rs {limit_amt:,.0f}"
        if feas["outcome"]=="gap":
            short=f"Rs {feas['gap_amount']:,.0f}"
            basis=(" Your income is seasonal, so I used your worst month rather than your average."
                   if feas.get("stress_applied") else "")
            body=(f"this needs {need} a month, but your comfortable limit is {limit}. "
                  f"That is a {short} shortfall every month.{basis} "
                  f"I wouldn't take that on. Let's adjust it — what you actually want is still reachable.")
            alts=[{"type":"timeline","description":"Give it more time"},
                  {"type":"target","description":"Make the target smaller"},
                  {"type":"mechanism","description":"Use a different method"}]
        elif feas["outcome"]=="at-risk":
            better=[r["mechanism"] for r in (all_results or []) if r["outcome"]=="feasible"]
            pick=_m(better[0]) if better else _m("insurance+reserve")
            body=("savings on their own won't do this. Without insurance, one large medical bill "
                  f"wipes it out. {pick.capitalize()} works. What you want is safety, so it's worth "
                  "covering it the right way.")
            alts=[{"type":"mechanism","description":f"Switch to {pick}"}]
        else:
            body="your numbers look fine. I'll still keep an eye on it."
            alts=[]
        st["n"]+=1; st.update({"last_severity":"info"}); self.d[aspiration_id]=st
        return {"challenge":_tone(tone,body),
                "alternatives":alts,"nudge_count":st["n"],
                "tone":tone,"sentiment_applied":signal is not None}
