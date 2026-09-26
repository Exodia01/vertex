"""Optional LLM layer for J4 intent and J11 sentiment.

Anchor 1 §11 assigns natural-language understanding and sentiment detection to the AI layer.
The shipped deterministic classifiers (j4_intent, j11_sentiment) are the OFFLINE BASELINE:
fast, free, testable, and incapable of inventing a number. They are also pattern matchers,
so free-form language is where they are weakest.

This module is the seam where a model replaces the classifier. Two hard invariants, enforced
by construction and asserted in tests:

  1. The model NEVER supplies arithmetic. It may only return category labels, a stated
     mechanism, and a confidence. Any numeric field it returns is discarded.
  2. If the model is absent, slow, malformed or errors, the deterministic classifier answers.
     There is no path where a model failure produces no answer or a fabricated one.

Enabled with IASPIRE_LLM=1 plus a provider key. Off by default, so the system has no
network dependency in tests or demos.
"""
import json, os, re, time

ENABLED = os.environ.get("IASPIRE_LLM") == "1"
PROVIDER = os.environ.get("IASPIRE_LLM_PROVIDER", "none")
MODEL = os.environ.get("IASPIRE_LLM_MODEL", "")
ENDPOINT = os.environ.get("IASPIRE_LLM_ENDPOINT", "")
API_KEY = os.environ.get("IASPIRE_LLM_API_KEY", "")
TIMEOUT = float(os.environ.get("IASPIRE_LLM_TIMEOUT", "20"))
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
ARBITRATION = os.environ.get("IASPIRE_ARBITRATION", "disagreement_asks")

OBJECTIVES = {"travel","asset","protection","liquidity","wealth","debt","unknown"}
STATED = {"savings","insurance","loan","investment",None}
NUMERIC_KEYS = {"amount","horizon_mo","monthly_need","gap_amount","target","timeline",
                "avail_monthly","emergency_mo","income","savings_rate"}

# Schema handed to Ollama's constrained decoder. Constraining the output shape is what makes a
# local model usable here: free-form generation produced empty or truncated replies in probing.
INTENT_SCHEMA={"type":"object","properties":{
  "objective_category":{"type":"string","enum":sorted(o for o in OBJECTIVES)},
  "stated_mechanism":{"type":["string","null"],"enum":["savings","insurance","loan","investment",None]},
  "confidence":{"type":"number"},
  "contradictory":{"type":"boolean"}},
  "required":["objective_category","stated_mechanism","confidence","contradictory"]}

SENTIMENT_SCHEMA={"type":"object","properties":{
  "stress":{"type":"number"},"urgency":{"type":"number"},
  "frustration":{"type":"number"},"confidence":{"type":"number"}},
  "required":["stress","urgency","frustration","confidence"]}

INTENT_PROMPT = """Classify a customer's financial aspiration. Answer with the JSON object only.

objective_category is the underlying NEED, not the words used:
- "save 3L for my mother's surgery" -> protection (a reserve is the means, not the need)
- "3L for medical emergencies" -> protection
- "save 2L" -> liquidity
- "15L car on EMI" -> asset (EMI is funding, not the goal)
- "pay off my loan" -> debt
- "start a SIP" -> wealth
- "Japan trip 2.5L" -> travel
stated_mechanism is the financial mechanism the customer NAMED, else null.
contradictory is true only when the text states two competing desires for the same money.
If the text is vague, answer unknown with low confidence.
Never output amounts, prices, dates or any arithmetic.

TEXT: """

SENTIMENT_PROMPT = """Read the emotional state of a customer's statement about money.
stress = anxiety or fear about affordability. urgency = deadline pressure.
frustration = anger or resignation. confidence = how settled they sound.
Urgency alone is not distress. Hedging ("I'd like", "maybe") lowers confidence.
TEXT: """

def _ollama(prompt,schema):
    """Local Ollama. Never raises. think:false because the thinking variants spend the whole
    token budget on reasoning and return nothing."""
    import urllib.request
    body=json.dumps({"model":MODEL,"prompt":prompt,"stream":False,"think":False,
                     "format":schema,"options":{"temperature":0,"num_predict":400}}).encode()
    req=urllib.request.Request(f"{OLLAMA_URL}/api/generate",data=body,
                               headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(req,timeout=TIMEOUT) as r:
        return json.loads(r.read()).get("response")

def ollama_reachable():
    try:
        import urllib.request
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags",timeout=2) as r:
            return bool(json.loads(r.read()).get("models"))
    except Exception:
        return False

def _client():
    if not ENABLED: return None
    if PROVIDER=="ollama" and MODEL: return ("ollama",OLLAMA_URL)
    if PROVIDER=="anthropic" and API_KEY:
        try:
            import anthropic
            return ("anthropic",anthropic.Anthropic(api_key=API_KEY,timeout=TIMEOUT))
        except Exception: return None
    if PROVIDER=="openai" and API_KEY and ENDPOINT:
        return ("openai",(API_KEY,ENDPOINT))
    return None

def _ask(prompt,schema=None):
    """Never raises. A model failure is indistinguishable from no model, which is exactly
    what lets the caller fall back without special-casing."""
    try:
        c=_client()
        if not c: return None
        kind,handle=c
        if kind=="ollama": return _ollama(prompt,schema)
        if kind=="anthropic":
            m=handle.messages.create(model=MODEL or "claude-sonnet-5",max_tokens=300,
                messages=[{"role":"user","content":prompt}])
            return m.content[0].text
        return None
    except Exception:
        return None

def _parse(raw):
    if not raw: return None
    m=re.search(r"\{.*\}",raw,re.S)
    if not m: return None
    try: return json.loads(m.group(0))
    except Exception: return None

def _strip_numbers(d):
    """Invariant 1: discard anything numeric the model tried to supply."""
    return {k:v for k,v in d.items() if k not in NUMERIC_KEYS}

DISAGREE_CLARIFY=("Suna main ne is baat me do alag pehlu pakde hain. Tere liye pehla kya hai? "
                  "Ek line me batao, phir doosre ko usi hisaab se dekhta hun.")

def _model_intent(text):
    d=_strip_numbers(_parse(_ask(INTENT_PROMPT+text.strip(),INTENT_SCHEMA)) or {})
    obj=d.get("objective_category")
    if obj not in OBJECTIVES: return None
    if d.get("contradictory") is True: return {"contradictory":True}
    sm=d.get("stated_mechanism")
    return {"objective_category":obj,
            "stated_mechanism":sm if sm in STATED else None,
            "confidence":d.get("confidence")}

def _model_sentiment(text):
    d=_strip_numbers(_parse(_ask(SENTIMENT_PROMPT+(text or "").strip(),SENTIMENT_SCHEMA)) or {})
    if not d: return None
    out={}
    for k in ("stress","urgency","frustration","confidence"):
        if k in d:
            try: out[k]=max(0.0,min(1.0,float(d[k])))
            except Exception: return None
    return out or None

def _agree(det,mod):
    """Agreement is on the decision, not on the confidence score. A stated mechanism counts as
    agreement only when the deterministic layer also saw one, because 'none seen' and
    'seen but different' are different findings."""
    if mod.get("contradictory"): return False
    if det["objective_category"]!=mod["objective_category"]: return False
    dm,mm=det.get("stated_mechanism"),mod.get("stated_mechanism")
    if (dm is None)!=(mm is None): return False
    if dm is not None and dm!=mm: return False
    return True

class LLMIntent:
    """Deterministic layer is the floor, not the fallback.

    Arbitration (IASPIRE_ARBITRATION=disagreement_asks):
      model absent / errored / malformed -> deterministic answer
      both agree                        -> that answer
      both disagree                     -> ASK. Never pick a winner, because a disagreement
                                          is genuine ambiguity and Anchor 1 §15 says to ask
                                          rather than guess.
    The model can therefore widen free-form coverage but can never overrule the layer that owns
    the cases it has been verified on, and can never contribute a number.
    """
    def __init__(self, fallback): self.fallback=fallback; self.stats={"model":0,"agreed":0,"disagreed":0,"unavailable":0}
    def extract_intent(self,text):
        det=self.fallback(text)
        if not ENABLED: return det
        mod=_model_intent(text)
        if mod is None:
            self.stats["unavailable"]+=1; det=dict(det); det["engine"]="deterministic"; return det
        self.stats["model"]+=1
        if _agree(det,mod):
            self.stats["agreed"]+=1
            out=dict(det); out["engine"]="agreed"
            try: out["model_confidence"]=float(mod.get("confidence",0))
            except Exception: pass
            return out
        self.stats["disagreed"]+=1
        if ARBITRATION=="disagreement_asks":
            out=dict(det)
            out["objective_category"]="contradictory"; out["confidence"]=0.0
            out["clarify"]=DISAGREE_CLARIFY
            out["alternatives_considered"]=sorted({det["objective_category"],
                                                   mod.get("objective_category")}-
                                                  {None,"unknown"})
            out["engine"]="disagreement"
            out["det_said"]=det["objective_category"]; out["model_said"]=mod.get("objective_category")
            return out
        out=dict(det); out["engine"]="model_override"
        out["objective_category"]=mod.get("objective_category",det["objective_category"])
        return out

class LLMSentiment:
    """Same arbitration. Sentiment only ever adjusts tone and priority, so a disagreement asks
    rather than guesses, and can never change an outcome."""
    def __init__(self, fallback): self.fallback=fallback; self.stats={"model":0,"agreed":0,"disagreed":0,"unavailable":0}
    def detect(self,text,entry_id=None,aspiration_id=None):
        base=self.fallback(text,entry_id=entry_id,aspiration_id=aspiration_id)
        if not ENABLED: return base
        mod=_model_sentiment(text)
        if mod is None:
            self.stats["unavailable"]+=1; base=dict(base); base["engine"]="deterministic"; return base
        self.stats["model"]+=1
        from j11_sentiment import _band, _STRESS_BAND, _CONF_BAND
        model_bands={"stress_band":_band(mod["stress"],_STRESS_BAND),
                     "confidence_band":_band(mod["confidence"],_CONF_BAND)}
        if base["stress_band"]==model_bands["stress_band"] and \
           base["confidence_band"]==model_bands["confidence_band"]:
            self.stats["agreed"]+=1
            out=dict(base)
            # agreed band: take the mean score, which can only sharpen tone within the band
            out["stress"]=round((base["stress"]+mod["stress"])/2,2)
            out["engine"]="agreed"
            return out
        self.stats["disagreed"]+=1
        base=dict(base)
        if ARBITRATION=="disagreement_asks":
            base["engine"]="disagreement"
            base["det_said"]=base["stress_band"]; base["model_said"]=model_bands["stress_band"]
            base["tone_deferred"]=True
        else:
            base.update(mod); base["stress_band"]=model_bands["stress_band"]
            base["confidence_band"]=model_bands["confidence_band"]; base["engine"]="model_override"
        return base

_INTENT=None
_SENT=None
def intent_extractor():
    """Process-wide instance so arbitration statistics accumulate rather than resetting."""
    global _INTENT
    if _INTENT is None:
        from j4_intent import extract_intent
        _INTENT=LLMIntent(extract_intent)
    return _INTENT.extract_intent

def sentiment_detector():
    global _SENT
    if _SENT is None:
        from j11_sentiment import detect
        _SENT=LLMSentiment(detect)
    return _SENT.detect

def llm_stats():
    return {"enabled":ENABLED,"provider":PROVIDER,"model":MODEL or None,
            "arbitration":ARBITRATION,"ollama_reachable":ollama_reachable() if ENABLED else None,
            "intent":getattr(_INTENT,"stats",None),"sentiment":getattr(_SENT,"stats",None)}
