"""J6 deterministic feasibility engine.

Pure numeric computation. No LLM involvement in the calculation itself (Anchor 1 §12).
All thresholds come from policy/feasibility_policy.json - never hardcoded here - and every
result echoes the policy version and the thresholds actually applied, so a historical result
stays interpretable if the policy is later tightened.

FeasibilityResult carries computed_by="deterministic_engine" and is exact/reproducible.
"""
import json, os

_POLICY_PATH=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "policy","feasibility_policy.json")
_POLICY=json.load(open(_POLICY_PATH))
T={k:v["value"] for k,v in _POLICY["thresholds"].items()}
POLICY_VERSION=_POLICY["version"]

def policy_snapshot():
    return {"policy_id":_POLICY["policy_id"],"version":POLICY_VERSION,
            "thresholds_applied":dict(T),
            "provisional":_POLICY["provenance"]["status"]=="PROVISIONAL"}

# Emergency basis lives ONLY in policy/feasibility_policy.json. Single owner, no duplicate.
DEFAULT_EMERGENCY_BASIS=T["emergency_basis_amount"]

def emergency_months(savings, emergency_basis=None):
    """Liquid runway in months, using the declared basis denominator."""
    basis=emergency_basis if emergency_basis else DEFAULT_EMERGENCY_BASIS
    monthly_basis=_POLICY["thresholds"]["emergency_basis_months"]["value"]
    if savings<=0 or basis<=0: return 0.0
    return round(savings/(basis/monthly_basis),2)

def _basis_from(benchmarks):
    """External benchmark files no longer own this constant. Passing one is accepted for
    signature compatibility but deliberately ignored, so there is exactly one source."""
    return DEFAULT_EMERGENCY_BASIS

def compute(candidate, snapshot, benchmarks=None):
    """benchmarks may be a loaded dict, a path, or None."""
    basis=_basis_from(benchmarks)
    cap=candidate["required_capital"]; n=max(1,candidate["horizon_mo"])
    monthly_need=round(cap/n,2)

    income_avg=snapshot.income_monthly_avg
    income_worst=getattr(snapshot,"income_min_month",income_avg) or 0.0
    avail_avg=round(T["max_savings_rate"]*income_avg,2)

    # Seasonal / irregular stress test against the worst observed month.
    stress_applies = income_avg>0 and income_worst>0 and (income_worst/income_avg) < T["seasonal_stress_ratio"]
    stress_income = income_worst if stress_applies else income_avg
    avail_stress=round(T["max_savings_rate"]*stress_income,2)

    emerg_mo=emergency_months(snapshot.balances.get("savings",0.0), basis)
    debt=snapshot.balances.get("debt",0.0)
    debt_service=round(T["debt_service_ceiling"]*income_avg,2)
    debt_months=round(debt/income_avg,2) if income_avg>0 else 0.0
    debt_spiral = debt>0 and debt_months > T["debt_to_income_spiral_ratio"]

    notes=[]; wrong=False
    m=candidate["mechanism"]

    if candidate.get("liquidity_need")=="high" and m=="liquid reserve" \
       and _POLICY["mechanism_rules"]["protection_requires_insurance"]["value"]:
        wrong=True; notes.append("save-only cannot absorb a large medical shock; insurance missing")

    if debt_spiral:
        notes.append(f"debt spiral: {debt_months} months of income owed vs limit "
                     f"{T['debt_to_income_spiral_ratio']}")

    if monthly_need>avail_stress:
        gap_amt=round(monthly_need-avail_stress,2)
        notes.append(f"cash pressure: need {monthly_need}/mo vs safe {avail_stress}/mo")
    else:
        gap_amt=0.0
        if stress_applies:
            notes.append(f"passes on average income but fails on worst month "
                         f"({income_worst} vs {income_avg}) - held to the stress figure")

    if emerg_mo<T["emergency_months_required"]:
        notes.append(f"emergency thin: {emerg_mo}mo vs required {T['emergency_months_required']}mo")

    affordable = monthly_need<=avail_stress and emerg_mo>=T["emergency_months_required"] and not debt_spiral
    outcome="feasible" if (affordable and not wrong) else ("at-risk" if wrong else "gap")
    return {"mechanism":m,"feasible":bool(affordable and not wrong),
            "outcome":outcome,"gap_amount":gap_amt,
            "monthly_need":monthly_need,"avail_monthly":avail_avg,
            "avail_stress_monthly":avail_stress,
            "income_avg_used":income_avg,"income_worst_used":stress_income,
            "stress_applied":stress_applies,
            "emergency_mo":emerg_mo,"debt_spiral":debt_spiral,
            "debt_months_owed":debt_months,"debt_service_ceiling":debt_service,
            "risk_notes":notes,
            "computed_by":"deterministic_engine","version":"j6v2",
            "policy_version":POLICY_VERSION}
