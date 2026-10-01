"""Things people do: revoke or restore authority, approve or decline holds, inspect state."""
import json
import os
import shutil

from . import gate, rail
from .store import Store, now_iso

DEMO_DIR = os.path.join(os.path.dirname(__file__), "demo")


def _log(st, kind, **fields):
    event = {"ts": now_iso(), "kind": kind, **fields}
    st["events"].append(event)
    return event


def _name(cfg, person_id):
    for off in cfg.get("officers", []):
        if off["id"] == person_id:
            return off["name"]
    for dele in cfg.get("delegations", []):
        if dele["to"] == person_id:
            return dele["to_name"]
    return person_id


def _target_label(cfg, target_id):
    for dele in cfg.get("delegations", []):
        if dele["id"] == target_id:
            return f"{dele['to_name']}'s authority ({dele['role']})"
    for m in cfg.get("mandates", []):
        if m["id"] == target_id:
            return f"the agent's mandate {target_id}"
    for off in cfg.get("officers", []):
        if off["id"] == target_id:
            return f"{off['name']}'s office"
    return target_id


def reset(home, config_path=None):
    for sub in ("inbox", "processed", "outbox"):
        shutil.rmtree(os.path.join(home, sub), ignore_errors=True)
    for name in ("state.json", "receipts.jsonl", "ledger.jsonl", "config.json"):
        path = os.path.join(home, name)
        if os.path.exists(path):
            os.remove(path)
    store = Store(home)
    with open(config_path or os.path.join(DEMO_DIR, "config.json"), encoding="utf-8") as f:
        store.write_config(json.load(f))
    store.save_state(Store.empty_state())
    return store


def revoke(store, target_id, by="jane"):
    with store.lock:
        cfg, st = store.config(), store.state()
        who = _name(cfg, by)
        st["revoked"][target_id] = {"by": who, "ts": now_iso()}
        event = _log(st, "revoked", target=target_id, label=_target_label(cfg, target_id), by=who)
        store.save_state(st)
        return event


def restore(store, target_id, by="jane"):
    with store.lock:
        cfg, st = store.config(), store.state()
        st["revoked"].pop(target_id, None)
        event = _log(st, "restored", target=target_id, label=_target_label(cfg, target_id), by=_name(cfg, by))
        store.save_state(st)
        return event


def _chain_summary(links):
    return [{k: link[k] for k in ("kind", "id", "holder", "status")} for link in links]


def approve_hold(store, hold_id, by="tom"):
    with store.lock:
        cfg, st = store.config(), store.state()
        hold = st["holds"].get(hold_id)
        if not hold or hold["status"] != "open":
            return {"error": f"No open hold {hold_id}."}
        action = hold["action"]
        amount = float(action.get("amount") or 0)
        ok, why, who = gate.approver_authority(cfg, st, by, amount)
        result = gate.evaluate(action, cfg, st)
        # A person approves on their own authority, so the agent-chain checks give way,
        # but payee, duplicate, scope and currency failures still stop the payment.
        blocking = [r for r in result["reasons"] if r["level"] == gate.REJECT and r["code"] in
                    ("payee_not_approved", "duplicate", "out_of_scope", "wrong_currency", "above_all_limits")]
        if not ok or blocking:
            reasons = ([{"code": "approver_lacks_authority", "level": gate.REJECT, "text": why}] if not ok else []) + blocking
            rec = store.append_receipt({"decision": "REJECT", "action": action, "reasons": reasons,
                                        "decided_by": f"approval attempt by {who}", "of_hold": hold_id,
                                        "chain": _chain_summary(result["chain"])})
            event = _log(st, "decision", receipt=rec["id"], decision="REJECT", payee=action["payee"],
                         amount=action["amount"], invoice_ref=action["invoice_ref"], reasons=reasons,
                         hash=rec["hash"][:12], by=who, of_hold=hold_id)
            store.save_state(st)
            return event
        approved_points = [r for r in result["reasons"] if r["level"] == gate.HOLD]
        reasons = [{"code": "human_approval", "level": gate.PASS,
                    "text": f"Approved by {who}, within {who.split()[0]}'s own authority."}] + approved_points
        rec = store.append_receipt({"decision": "APPROVED", "action": action, "reasons": reasons, "decided_by": who,
                                    "of_hold": hold_id, "chain": _chain_summary(result["chain"])})
        payment = rail.execute(store, st, rec, action, approved_by=who)
        hold.update(status="approved", resolved_by=who, resolved_at=now_iso(), receipt=rec["id"])
        event = _log(st, "decision", receipt=rec["id"], decision="APPROVED", payee=action["payee"],
                     amount=action["amount"], invoice_ref=action["invoice_ref"], reasons=reasons,
                     hash=rec["hash"][:12], by=who, of_hold=hold_id, payment_id=payment["payment_id"])
        store.save_state(st)
        return event


def decline_hold(store, hold_id, by="tom"):
    with store.lock:
        cfg, st = store.config(), store.state()
        hold = st["holds"].get(hold_id)
        if not hold or hold["status"] != "open":
            return {"error": f"No open hold {hold_id}."}
        who = _name(cfg, by)
        action = hold["action"]
        reasons = [{"code": "declined", "level": gate.REJECT, "text": f"Declined by {who}."}]
        rec = store.append_receipt({"decision": "DECLINED", "action": action, "reasons": reasons,
                                    "decided_by": who, "of_hold": hold_id})
        hold.update(status="declined", resolved_by=who, resolved_at=now_iso(), receipt=rec["id"])
        event = _log(st, "decision", receipt=rec["id"], decision="DECLINED", payee=action["payee"],
                     amount=action["amount"], invoice_ref=action["invoice_ref"], reasons=reasons,
                     hash=rec["hash"][:12], by=who, of_hold=hold_id)
        store.save_state(st)
        return event


def snapshot(store):
    with store.lock:
        cfg, st = store.config(), store.state()
        day = gate.today_utc()
        agent = cfg.get("agent", {})
        links, fails = gate.authority_chain(cfg, st, agent.get("mandate_id"), day)
        mandate = next((m for m in cfg.get("mandates", []) if m["id"] == agent.get("mandate_id")), {})
        ok, bad, count, last = store.verify_chain()
        return {
            "principal": cfg.get("principal", {}),
            "agent": agent,
            "chain": list(reversed(links)),
            "chain_ok": not fails,
            "chain_problems": [text for _, _, text in fails],
            "limits": mandate.get("scope", {}),
            "week": gate.iso_week(day),
            "week_spent": float(st.get("weekly", {}).get(gate.iso_week(day), 0)),
            "heartbeat": st.get("heartbeat", {}),
            "events": list(reversed(st.get("events", [])[-60:])),
            "open_holds": [h for h in st.get("holds", {}).values() if h["status"] == "open"],
            "receipts": {"ok": ok, "count": count, "first_bad": bad, "last_hash": last[:16]},
            "payments": len(store.ledger()),
        }
