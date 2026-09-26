"""Server-side conversation store.

The chat is the product, so the transcript is persisted rather than left in browser
sessionStorage: it survives a reload, a new tab and a different device, and it is what the
separate "stored data" page reads from.

Append-only. Every turn records which module produced it, so the transcript doubles as a
readable audit trail of the decision path.
"""
import json, os, itertools

class ChatLog:
    def __init__(self, path="chat_log.jsonl", session="cust_opaque_7f3a"):
        self.path=path; self.session=session
        if not os.path.exists(path): open(path,"w").close()
        self._n=itertools.count(1)
    def _read(self):
        out=[]
        for line in open(self.path):
            line=line.strip()
            if line: out.append(json.loads(line))
        return out
    def add(self, role, text, meta=None):
        rec={"seq":next(self._n),"session":self.session,"role":role,"text":text,
             "at":f"2026-09-26T10:{len(self._read())%60:02d}:00Z"}
        if meta: rec["meta"]=meta
        with open(self.path,"a") as f: f.write(json.dumps(rec)+"\n")
        return rec
    def turns(self, session=None):
        s=session or self.session
        return [r for r in self._read() if r.get("session")==s]
    def clear(self, session=None):
        s=session or self.session
        keep=[r for r in self._read() if r.get("session")!=s]
        with open(self.path,"w") as f:
            for r in keep: f.write(json.dumps(r)+"\n")
    def count(self, session=None): return len(self.turns(session))
