"""A simulated Faster Payments rail. It pays only against a valid authority receipt."""
from .gate import iso_week, norm, today_utc
from .store import now_iso


def execute(store, st, receipt, action, approved_by=None):
    if receipt.get("decision") not in ("ALLOW", "APPROVED"):
        raise PermissionError("Payment refused: no ALLOW or APPROVED authority receipt.")
    ok, bad, _, _ = store.verify_chain()
    if not ok:
        raise PermissionError(f"Payment refused: receipt chain broken at {bad}.")
    ledger = store.ledger()
    if any(entry.get("receipt_id") == receipt["id"] for entry in ledger):
        raise PermissionError("Payment refused: this receipt has already been used.")
    amount = round(float(action["amount"]), 2)
    entry = {
        "payment_id": f"FP-{len(ledger) + 1:05d}",
        "ts": now_iso(),
        "rail": "simulated Faster Payments",
        "payee": action["payee"],
        "sort_code": action["sort_code"],
        "account": action["account"],
        "amount": amount,
        "currency": action.get("currency") or "GBP",
        "invoice_ref": action["invoice_ref"],
        "receipt_id": receipt["id"],
        "approved_by": approved_by,
    }
    store.append_ledger(entry)
    week = iso_week(today_utc())
    st["weekly"][week] = round(float(st["weekly"].get(week, 0)) + amount, 2)
    st["paid_refs"][f"{norm(action['payee'])}|{action['invoice_ref']}"] = entry["payment_id"]
    memory = st["suppliers"].setdefault(action["payee"], {"payments": 0, "total": 0.0})
    memory["payments"] += 1
    memory["total"] = round(memory["total"] + amount, 2)
    memory["last_paid"] = entry["ts"]
    return entry
