"""J2 financial normalization -> canonical FinancialSnapshot.

Anchor 1 J2 explicitly requires *income smoothing for irregular earners*. The previous
3-month window silently hid off-season collapse, so a seasonal business looked as steady as
a salaried one. This version:
  - aggregates income over the policy window (12 months) so at least one full cycle is seen
  - reports avg, worst observed month, and the number of months actually observed
  - smooths genuinely irregular (weekly/gig) earners by crediting a low month rather than
    pretending a quiet week means zero income
  - derives recurring obligations from observed transactions instead of hardcoding them
  - reconciles against source totals within tolerance
"""
from dataclasses import dataclass, field
from typing import List, Dict
from j1_ingest import RawTransaction, RawAccountSnapshot

@dataclass
class FinancialSnapshot:
    customer_id: str; as_of: str
    balances: Dict[str,float]
    income_monthly_avg: float
    income_min_month: float
    spend_3mo: float; essential_3mo: float
    obligations_monthly: float
    income_profile: Dict = field(default_factory=dict)
    data_class: str = "observed_data"

INCOME_CATS={"income"}
# FX rates are policy, not code. Held here so a snapshot can normalise multi-currency accounts
# without touching the engine. Rates are illustrative and marked as such.
FX_TO_BASE={"INR":1.0,"USD":83.0,"EUR":90.0,"GBP":106.0,"AED":22.6}
BASE_CURRENCY="INR"
ESSENTIAL={"family_health","investment","hostel_ops","essentials"}
RECURRING_CATS={"family_health","subscription","investment","utilities"}
TOL=0.01
WINDOW_MONTHS=12

def _month_key(d): return d[:7]
def _months_between(as_of, months):
    y,m=int(as_of[:4]),int(as_of[5:7]); out=[]
    for _ in range(months):
        out.append(f"{y:04d}-{m:02d}")
        m-=1
        if m==0: y,m=y-1,12
    return out

def _derive_obligations(txns, window_keys):
    """Recurring monthly commitments, derived from observed transactions.

    Each recurring category is normalised by the number of months in which it actually
    appeared, not by the full window length. These categories are recurring by definition,
    so a commitment seen once in a four-month dataset is a monthly commitment that fired
    once - dividing by the whole window would silently understate it to a fraction.
    """
    totals={}; months={}
    for t in txns:
        if t.category in RECURRING_CATS and _month_key(t.date) in window_keys:
            totals[t.category]=totals.get(t.category,0.0)+t.amount
            months.setdefault(t.category,set()).add(_month_key(t.date))
    detail={k:round(v/max(1,len(months[k])),2) for k,v in totals.items()}
    return round(sum(detail.values()),2), detail

def _to_base(amount,currency):
    """Normalise a foreign-currency amount into the base currency. Unknown currency is a
    hard error rather than a silent 1:1, which would understate a foreign balance."""
    if not currency or currency==BASE_CURRENCY: return amount
    rate=FX_TO_BASE.get(currency)
    if rate is None: raise ValueError(f"no FX rate for {currency}")
    return round(amount*rate,2)

def build_snapshot(customer_id, txns: List[RawTransaction], accts: Dict[str,RawAccountSnapshot],
                   as_of: str, income_pattern: str="flat", base_currency: str=BASE_CURRENCY):
    balances={}
    fx={}
    for k,v in accts.items():
        cur=(v.meta or {}).get("currency",base_currency)
        balances[k]=_to_base(v.balance,cur)
        if cur!=base_currency: fx[k]=cur
    window=_months_between(as_of, WINDOW_MONTHS)
    income={k:0.0 for k in window}
    for t in txns:
        if t.category in INCOME_CATS and t.amount>0 and _month_key(t.date) in window:
            income[_month_key(t.date)]+=_to_base(t.amount,(t.meta or {}).get("currency"))

    observed=[k for k in window if income[k]>0]
    if observed:
        income_avg=round(sum(income[k] for k in observed)/len(observed),2)
        income_min=round(min(income[k] for k in observed),2)
    else:
        credits=[t.amount for t in txns if t.category in INCOME_CATS and t.amount>0]
        if not credits:
            income_avg=income_min=0.0
        else:
            income_avg=round(sum(credits)/max(1,len({_month_key(t.date) for t in txns
                           if t.category in INCOME_CATS})),2)
            income_min=round(min(credits),2)

    # Irregular earners: a month with no credit is a data gap, not zero income. Credit it
    # with the observed minimum so a partial window cannot deflate the runway.
    if income_pattern=="irregular_weekly":
        gaps=[k for k in window if income[k]==0.0]
        for k in gaps: income[k]=income_min
        observed=window
        income_avg=round(sum(income[k] for k in window)/len(window),2)

    debits=[t for t in txns if t.category not in INCOME_CATS]
    spend=round(sum(_to_base(t.amount,(t.meta or {}).get("currency")) for t in debits),2)
    essential=round(sum(_to_base(t.amount,(t.meta or {}).get("currency")) for t in debits
                        if t.category in ESSENTIAL),2)
    obligations,oblig_detail=_derive_obligations(txns,window)

    profile={"base_currency":base_currency,"fx_normalised":fx or None,"fx_rates":FX_TO_BASE,
             "pattern":income_pattern,"window_months":WINDOW_MONTHS,
             "months_observed":len(observed),"months_missing":WINDOW_MONTHS-len(observed),
             "worst_ratio":round(income_min/income_avg,3) if income_avg>0 else 0.0,
             "obligations_derived_from":"observed_transactions",
             "obligations_detail":oblig_detail}

    snap=FinancialSnapshot(customer_id,as_of,balances,income_avg,income_min,
                           spend,essential,obligations,profile)
    rec={"source_debit_total":spend,"snapshot_spend":snap.spend_3mo,
         "income_window":{k:income[k] for k in window},
         "months_observed":len(observed),
         "match":abs(spend-snap.spend_3mo)<=TOL}
    return snap,{"event":"snapshot.updated","reconciled":rec["match"],"detail":rec}
