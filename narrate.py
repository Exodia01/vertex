"""Friend-voice narration. Every number is read from engine output, never invented.
No LLM here on purpose: instant, offline, and structurally incapable of hallucinating a figure."""
import json

def _inr(n):
    n=float(n)
    if n>=10000000: return f"Rs {n/10000000:.2f} Cr"
    if n>=100000: return f"Rs {n/100000:.2f} L"
    return f"Rs {int(n):,}"

OBJ_LABEL={
 "travel":"baahar ka safar","asset":"koi bada kharidna","protection":"family ko suraksha",
 "liquidity":"paisa rakhna","wealth":"paisa badhana","debt":"loan niptana","unknown":"samajh nahi aaya",
}
MECH_LABEL={
 "savings goal":"Savings goal chal raha hai","auto loan":"Auto loan","cash purchase":"Cash se kharidna",
 "EMI":"EMI / loan","downpayment+mortgage":"Down payment + mortgage",
 "insurance+reserve":"Insurance + thoda reserve","liquid reserve":"Sirf savings",
 "investment allocation":"Investment allocation","refinance/repay":"Refinance / repayment",
}
ALT_LABEL={
 "timeline":"Thoda aur waqt le","target":"Target thoda chhota kar",
 "mechanism":"Tarika badal",
}

def greeting(hour=None, streak=0):
    h=hour if hour is not None else 12
    part = "Subah" if h<12 else ("Dopahar" if h<17 else "Raat")
    s=f"{part} bhai. Hisab dekhte hain."
    if streak>0: s+=f"  Diya {streak} din se jal raha hai."
    else: s+="  Aaj pehli baar bol rahe ho, koi baat nahi."
    return s

def clarify(intent):
    return intent.get("clarify","Thoda aur batao bhai.")

def objective(intent):
    lbl=OBJ_LABEL.get(intent["objective_category"],intent["objective_category"])
    amt=intent.get("amount")
    h=intent.get("horizon_mo",12)
    if amt:
        return f"Suna main ne: {lbl} — {_inr(amt)}, {h} mahine me."
    return f"Suna main ne: {lbl}. Paisa aur time abhi clear nahi, wo batao."

def evidence(snapshot, behaviour, results, soul=None):
    leaks=behaviour.get("top_leaks") or []
    joy=behaviour.get("joy",0)
    lines=[f"Average mahina aana: {_inr(snapshot.income_monthly_avg)}.",
           f"Hath me turant: {_inr(snapshot.balances.get('savings',0))}."]
    mf=snapshot.balances.get("mf",0); fd=snapshot.balances.get("fd",0)
    if mf or fd:
        lines.append(f"Parked kaagaz pe: {_inr(mf+fd)} (MF {_inr(mf)} + FD {_inr(fd)}).")
    if soul:
        fam=[f for f in (soul.get("household") or soul.get("family") or []) if f]
        if fam: lines.append("Ghar ka bhaar: "+", ".join(fam)+".")
        goals=[g["name"] for g in soul.get("goals",[]) if g.get("name")]
        if goals: lines.append("Tere mann ke plan: "+", ".join(goals)+".")
    if leaks:
        top=leaks[0]
        lines.append(f"3 mahine me bekaar kharch: {_inr(top['total'])} ({top['count']}x {top['merchant'].split('/')[0]}).")
    if joy and joy<20000:
        lines.append(f"Apne liye kharch: sirf {_inr(joy)}. Matlab apni baari me zyada nahi kharche.")
    r=results[0]
    lines.append(f"Emergency cushion: {r['emergency_mo']} mahine.")
    if r.get("stress_applied"):
        lines.append(f"Sabse kam aana: {_inr(r['income_worst_used'])} (average {_inr(r['income_avg_used'])}).")
    return lines

def verdict(result, snapshot, challenge=None):
    """Headline register + arithmetic. When J7 has authored a challenge, that text is the
    customer-facing body - narration must not paraphrase it, or the journal and the screen
    would disagree about what was actually said."""
    o=result["outcome"]
    need=_inr(result["monthly_need"])
    stress=result.get("stress_applied")
    limit=result.get("avail_stress_monthly",result["avail_monthly"])
    if o=="feasible":
        if stress:
            body=(f"{need} per mahina chahiye. Tera aana seasonal hai — isliye maine hisaab teri "
                  f"sabse kam wali mahine ({_inr(result['income_worst_used'])}) se lagaya, jabki average "
                  f"{_inr(result['income_avg_used'])} hai. Usi hisaab se {_inr(limit)} bachta hai. "
                  f"Emergency {result['emergency_mo']} mahine. Ye plan chalega.")
        else:
            body=(f"{need} per mahina chahiye, aur tere {limit} khaane me se niklta hai. "
                  f"Emergency {result['emergency_mo']} mahine bacha hai. Ye plan chalega.")
        return "GO AHEAD", body
    if o=="gap":
        return "YE HO NHI SAKTA AS IS", (challenge or
                (f"{need} chahiye mahina, lekin comfortable limit {_inr(limit)} hai. "
                 f"Matlab har mahine {_inr(result['gap_amount'])} ka shortfall."))
    return "EK GALTI MILI", (challenge or
            "Sirf paise bachana is maqsad ke liye sahi nahi hai. Ek aur rasta hai.")

def alternatives(alts):
    """J7 already authors these in the customer's language; do not re-translate."""
    return [a["description"] for a in alts]

def decision_options():
    return [
      {"id":"accept","label":"Theek hai, pakka kar do","hint":"Yehi plan meri financial memory me chala jayega"},
      {"id":"modify","label":"Thoda aur waqt de do","hint":"Timeline badlunga, dubara hisaab lagao"},
      {"id":"reject","label":"Abhi nahi chahiye","hint":"Isko band kar do, yaad rakh lena"},
    ]

def confirmation(goal):
    return (f"Ho gaya. {goal['goal_id']} pakka: {OBJ_LABEL.get(goal['objective'],goal['objective'])}, "
            f"{MECH_LABEL.get(goal['mechanism'],goal['mechanism'])} — {_inr(goal['target'])} "
            f"{goal['timeline']} mahine me. Ye main yaad rakhunga aur jab bhi kuch badlega, batayega.")

def memory_line(rec):
    if rec.get("tombstone"): return f"{rec['goal_id']} — hata diya gaya (consent change)."
    return (f"{rec['goal_id']}: {OBJ_LABEL.get(rec['objective'],rec['objective'])} | "
            f"{MECH_LABEL.get(rec['mechanism'],rec['mechanism'])} — {_inr(rec['target'])} / {rec['timeline']}mo "
            f"[{rec['state_version']}]")

TRIGGER_LABEL={"large_withdrawal":"ek bada kharch","income_drop":"aana kam ho gaya"}
def change_alert(kind, trigger, reanalyses):
    tl=TRIGGER_LABEL.get(trigger.get("type"),"kuch badla")
    h=f"Kuch badla: {tl}. Dekhta hoon tera kya plan chal raha hai."
    for o in reanalyses:
        if o.get("new_outcome")=="feasible":
            h+=f"  {o['goal_id']} abhi bhi theek hai."
        else:
            h+=f"  {o['goal_id']} abhi at risk hai — {o.get('challenge','')}"
    return h

def pending_note(status):
    if status=="analysis_pending":
        return "Aaj nahi bol paunga — meri limit khatam ho gayi. Kal poochh lena, koi jaldi nahi hai."
    return ""
