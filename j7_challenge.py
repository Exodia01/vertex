"""J7 challenge/nudge with cap 5 per aspiration. Fails closed.

J11 sentiment is an OPTIONAL input: it adjusts how a challenge is phrased, never whether the
underlying gap is real (Anchor 1 J7 scope). If sentiment is absent or raises, this module
degrades to default tone with no sentiment input.
"""
CAP=5
# Raw mechanism ids must never reach the customer. Every label here is reviewable copy.
MECH_DISPLAY={"insurance+reserve":"bima + thoda reserve","liquid reserve":"sirf savings",
              "savings goal":"savings goal","investment allocation":"investment",
              "EMI":"EMI/loan","auto loan":"auto loan","cash purchase":"cash se kharidna",
              "downpayment+mortgage":"down payment + mortgage","refinance/repay":"loan jaldi khatam karna"}
def _m(mech): return MECH_DISPLAY.get(mech,mech)

def _tone(tone,body):
    if tone=="soften_tone": return "Sun, "+body
    if tone=="allow_direct_actionable_phrasing": return "Bhai, tera plan seedha ye hai: "+body
    return "Bhai, "+body

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
        limit=f"Rs {feas.get('avail_stress_monthly',feas['avail_monthly']):,.0f}"
        if feas["outcome"]=="gap":
            short=f"Rs {feas['gap_amount']:,.0f}"
            basis=(" Tera aana seasonal hai, isliye maine sabse kam wali mahine ka hisaab lagaya."
                   if feas.get("stress_applied") else "")
            body=(f"iske liye {need} har mahina chahiye, lekin tera comfortable limit {limit} hai. "
                  f"Matlab har mahine {short} ka shortfall rahega.{basis} "
                  f"Tenz mat le, adjust karna padega. Tera asal maqsad kya hai, ussi hisaab se rasta nikalte hain.")
            alts=[{"type":"timeline","description":"Thoda aur waqt le"},
                  {"type":"target","description":"Target thoda chhota kar"},
                  {"type":"mechanism","description":"Tarika badal"}]
        elif feas["outcome"]=="at-risk":
            better=[r["mechanism"] for r in (all_results or []) if r["outcome"]=="feasible"]
            pick=_m(better[0]) if better else _m("insurance+reserve")
            body=("sirf paise bachana is maqsad ke liye sahi nahi hai — bima ke bina ek bada medical "
                  f"aa gaya to sab khatam. {pick} se ye chalega. Tera asal maqsad safety hai, "
                  "to usi tarike se usse poora karna behtar hai.")
            alts=[{"type":"mechanism","description":f"Tarika badal: {pick}"}]
        else:
            body="tera hisaab theek dikh raha hai. Par phir bhi main ek nazar daal leta hun."
            alts=[]
        st["n"]+=1; st.update({"last_severity":"info"}); self.d[aspiration_id]=st
        return {"challenge":_tone(tone,body),
                "alternatives":alts,"nudge_count":st["n"],
                "tone":tone,"sentiment_applied":signal is not None}
