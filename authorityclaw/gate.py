"""Deterministic authority gate.

The model proposes; this code decides. Every consequential action is checked
against the whole chain of authority behind the agent:

    principal (company) -> officer -> delegate -> agent mandate -> action

and against scope, limits, bank-detail memory, duplicates and live revocation.
No model output can change the verdict.
"""
import re
from datetime import date, datetime, timezone

REJECT, HOLD, PASS = "reject", "hold", "pass"


def today_utc(at=None):
    return (at or datetime.now(timezone.utc)).date()


def iso_week(day):
    year, week, _ = day.isocalendar()
    return f"{year}-W{week:02d}"


def norm(name):
    name = re.sub(r"\b(ltd|limited|plc)\b\.?", "", (name or "").lower())
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", name).split())


def digits(value):
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def money(value):
    return f"£{float(value or 0):,.2f}"


def _in_window(obj, day):
    start, end = obj.get("valid_from"), obj.get("valid_until")
    if start and day < date.fromisoformat(start):
        return False
    if end and day > date.fromisoformat(end):
        return False
    return True


def _status(obj, revoked, day):
    if obj["id"] in revoked:
        return "revoked"
    return "active" if _in_window(obj, day) else "expired"


def find_supplier(cfg, name):
    key = norm(name)
    for sup in cfg.get("approved_suppliers", []):
        if norm(sup["name"]) == key:
            return sup
    return None


def authority_chain(cfg, st, mandate_id, day):
    """Walk from the agent's mandate up to an officer of the principal.

    Returns (links, failures). Links run child -> parent:
    mandate, delegation(s), officer. Each link must fit inside its parent:
    authority may narrow down the chain, never widen.
    """
    revoked = st.get("revoked", {})
    mandates = {m["id"]: m for m in cfg.get("mandates", [])}
    officers = {o["id"]: o for o in cfg.get("officers", [])}
    delegation_of = {d["to"]: d for d in cfg.get("delegations", [])}
    links, fails = [], []

    mandate = mandates.get(mandate_id)
    if not mandate:
        return links, [("no_mandate", REJECT, "No mandate on file for this agent.")]
    status = _status(mandate, revoked, day)
    links.append({"kind": "mandate", "id": mandate["id"], "holder": cfg.get("agent", {}).get("name", mandate["agent"]),
                  "role": mandate.get("purpose", "Agent mandate"), "limits": mandate["scope"], "status": status})
    if status == "revoked":
        fails.append(("mandate_revoked", REJECT, f"The agent's mandate {mandate['id']} was revoked by {revoked[mandate['id']]['by']}."))
    elif status == "expired":
        fails.append(("mandate_expired", REJECT, f"The agent's mandate {mandate['id']} is outside its validity window."))

    grantor, hops = mandate["granted_by"], 0
    while grantor and hops < 6:
        hops += 1
        if grantor in officers:
            off = officers[grantor]
            status = _status(off, revoked, day)
            links.append({"kind": "officer", "id": off["id"], "holder": off["name"], "role": off["role"],
                          "limits": off["capacity"], "status": status, "source": off.get("source")})
            if status != "active":
                fails.append(("officer_invalid", REJECT, f"{off['name']} no longer holds authority as {off['role']}."))
            break
        dele = delegation_of.get(grantor)
        if not dele:
            fails.append(("no_capacity", REJECT, f"{grantor} has no recorded authority to delegate."))
            break
        status = _status(dele, revoked, day)
        links.append({"kind": "delegation", "id": dele["id"], "holder": dele["to_name"], "role": dele["role"],
                      "limits": dele["capacity"], "status": status, "source": dele.get("source")})
        if status == "revoked":
            fails.append(("delegation_revoked", REJECT,
                          f"{dele['to_name']}'s authority was revoked by {revoked[dele['id']]['by']}, so the mandate "
                          f"{dele['to_name'].split()[0]} gave this agent no longer stands."))
        elif status == "expired":
            fails.append(("delegation_expired", REJECT, f"{dele['to_name']}'s authority has expired."))
        grantor = dele["from"]

    for child, parent in zip(links, links[1:]):
        c, p = child.get("limits", {}), parent.get("limits", {})
        if c.get("max_single", 0) > p.get("max_single", 0) or c.get("max_weekly", 0) > p.get("max_weekly", 0):
            fails.append(("authority_widens", REJECT,
                          f"{child['id']} grants more than {parent['holder']} holds; authority may only narrow down the chain."))
    return links, fails


def evaluate(action, cfg, st, at=None):
    """Return {"decision": ALLOW|HOLD|REJECT, "reasons": [...], "chain": [...]}."""
    day = today_utc(at)
    checks = []
    links, chain_fails = authority_chain(cfg, st, action.get("mandate_id"), day)
    checks += chain_fails
    mandate = next((m for m in cfg.get("mandates", []) if m["id"] == action.get("mandate_id")), None)
    scope = (mandate or {}).get("scope", {})

    missing = [k for k in ("payee", "amount", "sort_code", "account", "invoice_ref") if not action.get(k)]
    if missing:
        checks.append(("incomplete_evidence", HOLD, "Missing from the invoice: " + ", ".join(missing) + "."))

    if mandate and action.get("type") != scope.get("action"):
        checks.append(("out_of_scope", REJECT, f"The mandate covers {scope.get('action')}s only."))
    if mandate and (action.get("currency") or "GBP") != scope.get("currency", "GBP"):
        checks.append(("wrong_currency", REJECT, f"The mandate covers {scope.get('currency', 'GBP')} payments only."))

    supplier = find_supplier(cfg, action.get("payee"))
    if action.get("payee") and not supplier:
        checks.append(("payee_not_approved", REJECT, f"{action['payee']} is not an approved supplier."))
    if supplier and (digits(supplier["sort_code"]) != digits(action.get("sort_code"))
                     or digits(supplier["account"]) != digits(action.get("account"))):
        checks.append(("bank_details_changed", HOLD,
                       f"Bank details differ from the approved record for {supplier['name']}: the usual "
                       f"invoice-redirection pattern. Confirm through a known contact before paying."))

    amount = float(action.get("amount") or 0)
    if mandate and amount > scope.get("max_single", 0):
        above = next((l for l in links[1:] if l["status"] == "active"), None)
        if above and amount <= above["limits"].get("max_single", 0):
            checks.append(("above_agent_limit", HOLD,
                           f"{money(amount)} is above the agent's {money(scope['max_single'])} limit; "
                           f"{above['holder']} can approve it."))
        else:
            checks.append(("above_all_limits", REJECT, f"{money(amount)} is more than anyone in this chain can authorise."))

    week = iso_week(day)
    spent = float(st.get("weekly", {}).get(week, 0))
    if mandate and amount and spent + amount > scope.get("max_weekly", 0):
        checks.append(("weekly_limit", HOLD,
                       f"This would take the week to {money(spent + amount)}, over the {money(scope['max_weekly'])} weekly limit."))

    ref_key = f"{norm(action.get('payee'))}|{action.get('invoice_ref')}"
    if ref_key in st.get("paid_refs", {}):
        checks.append(("duplicate", REJECT,
                       f"Invoice {action.get('invoice_ref')} from {action.get('payee')} was already paid "
                       f"({st['paid_refs'][ref_key]})."))

    if any(level == REJECT for _, level, _ in checks):
        decision = "REJECT"
    elif any(level == HOLD for _, level, _ in checks):
        decision = "HOLD"
    else:
        decision = "ALLOW"
    reasons = [{"code": c, "level": lvl, "text": txt} for c, lvl, txt in checks] or [
        {"code": "within_mandate", "level": PASS,
         "text": "Within mandate: approved supplier, known bank details, inside the per-invoice and weekly limits."}]
    return {"decision": decision, "reasons": reasons, "chain": links}


def approver_authority(cfg, st, approver_id, amount, at=None):
    """Can this person approve a held payment of this amount? (ok, why, display_name)"""
    day = today_utc(at)
    revoked = st.get("revoked", {})
    for off in cfg.get("officers", []):
        if off["id"] == approver_id:
            if _status(off, revoked, day) != "active":
                return False, f"{off['name']} no longer holds authority.", off["name"]
            if amount > off["capacity"].get("max_single", 0):
                return False, f"{money(amount)} is above {off['name']}'s authority.", off["name"]
            return True, "", off["name"]
    for dele in cfg.get("delegations", []):
        if dele["to"] == approver_id:
            name = dele["to_name"]
            if _status(dele, revoked, day) != "active":
                return False, f"{name}'s authority was revoked by {revoked.get(dele['id'], {}).get('by', 'the grantor')}.", name
            parent = next((o for o in cfg.get("officers", []) if o["id"] == dele["from"]), None)
            if parent and _status(parent, revoked, day) != "active":
                return False, f"{name}'s authority came from {parent['name']}, who no longer holds office.", name
            if amount > dele["capacity"].get("max_single", 0):
                return False, f"{money(amount)} is above {name}'s authority.", name
            return True, "", name
    return False, f"{approver_id} has no recorded authority.", approver_id
