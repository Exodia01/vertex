"""J5 banking-equivalent candidates. Customer's stated mechanism is ranked first.
Candidate generation only; J6 judges feasibility."""
import json
MAP=json.load(open("banking_map.json"))
BENCH=json.load(open("benchmarks.json"))["external_benchmarks"]
MECH={k:v["mechanisms"] for k,v in MAP["objectives"].items()}
STATED_TO_MECH=MAP["stated_to_mechanism"]
LIQUIDITY_HIGH=set(MAP["liquidity_need_by_objective"])
BENCH_CAP={"travel":BENCH["travel"]["dubai_family_typical"],"asset":1500000,"protection":300000,
           "liquidity":200000,"wealth":200000,"debt":0}
def candidates(intent):
    obj=intent["objective_category"]
    if obj=="unknown": return []
    cap=intent["amount"] or BENCH_CAP.get(obj,200000)
    mechs=list(MECH[obj])
    stated=STATED_TO_MECH.get(intent.get("stated_mechanism"))
    if stated in mechs:
        mechs.remove(stated); mechs.insert(0,stated)
    return [{"mechanism":m,"required_capital":cap,"horizon_mo":intent["horizon_mo"],
             "liquidity_need":("high" if obj in LIQUIDITY_HIGH else "med"),
             "financing_need":("loan" in m.lower() or "emi" in m.lower() or "mortgage" in m.lower()),
             "is_stated":(m==stated and stated is not None)}
            for m in mechs]
