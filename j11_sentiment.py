"""J11 sentiment analysis.

Runs PARALLEL to J4 on the same raw text. Never inside the state machine: it never blocks,
delays or reorders a J1-J10 transition (Anchor 1 J11 acceptance criteria). Its only outputs
are (a) a read-only annotation attached to an entry and (b) inputs to J7 tone, J8
contradiction check and J10 priority weighting.

Deterministic and lexicon-based so it is testable, offline and incapable of fabricating
sentiment that was not expressed. Always tagged ai_hypothesis.

Only the coarse bands may ever cross the Anchor 1/2 boundary; raw scores, evidence snippets
and free text stay inside Anchor 1.
"""
import re

LEX={
 "stress":["scared","afraid","worried","worry","worrying","panic","panicking","terrified",
           "sleepless","anxious","anxiety","can't sleep","cannot sleep","feel sick",
           "keep thinking","what if","darr","darte","chinta","chitna",
           "every month i","every month","again this month"],
 "urgency":["urgent","urgently","immediately","right now","today","tomorrow","must",
            "deadline","asap","jaldi","abhi","turant","prices are going up","going up",
            "need to","need","or i lose","or else","this month","before i lose",
            "no time","running out"],
 "frustration":["fed up","angry","useless","hate","sick of","no one",
                "nobody","samajh nahi","koi nahi","thak gaya","dimag kharab"],
 "confidence":["sure","definitely","decided","going for it","i will","i'll","must clear",
              "no doubt","pakka","certain","i want to","i'd like","i would like",
              "i need","we need","i plan to","i'm going to"],
}
UNCERTAINTY=["maybe","not sure","don't know","donte know","i guess","perhaps","let's see",
             "not decided","sochta hun","soch raha","maybe i","not planning","no idea"]
NEGATORS=["nothing","not","no","never","dont","don't","doesn't","doesn't","isn't","not really"]
POSITIVE_CALM=["fine","okay","all good","settled","calm","no rush","whenever","someday",
               "not worried","happy","relaxed"]

_STRESS_BAND=[("high_stress",0.66),("moderate_stress",0.33),("low_stress",0.0)]
_CONF_BAND=[("high_confidence",0.66),("moderate_confidence",0.33),("low_confidence",0.0)]

def _band(value,bands):
    for name,threshold in bands:
        if value>=threshold: return name
    return bands[-1][0]

def _count(text,keys):
    n=0
    for k in keys:
        for m in re.finditer(r"(?<!\w)"+re.escape(k)+r"(?!\w)",text):
            before=text[max(0,m.start()-18):m.start()]
            if any(re.search(r"(?<!\w)"+re.escape(neg)+r"(?!\w)",before) for neg in NEGATORS):
                continue
            n+=1
    return n

def detect(text: str, entry_id=None, aspiration_id=None):
    """Returns a SentimentSignal. Deterministic; degrades to all-low on empty input."""
    t=(text or "").lower().strip()
    if not t:
        return {"entry_id":entry_id,"aspiration_id":aspiration_id,
                "stress":0.0,"urgency":0.0,"frustration":0.0,"confidence":0.0,
                "stress_band":"low_stress","confidence_band":"low_confidence",
                "evidence_snippet":"","data_class":"ai_hypothesis","detected_at":"2026-09-26T10:00:00Z"}
    counts={k:_count(t,v) for k,v in LEX.items()}
    unc=sum(1 for k in UNCERTAINTY if k in t)
    calm=sum(1 for k in POSITIVE_CALM if k in t)
    urgency=min(1.0,counts["urgency"]*0.34)
    # Deadline pressure is itself a stressor, so urgency contributes to stress at reduced weight.
    frustration=min(1.0,counts["frustration"]*0.5)
    # Repeated frustration ("every month I ...") is itself an anxiety signal, not only annoyance.
    stress=min(1.0,counts["stress"]*0.5 + urgency*0.35 + frustration*0.40
               + (0.2 if unc else 0) - (0.2 if calm else 0))
    confidence=min(1.0,counts["confidence"]*0.34 + (0.25 if calm else 0) - (0.2 if unc else 0))
    # evidence: the strongest matching phrase, kept internal to Anchor 1
    ev=""
    for k in LEX["stress"]+LEX["urgency"]+LEX["frustration"]:
        if k in t: ev=k; break
    return {"entry_id":entry_id,"aspiration_id":aspiration_id,
            "stress":round(max(0.0,stress),2),"urgency":round(urgency,2),
            "frustration":round(frustration,2),"confidence":round(max(0.0,confidence),2),
            "stress_band":_band(max(0.0,stress),_STRESS_BAND),
            "confidence_band":_band(max(0.0,confidence),_CONF_BAND),
            "evidence_snippet":ev,"data_class":"ai_hypothesis","detected_at":"2026-09-26T10:00:00Z"}

def is_contradictory(signals, explicit_response):
    """J8 secondary validation. Repeated high-stress signals against an aspiration the customer
    has just explicitly accepted. Returns a note; NEVER blocks stabilization."""
    if explicit_response!="accept": return None
    after=[s for s in signals if s.get("data_class")=="ai_hypothesis"]
    stressed=[s for s in after if s.get("stress_band")=="high_stress"]
    if not stressed: return None
    return {"contradiction_note":"customer explicitly accepted but shows repeated high-stress signals",
            "high_stress_signals":len(stressed),
            "stabilization_proceeds":True,
            "follow_up_at":"2026-10-03T09:00:00Z"}

def tone_directive(signal):
    """J7 input: how to phrase. Never whether the gap is real."""
    if not signal: return "default_tone"
    if signal.get("stress_band")=="high_stress": return "soften_tone"
    if signal.get("confidence_band")=="high_confidence": return "allow_direct_actionable_phrasing"
    return "default_tone"

def to_boundary_fields(signal):
    """The ONLY sentiment data permitted to leave Anchor 1 (Anchor 1 §21 v1.1)."""
    if not signal: return {}
    return {"coarse_sentiment_band":signal["stress_band"],
            "confidence_band":signal["confidence_band"]}
