"""J1 ingestion: schema validation, consent tags, quarantine. Zero silent drops."""
import re
from dataclasses import dataclass, asdict
from typing import List, Dict, Tuple
REQUIRED_TXN = ["id","date","amount","merchant","category","channel"]
REQUIRED_ACCT = ["balance"]

@dataclass
class RawTransaction:
    id: str; date: str; amount: float; merchant: str; category: str; channel: str
    consent_scope: List[str]; data_class: str = "observed_data"; note: str = ""
    meta: Dict = None

@dataclass
class RawAccountSnapshot:
    name: str; balance: float; consent_scope: List[str]; meta: Dict = None

def validate_txn(d: Dict) -> Tuple[bool,str]:
    for f in REQUIRED_TXN:
        if f not in d: return False, f"missing:{f}"
    try: float(d["amount"])
    except: return False, "bad:amount"
    if not str(d["merchant"]): return False, "bad:merchant"
    return True, "ok"

class Quarantine:
    """Quarantine is a security boundary, not a list. Records land here with a reason code and
    stay unreadable without an explicit grant. Anchor 1 J1 security test: 'quarantine queue
    access-controlled'."""
    def __init__(self): self._items=[]; self._grants=set()
    def put(self,record,reason):
        item={"record":record,"reason":reason,"quarantined_at":f"q{len(self._items)+1:03d}"}
        self._items.append(item); return item
    def grant(self,principal):
        self._grants.add(principal); return principal
    def revoke(self,principal): self._grants.discard(principal)
    def reason_codes(self): return sorted({i["reason"].split(":")[0] for i in self._items})
    def count(self): return len(self._items)
    def read(self,principal):
        if principal not in self._grants:
            raise PermissionError(f"principal {principal!r} may not read the quarantine queue")
        return [dict(i) for i in self._items]
    def read_one(self,principal,quarantined_at):
        if principal not in self._grants:
            raise PermissionError(f"principal {principal!r} may not read the quarantine queue")
        for i in self._items:
            if i["quarantined_at"]==quarantined_at: return dict(i)
        raise KeyError(quarantined_at)

def ingest(feed_txns: List[Dict], feed_accts: Dict, consent_scope: List[str],
           quarantine: "Quarantine"=None):
    """Returns (txns, accts, quarantine, audit). Every record tagged; zero silent drops."""
    Q=quarantine if quarantine is not None else Quarantine()
    txns=[]; audit=[]
    for d in feed_txns:
        ok, reason = validate_txn(d)
        if not ok:
            Q.put(d,reason)
            audit.append({"event":"ingest.transaction.quarantined","reason":reason})
            continue
        cur=d.get("currency")
        if cur is not None and not re.fullmatch(r"[A-Z]{3}",str(cur)):
            Q.put(d,f"bad:currency:{cur}")
            audit.append({"event":"ingest.transaction.quarantined","reason":"bad:currency"})
            continue
        txns.append(RawTransaction(d["id"],d["date"],float(d["amount"]),str(d["merchant"]),
            str(d["category"]),str(d["channel"]),consent_scope,"observed_data",d.get("note",""),
            {"currency":cur} if cur else None))
        audit.append({"event":"ingest.transaction.received","id":d["id"]})
    accts = {}
    for k,v in feed_accts.items():
        bal = v.get("balance") if isinstance(v,dict) else v
        if bal is None:
            Q.put({k:v},"missing:balance")
            audit.append({"event":"ingest.account.quarantined","account":k})
            continue
        accts[k]=RawAccountSnapshot(k,float(bal),consent_scope,v if isinstance(v,dict) else {})
        audit.append({"event":"ingest.account.received","account":k})
    return txns, accts, Q, audit
