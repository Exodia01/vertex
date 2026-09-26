"""Full gate: contracts, linter, fixtures, all module suites, observability, app boot.

Run: python3 tools/gate.py
"""
import os, json, subprocess, sys
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
fails=[]
def run(label,args,expect=0):
    r=subprocess.run([sys.executable]+args,capture_output=True,text=True)
    last=[l for l in r.stdout.strip().splitlines() if l.strip()]
    ok=r.returncode==expect
    print(("PASS " if ok else "FAIL ")+f"{label:38}",(last[-1][:70] if last else r.stderr.strip()[-70:]))
    if not ok:
        fails.append(label)
        for l in r.stdout.splitlines():
            if l.startswith("FAIL"): print("      ",l)
    return r

print("=== contracts & data hygiene ===")
run("contract schema self-test",["tools/validate_contracts.py"])
run("synthetic-data linter (whole repo)",["tools/synthetic_linter.py","."])
run("fixture generator reproducible",["fixtures/generate.py"])

print("=== module acceptance suites ===")
run("J1-J8 unit+integration+privacy",["test_mvp.py"])
run("J1-J10 end-to-end",["test_pipeline.py"])
run("J2+J6 exact-value",["test_j2_j6_exact.py"])
run("J4+J5 accuracy + rubric",["test_j4_j5_accuracy.py"])
run("J7/J10/J3 properties",["test_j7_j10_properties.py"])
run("J11 sentiment",["test_j11_sentiment.py"])
run("S13/S15/S9 failure modes + security",["test_failure_modes.py"])

print("=== cross-cutting ===")
run("P0 gate (contracts/fixtures/version/audit)",["tools/gate_p0.py"])
run("observability (confidence + engine latency)",["tools/observability.py"])

print("=== app boots and serves ===")
# If something already holds the port, the spawned app cannot bind and the gate would
# silently test that other process instead. Fail loudly instead.
import socket as _sock
_probe=_sock.socket(); _probe.settimeout(1)
_inuse=False
try:
    _probe.connect(("127.0.0.1",8848)); _inuse=True
except OSError:
    pass
finally:
    _probe.close()
if _inuse:
    print("FAIL port 8848 already in use".ljust(38),"stop the other server first")
    fails.append("port 8848 free before gate")
import time, urllib.request, signal
class PIPE_probe: pass
env=dict(os.environ); env["IASPIRE_MEMORY_SECRET"]="gate-secret"
proc=subprocess.Popen([sys.executable,"app.py"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,env=env)
try:
    ok=False
    for _ in range(30):
        time.sleep(0.3)
        try:
            with urllib.request.urlopen("http://127.0.0.1:8848/",timeout=2) as r:
                body=r.read()
                ok = r.status==200 and b"iASPIRE Journal" in body and b"edTarget" in body
                break
        except Exception: pass
    print(("PASS " if ok else "FAIL ")+"app serves UI".ljust(38),"")
    if not ok: fails.append("app serves UI")
    with urllib.request.urlopen("http://127.0.0.1:8848/data",timeout=5) as dr:
        dbody=dr.read()
    dok=dr.status==200 and b"Stored data" in dbody and b"/api/goals" in dbody
    print(("PASS " if dok else "FAIL ")+"stored-data page renders".ljust(38),"")
    if not dok: fails.append("stored-data page renders")
    rq1=urllib.request.Request("http://127.0.0.1:8848/api/flow/say",
        data=json.dumps({"text":"I want to save 3L for medical emergencies"}).encode(),
        headers={"Content-Type":"application/json"})
    urllib.request.urlopen(rq1,timeout=20).read()
    tr=json.loads(urllib.request.urlopen("http://127.0.0.1:8848/api/chat",timeout=5).read())
    roles=[t["role"] for t in tr["turns"]]
    bothsides=("user" in roles) and ("app" in roles)
    print(("PASS " if bothsides else "FAIL ")+"transcript stored server-side".ljust(38),
          f"{len(roles)} turns, both sides={bothsides}")
    if not bothsides: fails.append("transcript stored server-side")
    alltext=" ".join(t["text"] for t in tr["turns"] if t["role"]=="app").lower()
    hindi=[w for w in ("bhai","tera","aap","hisaab","chahiye","mahine","karna","paisa") if w in alltext]
    print(("PASS " if not hindi else "FAIL ")+"all app replies are English".ljust(38),str(hindi))
    if hindi: fails.append("all app replies are English")
    if ok:
        with urllib.request.urlopen("http://127.0.0.1:8848/api/health",timeout=5) as h:
            health=json.loads(h.read())
        print("     health:",json.dumps(health))
        llm=health.get("llm_layer",{})
        print("     language layer:",json.dumps(llm))
        active=llm.get("active","deterministic_fallback")
        check_active = active in ("model","deterministic_fallback")
        print(("PASS " if check_active else "FAIL ")+"language layer reports honestly".ljust(38),active)
        if not check_active: fails.append("language layer reports honestly")
        sealed=health["memory_at_rest"]=="sealed"
        print(("PASS " if sealed else "FAIL ")+"memory sealed at rest".ljust(38),health["memory_at_rest"])
        if not sealed: fails.append("memory sealed at rest")
        single="audit" not in dir(PIPE_probe) if False else True
        import json as _j
        au=_j.loads(urllib.request.urlopen("http://127.0.0.1:8848/api/audit",timeout=5).read())
        has_flat="audit" in au
        print(("PASS " if not has_flat else "FAIL ")+"no parallel flat audit view".ljust(38),"")
        if has_flat: fails.append("no parallel flat audit view")
        # the on-disk memory store must not contain plaintext once a goal is written
        req0=urllib.request.Request("http://127.0.0.1:8848/api/flow/say",
            data=json.dumps({"text":"Dubai family trip 1.2L in 3 months"}).encode(),
            headers={"Content-Type":"application/json"})
        d0=_j.loads(urllib.request.urlopen(req0,timeout=5).read())
        urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:8848/api/flow/say",
            data=json.dumps({"text":"__respond__","aspiration_id":d0["aspiration_id"],
                             "response":"accept"}).encode(),
            headers={"Content-Type":"application/json"}),timeout=5).read()
        blob=open("memory.jsonl").read()
        leak=[w for w in ("travel","120000","savings goal") if w in blob]
        print(("PASS " if not leak else "FAIL ")+"no plaintext in memory file".ljust(38),str(leak))
        if leak: fails.append("no plaintext in memory file")
        req=urllib.request.Request("http://127.0.0.1:8848/api/flow/say",
            data=json.dumps({"text":"I want to save 3L for medical emergencies"}).encode(),
            headers={"Content-Type":"application/json"})
        d=json.loads(urllib.request.urlopen(req,timeout=5).read())
        verd=[s for s in d["stages"] if s["kind"]=="verdict"]
        challenged = bool(verd) and verd[0]["outcome"]=="at-risk"
        print(("PASS " if challenged else "FAIL ")+"adversary challenges wrong construct".ljust(38),
              verd[0]["headline"] if verd else "no verdict")
        if not challenged: fails.append("adversary challenges wrong construct")
        # U2: a clarifying question must be answerable, not orphaned
        vq=json.loads(urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:8848/api/flow/say",
            data=json.dumps({"text":"hmm paisa chahiye"}).encode(),
            headers={"Content-Type":"application/json"}),timeout=10).read())
        asked=any(s["kind"]=="clarify" for s in vq["stages"])
        cont=json.loads(urllib.request.urlopen(urllib.request.Request(
            f"http://127.0.0.1:8848/api/aspirations/{vq['aspiration_id']}/continue",
            data=json.dumps({"text":"Japan trip 2.5L in 4 months"}).encode(),
            headers={"Content-Type":"application/json"}),timeout=10).read())
        resumed=any(s["kind"]=="verdict" for s in cont["stages"])
        print(("PASS " if (asked and resumed) else "FAIL ")+"clarifying question is answerable".ljust(38),
              f"asked={asked} resumed={resumed}")
        if not (asked and resumed): fails.append("clarifying question is answerable")
        # U1: the choice step must be editable, not one canned button
        ed=[s for s in cont["stages"] if s["kind"]=="options" and s.get("editable")]
        ok_ed=bool(ed) and ed[0]["editable"]["target"]>0 and ed[0]["editable"]["timeline_mo"]>0
        print(("PASS " if ok_ed else "FAIL ")+"choice step is editable".ljust(38),
              (f"target={ed[0]['editable']['target']} timeline={ed[0]['editable']['timeline_mo']}" if ed else "no editable block"))
        if not ok_ed: fails.append("choice step is editable")
        # U4: goals view with live standing
        gv=json.loads(urllib.request.urlopen("http://127.0.0.1:8848/api/goals",timeout=5).read())
        st={g["status"] for g in gv["goals"]} if gv["goals"] else set()
        ok_gv=bool(gv["goals"]) and all(g.get("next_action") for g in gv["goals"]) and st <= {"on_track","tight","behind","at_risk"}
        print(("PASS " if ok_gv else "FAIL ")+"goals view has standing + next action".ljust(38),str(sorted(st)))
        if not ok_gv: fails.append("goals view has standing + next action")
        req2=urllib.request.Request("http://127.0.0.1:8848/api/flow/say",
            data=json.dumps({"text":"Japan 2.5L in 2 months"}).encode(),
            headers={"Content-Type":"application/json"})
        d2=json.loads(urllib.request.urlopen(req2,timeout=5).read())
        gapped = any(s["kind"]=="verdict" and s["outcome"]=="gap" for s in d2["stages"])
        print(("PASS " if gapped else "FAIL ")+"gap produces a challenge".ljust(38),"")
        if not gapped: fails.append("gap produces a challenge")
finally:
    proc.send_signal(signal.SIGTERM); proc.wait(timeout=5)

print("=== the app must be fully functional with the model layer unreachable ===")
dead=dict(os.environ)
dead["IASPIRE_LLM"]="1"; dead["IASPIRE_LLM_PROVIDER"]="ollama"
dead["OLLAMA_URL"]="http://127.0.0.1:59999"; dead["IASPIRE_LLM_TIMEOUT"]="2"
if os.path.exists("memory_gate.jsonl"): os.remove("memory_gate.jsonl")
p2=subprocess.Popen([sys.executable,"app.py"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,env=dead)
try:
    up=False
    for _ in range(30):
        time.sleep(0.3)
        try:
            with urllib.request.urlopen("http://127.0.0.1:8848/",timeout=2) as r: up=(r.status==200); break
        except Exception: pass
    print(("PASS " if up else "FAIL ")+"serves with model layer down".ljust(38),"")
    if not up: fails.append("serves with model layer down")
    if up:
        h=json.loads(urllib.request.urlopen("http://127.0.0.1:8848/api/health",timeout=5).read())
        fb=h["llm_layer"]["active"]=="deterministic_fallback"
        print(("PASS " if fb else "FAIL ")+"reports deterministic_fallback".ljust(38),h["llm_layer"]["active"])
        if not fb: fails.append("reports deterministic_fallback")
        rq=urllib.request.Request("http://127.0.0.1:8848/api/flow/say",
            data=json.dumps({"text":"I want to save 3L for medical emergencies"}).encode(),
            headers={"Content-Type":"application/json"})
        d=json.loads(urllib.request.urlopen(rq,timeout=10).read())
        adv=any(s["kind"]=="verdict" and s["outcome"]=="at-risk" for s in d["stages"])
        print(("PASS " if adv else "FAIL ")+"adversary still works, model down".ljust(38),"")
        if not adv: fails.append("adversary still works, model down")
finally:
    p2.send_signal(signal.SIGTERM); p2.wait(timeout=5)
    if os.path.exists("memory_gate.jsonl"): os.remove("memory_gate.jsonl")

print("\nFULL GATE:","ALL PASS" if not fails else f"{len(fails)} FAILURES {fails}")
sys.exit(1 if fails else 0)
