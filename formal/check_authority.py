"""Bounded Z3 checks for AuthorityClaw's current authority invariants.

This is a hand-written formal model of the decision rules, not an automatic
translation of the Python implementation. Counterexamples found during the
post-challenge audit are replayed against the real code in
``tests/test_formal_findings.py``. CI runs this file to keep the current rules
consistent with the eight stated properties.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from typing import Callable

from z3 import (
    And,
    Bool,
    FP,
    FPVal,
    Float64,
    Not,
    Or,
    Real,
    RealVal,
    Solver,
    fpGT,
    fpIsInf,
    fpIsNaN,
    unsat,
)

D64 = Float64()


def fp_num(value: float):
    return FPVal(value, D64)


def sane_fp(value):
    """Positive and finite, matching the current gate/rail requirement."""
    return And(Not(fpIsNaN(value)), Not(fpIsInf(value)), fpGT(value, fp_num(0)))


def prove(name: str, assumptions, violation) -> bool:
    solver = Solver()
    solver.add(*assumptions, violation)
    result = solver.check()
    if result == unsat:
        print(f"{name}: holds")
        return True
    print(f"{name}: COUNTEREXAMPLE")
    print(f"  {solver.model()}")
    return False


def p1_positive_finite_amount() -> bool:
    amount = FP("p1_amount", D64)
    rail_executes = sane_fp(amount)
    return prove("P1 positive finite amount", [], And(rail_executes, Not(sane_fp(amount))))


def p2_agent_weekly_limit() -> bool:
    spent = Real("p2_spent")
    amount = Real("p2_amount")
    paid = Bool("p2_paid")
    next_spent = Real("p2_next_spent")
    assumptions = [
        spent >= 0,
        spent <= 3000,
        amount > 0,
        paid == (spent + amount <= 3000),
        next_spent == spent + amount,
    ]
    return prove("P2 autonomous weekly limit", assumptions, And(paid, next_spent > 3000))


def p3_each_authority_link_weekly_limit() -> bool:
    used = Real("p3_used")
    amount = Real("p3_amount")
    cap = Real("p3_cap")
    approved = Bool("p3_approved")
    next_used = Real("p3_next_used")
    assumptions = [
        cap > 0,
        used >= 0,
        used <= cap,
        amount > 0,
        approved == (used + amount <= cap),
        next_used == used + amount,
    ]
    return prove("P3 authority-link weekly limit", assumptions, And(approved, next_used > cap))


def p4_recursive_revocation() -> bool:
    jane_active = Bool("p4_jane_active")
    tom_active = Bool("p4_tom_active")
    sam_active = Bool("p4_sam_active")
    amount_ok = Bool("p4_amount_ok")
    approval = And(jane_active, tom_active, sam_active, amount_ok)
    revoked_above = Or(Not(jane_active), Not(tom_active), Not(sam_active))
    return prove("P4 revocation stops descendants", [], And(approval, revoked_above))


def p5_director_ceiling() -> bool:
    amount = Real("p5_amount")
    director_cap = RealVal(25000)
    chain_executes = Bool("p5_chain_executes")
    assumptions = [amount > 0, chain_executes == (amount <= director_cap)]
    return prove("P5 director ceiling", assumptions, And(chain_executes, amount > director_cap))


def p6_escalate_when_someone_can_authorise() -> bool:
    amount = Real("p6_amount")
    agent_cap = RealVal(1000)
    tom_cap = RealVal(1500)
    jane_cap = RealVal(25000)
    clean = Bool("p6_clean")
    somebody_can = Or(amount <= tom_cap, amount <= jane_cap)
    hold = And(clean, amount > agent_cap, somebody_can)
    reject = And(clean, amount > agent_cap, Not(somebody_can))
    assumptions = [clean, amount > agent_cap, amount <= jane_cap]
    return prove("P6 escalation rather than refusal", assumptions, Or(reject, Not(hold)))


def p7_agent_allow_implies_all_controls() -> bool:
    controls = [
        Bool("p7_positive_finite"),
        Bool("p7_complete"),
        Bool("p7_gbp"),
        Bool("p7_approved_payee"),
        Bool("p7_same_bank"),
        Bool("p7_not_duplicate"),
        Bool("p7_within_single"),
        Bool("p7_within_weekly"),
        Bool("p7_all_links_active"),
        Bool("p7_chain_narrows"),
    ]
    all_controls = And(*controls)
    allow = all_controls
    return prove("P7 ALLOW implies all controls", [], And(allow, Not(all_controls)))


def p8_authority_has_officer_root() -> bool:
    root_is_officer = Bool("p8_root_is_officer")
    all_links_active = Bool("p8_all_links_active")
    chain_narrows = Bool("p8_chain_narrows")
    executes = And(root_is_officer, all_links_active, chain_narrows)
    return prove("P8 officer-root requirement", [], And(executes, Not(root_is_officer)))


@dataclass(frozen=True)
class Property:
    id: str
    check: Callable[[], bool]


PROPERTIES = (
    Property("P1", p1_positive_finite_amount),
    Property("P2", p2_agent_weekly_limit),
    Property("P3", p3_each_authority_link_weekly_limit),
    Property("P4", p4_recursive_revocation),
    Property("P5", p5_director_ceiling),
    Property("P6", p6_escalate_when_someone_can_authorise),
    Property("P7", p7_agent_allow_implies_all_controls),
    Property("P8", p8_authority_has_officer_root),
)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rules", choices=("current",), default="current")
    parser.add_argument("--only", nargs="*", help="Property IDs, e.g. P1 P4")
    args = parser.parse_args(argv)
    selected = {item.upper() for item in args.only} if args.only else None
    ok = True
    for prop in PROPERTIES:
        if selected and prop.id not in selected:
            continue
        ok = prop.check() and ok
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
