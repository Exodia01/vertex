"""J4 intent extraction. Output always ai_hypothesis. Low conf -> clarifying question."""
import re
RULES=[
 ("travel",["japan","dubai","trip","flight","lounge","vacation","holiday"]),
 ("asset",["car","house","bike","flat"]),
 ("protection",["medical","emergency","parents","insurance","health","protect","surgery","hospital","treatment"]),
 ("liquidity",["save","saving","reserve","emergency fund"]),
 ("wealth",["invest","sip","wealth","mutual"]),
 ("debt",["loan","emi","debt","refinance"]),
]
MONTH_WORDS=("month","months","mo","yr","year","years","%","percent")
NUM=re.compile(r"(?:₹\s*|rs\.?\s*)?(\d+(?:\.\d+)?)\s*(l|lakh|lakhs|cr|crores?)?\b", re.I)
NEXT_WORD=re.compile(r"\s*([A-Za-z%]+)")
def _next_word(text,pos):
    m=NEXT_WORD.match(text,pos)
    return m.group(1).lower() if m else ""
def _extract_amount(text):
    for m in NUM.finditer(text):
        if _next_word(text,m.end()) in MONTH_WORDS: continue
        unit=(m.group(2) or "").lower()
        val=float(m.group(1))
        if unit in ("l","lakh","lakhs"): return int(val*100000)
        if unit.startswith("cr"): return int(val*10000000)
        token=m.group(0).strip().lower()
        if token.startswith("₹") or token.startswith("rs"): return int(val)
    return None

STATED=[
 ("savings",["save","saving","bacha","bachao","jama","jamao","rakho","side me","reserve"]),
 ("insurance",["insurance","bima","cover","policy"]),
 ("loan",["loan","emi","borrow","udhaar"]),
 ("investment",["sip","invest","mutual","mf","share"]),
]
# A funding instrument explains the purchase of something else; it is never the goal itself.
FUNDING_MECHANISMS={"loan"}
DEBT_GOAL_VERBS=["pay off","payoff","close","clear","settle","reduce","beset"]
# Goal-type mechanisms imply the objective they belong to.
MECH_OBJECTIVE={"savings":"liquidity","insurance":"protection","investment":"wealth","loan":"debt"}

def _stated_candidates(t):
    out=[]
    for mech,keys in STATED:
        if any(k in t for k in keys): out.append(mech)
    return out

MEANS_RE=re.compile(r"\b(save|saving|bacha|invest|sip|mutual|insurance|bima|reserve|side)\b[^.]{0,25}?\bfor\b")

def _resolve_objective(t,hits):
    """Decide the objective without guessing. Returns (objective, confidence_bonus, contradiction).

    The hard part is that the same word can be a goal or the means to a goal:
      'save 3L for medical'  -> 'save' is the MEANS (it is followed by 'for'); goal = protection.
      'start a SIP'          -> no purpose clause, so the mechanism IS the goal = wealth.
      '15L car on EMI'       -> 'EMI' is FUNDING; the goal is the asset.
      'pay off my loan'      -> 'loan' IS the goal, and it competes with the car for the same cash.
    """
    cands=_stated_candidates(t)
    if not cands: return None,0,False
    debt_goal=any(v in t for v in DEBT_GOAL_VERBS)

    funding=[m for m in cands if m in FUNDING_MECHANISMS]
    if funding and "asset" in hits and not debt_goal: return "asset",0,False
    if debt_goal and len(hits)>1:
        top=sorted(hits.values(),reverse=True)
        if top[0]-top[1]<2: return "debt",0,True
        return "debt",0,False

    # A mechanism followed by a purpose clause is the means, not the goal. The purpose clause
    # itself names the goal. Longest-key wins so 'emergency fund' (liquidity) beats the
    # substring 'emergency' (protection).
    if MEANS_RE.search(t):
        purpose=t.split("for",1)[1] if "for" in t else ""
        best=None; best_len=0
        for o,keys in RULES:
            for k in keys:
                if k in purpose and len(k)>best_len:
                    best, best_len = o, len(k)
        if best: return best,0,False

    for m in reversed(cands):
        obj=MECH_OBJECTIVE.get(m)
        if obj in hits: return obj,0,False
    return None,0,False

def _stated_mechanism(t):
    cands=_stated_candidates(t)
    if not cands: return None
    return cands[0]

CONTRADICTION_MARKERS=[r"but also",r"but i also",r"and also",r"at the same time",
                       r"as well as",r"or maybe",r"confused",r"not sure which",r"either",r"or"]
CLARIFY_CONTRADICT=("Suna main ne do cheezein ek saath — tumhe pehle kaun si sortani hai? "
                    "Ek line me batao, phir main dusri par bhi usi hisaab se sochta hun.")
_MARKER_RE=re.compile(r"\b(?:"+"|".join(CONTRADICTION_MARKERS)+r")\b")

def _detect_contradiction(t,hits,stated_for_objective):
    """A genuine ambiguity, not a keyword-count guess.

    Two objectives of equal strength mean we must ask rather than pick - unless a stated
    GOAL mechanism resolves the tie (a named goal mechanism tells us which objective is meant).
    """
    if len(hits)<2: return False
    top=sorted(hits.values(),reverse=True)
    if top[0]-top[1]>=2: return False          # one objective clearly dominates
    if stated_for_objective is not None: return False
    return True

def extract_intent(text: str):
    t=text.lower(); hits={}
    for obj,keys in RULES:
        s=sum(1 for k in keys if k in t)
        if s: hits[obj]=s
    amt=_extract_amount(text)
    tm=re.search(r"(\d+)\s*(?:mo|month)",t)
    horizon=int(tm.group(1)) if tm else 12
    stated=_stated_mechanism(t)
    if not hits:
        return {"objective_category":"unknown","confidence":0.0,"amount":amt,"horizon_mo":horizon,
                "stated_mechanism":stated,
                "data_class":"ai_hypothesis","clarify":"Aap kya chahte ho — travel, car/house, medical safety, saving ya loan? Ek line me batao."}
    resolved,bonus,contra=_resolve_objective(t,hits)
    best=max(hits,key=hits.get); conf=min(0.95,0.5+0.2*hits[best]+bonus)
    if resolved in hits: best=resolved
    out={"objective_category":best,"confidence":round(conf,2),"amount":amt,"horizon_mo":horizon,
         "stated_mechanism":stated,"data_class":"ai_hypothesis","alternatives_considered":sorted(hits)}
    if contra or (len(hits)>1 and _MARKER_RE.search(t)):
        out["objective_category"]="contradictory"
        out["confidence"]=0.0
        out["clarify"]=CLARIFY_CONTRADICT
        out["data_class"]="ai_hypothesis"
        return out
    if conf<0.6: out["clarify"]="Thoda aur batao — kitna paisa, kab tak? (e.g. Dubai 1.2L Dec)"
    return out
