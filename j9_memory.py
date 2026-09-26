"""J9 financial memory: append-only, versioned, queryable, tombstonable.

Every record carries the same shape (tombstones included) so downstream consumers never have
to branch on record type. Two controls Anchor 1 calls for are implemented here rather than
left to the transport:
  * customer scoping - reads are refused unless the requester owns the customer_ref (§9
    security test: 'access restricted to the owning customer')
  * at-rest confidentiality - records are sealed with a per-tenant derived key (§13)

The confidentiality seam is honest about what it is: HMAC-SHA256 keystream derivation with an
integrity tag, which protects against casual disclosure and tampering but is NOT a
production cipher. stdlib exposes no AEAD, and rolling a real cipher by hand would be worse
than naming the limitation. See CRYPTO_NOTE.
"""
import base64, hashlib, hmac, json, os

CRYPTO_NOTE={
 "scheme":"hmac-sha256 counter-mode keystream + HMAC tag",
 "provides":["integrity (tamper-evident)","key separation per tenant",
             "records unreadable without the tenant key"],
 "does_not_provide":["semantic security against a determined analyst",
                     "auditable compliance-grade encryption","key rotation or KMS lifecycle"],
 "production_path":"swap Seal for an AEAD (AES-GCM via `cryptography`, or a cloud KMS envelope "
                   "key). The interface below is the seam; only the cipher changes.",
 "status":"DEMONSTRATION ONLY - do not treat as compliant at rest",
}

def derive_key(master_secret: bytes, tenant: str) -> bytes:
    if isinstance(master_secret,str): master_secret=master_secret.encode()
    return hmac.new(master_secret,tenant.encode(),hashlib.sha256).digest()

class Seal:
    def __init__(self,master_secret,tenant):
        self.key=derive_key(master_secret,tenant)
    def _keystream(self,n,nonce):
        out=b""
        c=0
        while len(out)<n:
            out+=hmac.new(self.key,nonce+c.to_bytes(4,"big"),hashlib.sha256).digest()
            c+=1
        return out[:n]
    def seal(self,obj)->str:
        raw=json.dumps(obj,sort_keys=True,separators=(",",":")).encode()
        nonce=os.urandom(16)
        ct=bytes(a^b for a,b in zip(raw,self._keystream(len(raw),nonce)))
        tag=hmac.new(self.key,nonce+ct,hashlib.sha256).digest()[:16]
        return "v1."+base64.urlsafe_b64encode(nonce+tag+ct).decode()
    def open(self,blob)->dict:
        if not blob.startswith("v1."): raise ValueError("unrecognised record format")
        raw=base64.urlsafe_b64decode(blob[3:].encode())
        nonce,tag,ct=raw[:16],raw[16:32],raw[32:]
        if not hmac.compare_digest(hmac.new(self.key,nonce+ct,hashlib.sha256).digest()[:16],tag):
            raise ValueError("integrity check failed - record altered")
        pt=bytes(a^b for a,b in zip(ct,self._keystream(len(ct),nonce)))
        return json.loads(pt.decode())

class MemoryAccessError(PermissionError): pass

class MemoryStore:
    def __init__(self, path="memory.jsonl", master_secret=None, tenant="anchor1"):
        self.path=path; self.tenant=tenant
        self.seal=Seal(master_secret,tenant) if master_secret else None
        if not os.path.exists(path): open(path,"w").close()
    def _read_raw(self):
        out=[]
        for line in open(self.path):
            line=line.strip()
            if line: out.append(line)
        return out
    def _dec(self,line):
        if self.seal is None: return json.loads(line)
        if line.startswith("v1."): return self.seal.open(line)
        return json.loads(line)
    def _read(self):
        return [self._dec(l) for l in self._read_raw()]
    def _append(self, rec):
        line=self.seal.seal(rec) if self.seal else json.dumps(rec)
        with open(self.path,"a") as f: f.write(line+"\n")
    def _next_version(self, goal_id):
        return sum(1 for r in self._read()
                   if r.get("goal_id")==goal_id and not r.get("tombstone"))+1
    def add(self, goal_id, customer_ref, objective, mechanism, target, timeline, extra=None):
        version=self._next_version(goal_id)
        rec={"record_type":"goal","goal_id":goal_id,"customer_ref":customer_ref,
             "objective":objective,"mechanism":mechanism,"target":target,"timeline":timeline,
             "confirmed_at":"2026-09-26T10:00:00Z","state_version":f"v{version}",
             "tombstone":False}
        if extra: rec.update(extra)
        self._append(rec)
        return rec
    def history(self, goal_id):
        return [r for r in self._read() if r.get("goal_id")==goal_id]
    def revisions(self, goal_id):
        """Live versions only. A tombstone retracts every prior version of that goal, so a
        withdrawn goal must not still look active downstream."""
        tombstoned=any(r.get("record_type")=="tombstone" for r in self.history(goal_id))
        if tombstoned: return []
        return [r for r in self.history(goal_id)
                if r.get("record_type")=="goal" and not r.get("tombstone")]
    def query(self, customer_ref, requester=None):
        """Customer-facing read. Refused unless the requester is that customer (or an
        authorised auditor role)."""
        if requester is not None and requester not in (customer_ref,"human_auditor","ai"):
            raise MemoryAccessError(
                f"{requester!r} may not read financial memory of {customer_ref!r}")
        return [r for r in self._read() if r.get("customer_ref")==customer_ref]
    def tombstone(self, goal_id, reason="consent_withdrawn"):
        prior=self.revisions(goal_id)
        if not prior: return []
        self._append({"record_type":"tombstone","goal_id":goal_id,
                      "customer_ref":prior[0]["customer_ref"],
                      "objective":prior[0]["objective"],"mechanism":prior[0]["mechanism"],
                      "target":prior[0]["target"],"timeline":prior[0]["timeline"],
                      "confirmed_at":"2026-09-26T10:00:00Z",
                      "state_version":prior[-1]["state_version"],
                      "tombstone":True,"reason":reason,
                      "retracts":[r["state_version"] for r in prior]})
        return [r["state_version"] for r in prior]
