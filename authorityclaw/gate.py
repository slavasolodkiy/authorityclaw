"""Deterministic authority gate.

The model proposes; this code decides. Every consequential action is checked
against the whole chain of authority behind the agent:

    principal (company) -> officer -> delegate -> agent mandate -> action

and against scope, limits, bank-detail memory, duplicates and live revocation.
No model output can change the verdict.
"""
import math
import re
from datetime import date, datetime, timezone

REJECT, HOLD, PASS = "reject", "hold", "pass"


def today_utc(at=None):
    return (at or datetime.now(timezone.utc)).date()


def iso_week(day):
    year, week, _ = day.isocalendar()
    return f"{year}-W{week:02d}"


def as_amount(value):
    """The amount as a float; anything unreadable becomes NaN, which is never payable."""
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return float("nan")


def sane_amount(value):
    """A payable amount is a positive, finite number: not NaN, not infinite, not zero, not negative."""
    amount = as_amount(value)
    return math.isfinite(amount) and amount > 0


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

    if not fails and not any(link["kind"] == "officer" for link in links):
        fails.append(("no_root", REJECT, "This authority does not trace back to an officer of the company."))
    for child, parent in zip(links, links[1:]):
        c, p = child.get("limits", {}), parent.get("limits", {})
        if c.get("max_single", 0) > p.get("max_single", 0) or c.get("max_weekly", 0) > p.get("max_weekly", 0):
            fails.append(("authority_widens", REJECT,
                          f"{child['id']} grants more than {parent['holder']} holds; authority may only narrow down the chain."))
    return links, fails


def person_chain(cfg, st, person_id, day):
    """The chain of authority above a person who approves something, starting with their own link.

    The same rules as the agent's chain: every link must be live, must fit inside its parent,
    and the chain must end at an officer of the company. Revoking anyone in it stops everyone below.
    """
    revoked = st.get("revoked", {})
    officers = {o["id"]: o for o in cfg.get("officers", [])}
    delegation_of = {d["to"]: d for d in cfg.get("delegations", [])}
    links, fails, current, hops = [], [], person_id, 0
    while current and hops < 6:
        hops += 1
        own = not links
        first = links[0]["holder"] if links else None
        if current in officers:
            off = officers[current]
            status = _status(off, revoked, day)
            links.append({"kind": "officer", "id": off["id"], "holder": off["name"], "role": off["role"],
                          "limits": off["capacity"], "status": status})
            if status != "active":
                fails.append(("officer_invalid", REJECT, f"{off['name']} no longer holds authority as {off['role']}." if own
                              else f"{first}'s authority comes through {off['name']}, who no longer holds office."))
            break
        dele = delegation_of.get(current)
        if not dele:
            fails.append(("no_capacity", REJECT, f"{current} has no recorded authority."))
            break
        status = _status(dele, revoked, day)
        links.append({"kind": "delegation", "id": dele["id"], "holder": dele["to_name"], "role": dele["role"],
                      "limits": dele["capacity"], "status": status})
        if status != "active":
            what = f"revoked by {revoked[dele['id']]['by']}" if status == "revoked" else "expired"
            fails.append(("delegation_" + status, REJECT, f"{dele['to_name']}'s authority was {what}." if own
                          else f"{first}'s authority comes through {dele['to_name']}, whose authority was {what}."))
        current = dele["from"]
    if links and not fails and links[-1]["kind"] != "officer":
        fails.append(("no_root", REJECT, f"{links[0]['holder']}'s authority does not trace back to an officer of the company."))
    for child, parent in zip(links, links[1:]):
        c, p = child.get("limits", {}), parent.get("limits", {})
        if c.get("max_single", 0) > p.get("max_single", 0) or c.get("max_weekly", 0) > p.get("max_weekly", 0):
            fails.append(("authority_widens", REJECT,
                          f"{child['holder']}'s authority is wider than {parent['holder']}'s; authority may only narrow."))
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

    amount = as_amount(action.get("amount"))
    valid = sane_amount(amount)
    if action.get("amount") and not valid:
        checks.append(("invalid_amount", REJECT, "The amount is not a positive, finite sum of money."))
    if mandate and valid and amount > scope.get("max_single", 0):
        able = next((l for l in links[1:] if l["status"] == "active" and amount <= l["limits"].get("max_single", 0)), None)
        if able:
            checks.append(("above_agent_limit", HOLD,
                           f"{money(amount)} is above the agent's {money(scope['max_single'])} limit; "
                           f"{able['holder']} can approve it."))
        else:
            checks.append(("above_all_limits", REJECT, f"{money(amount)} is more than anyone in this chain can authorise."))

    week = iso_week(day)
    spent = float(st.get("weekly", {}).get(week, 0))
    if mandate and valid and spent + amount > scope.get("max_weekly", 0):
        checks.append(("weekly_limit", HOLD,
                       f"This would take the week to {money(spent + amount)}, over the {money(scope['max_weekly'])} weekly limit."))
    used = st.get("link_weekly", {}).get(week, {})
    over_week = any(code == "weekly_limit" for code, _, _ in checks)
    for link in links:
        if link["kind"] == "mandate" and over_week:
            continue
        cap = link["limits"].get("max_weekly", 0)
        total = float(used.get(link["id"], 0)) + amount
        if valid and link["status"] == "active" and total > cap:
            checks.append(("authority_weekly_limit", HOLD,
                           f"This would take payments under {link['holder']}'s authority to {money(total)} this week, "
                           f"over the {money(cap)} weekly limit."))

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
    """Can this person approve a held payment of this amount? Returns (ok, why, display_name, chain).

    The approver's whole chain is checked, not only their own link: revoking anyone above them
    stops them too. Their per-payment and weekly limits both apply.
    """
    day = today_utc(at)
    links, fails = person_chain(cfg, st, approver_id, day)
    if not links:
        return False, f"{approver_id} has no recorded authority.", approver_id, links
    name = links[0]["holder"]
    if fails:
        return False, fails[0][2], name, links
    if not sane_amount(amount):
        return False, "The amount is not a positive, finite sum of money.", name, links
    if amount > links[0]["limits"].get("max_single", 0):
        return False, f"{money(amount)} is above {name}'s authority.", name, links
    used = st.get("link_weekly", {}).get(iso_week(day), {})
    for link in links:
        cap = link["limits"].get("max_weekly", 0)
        total = float(used.get(link["id"], 0)) + amount
        if total > cap:
            return False, (f"This would take payments under {link['holder']}'s authority to {money(total)} this week, "
                           f"over the {money(cap)} weekly limit."), name, links
    return True, "", name, links
