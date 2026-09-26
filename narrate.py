"""Friend-voice narration in English. Every number is read from engine output, never invented.
No LLM here on purpose: instant, offline, and structurally incapable of hallucinating a figure."""
import json

def _inr(n):
    n=float(n)
    if n>=10000000: return f"Rs {n/10000000:.2f} Cr"
    if n>=100000: return f"Rs {n/100000:.2f} L"
    return f"Rs {int(n):,}"

OBJ_LABEL={
 "travel":"a trip","asset":"a big purchase","protection":"protecting your family",
 "liquidity":"keeping money aside","wealth":"growing your money","debt":"clearing a loan",
 "unknown":"unclear",
}
MECH_LABEL={
 "savings goal":"a savings goal","insurance+reserve":"insurance plus a small reserve",
 "liquid reserve":"savings alone","investment allocation":"an investment plan",
 "EMI":"a loan/EMI plan","auto loan":"a car loan","cash purchase":"paying cash",
 "downpayment+mortgage":"a down payment plus mortgage",
 "refinance/repay":"refinancing or repaying",
}

def greeting(hour=None,streak=0):
    h=hour if hour is not None else 12
    part="Good morning" if h<12 else ("Good afternoon" if h<17 else "Good evening")
    s=f"{part}. Let's go through it."
    if streak>0: s+=f" {streak}-day streak going."
    else: s+=" First time you're saying this out loud, that's fine."
    return s

def smalltalk(text, streak=0):
    t=(text or "").strip().lower()
    if any(w in t for w in ("thanks","thank you","shukriya")):
        return "Any time. I'm here whenever the money question comes up."
    if any(w in t for w in ("bye","bye ")):
        return "Take care. Your goals are saved, and I'll flag it if anything changes."
    if any(w in t for w in ("how are you","kaise ho","kya haal","sup","what's up","whats up")):
        return ("I'm good — I spend my time checking your numbers so you don't have to. "
                "What's on your mind today?")
    return ("Hello. Tell me anything about money — a goal, a worry, a bill you weren't "
            "expecting. One line is enough to start.")

def clarify(intent):
    return intent.get("clarify","Tell me a bit more and we'll work it out.")

def objective(intent):
    lbl=OBJ_LABEL.get(intent["objective_category"],intent["objective_category"])
    amt=intent.get("amount"); h=intent.get("horizon_mo",12)
    if amt: return f"What I heard: {lbl} — {_inr(amt)}, over {h} month{'s' if h!=1 else ''}."
    return f"What I heard: {lbl}. The amount and timing aren't clear yet."

def evidence(snapshot, behaviour, results, soul=None):
    leaks=behaviour.get("top_leaks") or []
    joy=behaviour.get("joy",0)
    lines=[f"Average monthly income: {_inr(snapshot.income_monthly_avg)}.",
           f"Cash in hand right now: {_inr(snapshot.balances.get('savings',0))}."]
    mf=snapshot.balances.get("mf",0); fd=snapshot.balances.get("fd",0)
    if mf or fd:
        lines.append(f"Parked and invested: {_inr(mf+fd)} (mutual funds {_inr(mf)}, fixed deposits {_inr(fd)}).")
    if soul:
        fam=[f for f in (soul.get("household") or soul.get("family") or []) if f]
        if fam: lines.append("Household commitments: "+", ".join(fam)+".")
        goals=[g["name"] for g in soul.get("goals",[]) if g.get("name")]
        if goals: lines.append("Goals on your mind: "+", ".join(goals)+".")
    if leaks:
        top=leaks[0]
        lines.append(f"Leakage over 3 months: {_inr(top['total'])} ({top['count']} orders at {top['merchant'].split('/')[0]}).")
    if joy and joy<20000:
        lines.append(f"Spend on yourself: only {_inr(joy)}. You are being tighter than you need to be.")
    r=results[0]
    lines.append(f"Emergency runway: {r['emergency_mo']} months.")
    if r.get("stress_applied"):
        lines.append(f"Worst income month: {_inr(r['income_worst_used'])} (average {_inr(r['income_avg_used'])}).")
    return lines

def verdict(result, snapshot, challenge=None):
    o=result["outcome"]
    need=_inr(result["monthly_need"])
    stress=result.get("stress_applied")
    limit=result.get("avail_stress_monthly",result["avail_monthly"])
    if o=="feasible":
        if stress:
            body=(f"You need {need} a month. Your income is seasonal, so I ran the numbers against "
                  f"your worst month ({_inr(result['income_worst_used'])}) rather than your average "
                  f"({_inr(result['income_avg_used'])}). Even then {_inr(limit)} is free each month. "
                  f"Emergency cover is {result['emergency_mo']} months. This plan works.")
        else:
            body=(f"You need {need} a month and {_inr(limit)} is free each month. "
                  f"Emergency cover is {result['emergency_mo']} months. This plan works.")
        return "GO AHEAD", body
    if o=="gap":
        return "NOT POSSIBLE AS IT STANDS", (challenge or
                (f"You need {need} a month but the comfortable limit is {_inr(limit)}. "
                 f"That leaves a {_inr(result['gap_amount'])} shortfall every month."))
    return "THAT'S THE WRONG TOOL", (challenge or
            "Savings alone cannot cover a large medical shock, so this needs a different route.")

def alternatives(alts):
    """J7 already authors these in plain language; do not re-translate."""
    return [a["description"] for a in alts]

def decision_options():
    return [
      {"id":"accept","label":"Yes, lock it in","hint":"This goes into my memory as your plan"},
      {"id":"modify","label":"Change the numbers","hint":"Set your own amount, timeline or method"},
      {"id":"reject","label":"Not right now","hint":"Close this off, but I'll remember it"},
    ]

def confirmation(goal):
    return (f"Done. {goal['goal_id']} is locked: {OBJ_LABEL.get(goal['objective'],goal['objective'])}, "
            f"{MECH_LABEL.get(goal['mechanism'],goal['mechanism'])} — {_inr(goal['target'])} "
            f"over {goal['timeline']} months. I'll hold on to it and tell you if anything changes.")

def memory_line(rec):
    if rec.get("tombstone"): return f"{rec['goal_id']} — removed (consent change)."
    return (f"{rec['goal_id']}: {OBJ_LABEL.get(rec['objective'],rec['objective'])} | "
            f"{MECH_LABEL.get(rec['mechanism'],rec['mechanism'])} — {_inr(rec['target'])} / {rec['timeline']}mo "
            f"[{rec['state_version']}]")

TRIGGER_LABEL={"large_withdrawal":"a large withdrawal","income_drop":"your income dropped"}
def change_alert(kind, trigger, reanalyses):
    tl=TRIGGER_LABEL.get(trigger.get("type"),"something changed")
    h=f"I noticed {tl}. Let me re-check which of your plans still hold."
    for o in reanalyses:
        if o.get("new_outcome")=="feasible": h+=f" {o['goal_id']} is still fine."
        else: h+=f" {o['goal_id']} is now at risk — {o.get('challenge','')}"
    return h

def pending_note(status):
    if status=="analysis_pending":
        return "My calculation engine isn't available right now, so I'm not going to guess. Ask me again in a moment."
    return ""
