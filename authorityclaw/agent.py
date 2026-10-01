"""The long-running accounts-payable agent.

Each cycle: pick up new invoices -> read them with the model -> ask the gate ->
pay (ALLOW), park for a person (HOLD) or refuse (REJECT) -> remember -> sleep.
"""
import os
import shutil
import time

from . import extract as ex
from . import gate, rail
from .actions import _chain_summary, _log
from .store import now_iso, sha256_text


class Agent:
    def __init__(self, store, poll=3.0):
        self.store = store
        self.poll = poll

    def handle(self, path):
        store = self.store
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
        digest = sha256_text(text)
        with store.lock:
            st = store.state()
            if digest in st["processed"]:
                return None
            st["heartbeat"].update(phase="reading", source=os.path.basename(path), last=now_iso())
            store.save_state(st)
        read_started = time.monotonic()
        fields = ex.extract(text)  # slow part (model call) runs outside the lock
        read_seconds = round(time.monotonic() - read_started, 3)
        with store.lock:
            cfg, st = store.config(), store.state()
            action = {
                "type": "payment",
                "mandate_id": cfg["agent"]["mandate_id"],
                "payee": fields.get("payee"),
                "amount": fields.get("amount"),
                "currency": fields.get("currency") or "GBP",
                "sort_code": fields.get("sort_code"),
                "account": fields.get("account"),
                "invoice_ref": fields.get("invoice_ref"),
                "description": fields.get("description"),
                "source": os.path.basename(path),
                "source_sha256": digest,
                "read_by": fields.get("_engine"),
                "injection_detected": bool(fields.get("suspicious_instructions")),
            }
            result = gate.evaluate(action, cfg, st)
            receipt = store.append_receipt({"decision": result["decision"], "action": action,
                                            "reasons": result["reasons"], "decided_by": "gate",
                                            "chain": _chain_summary(result["chain"])})
            event = {"receipt": receipt["id"], "decision": receipt["decision"], "payee": action["payee"],
                     "amount": action["amount"], "invoice_ref": action["invoice_ref"],
                     "reasons": result["reasons"], "source": action["source"], "hash": receipt["hash"][:12],
                     "injection": action["injection_detected"], "read_by": action["read_by"],
                     "read_seconds": read_seconds}
            if result["decision"] == "ALLOW":
                event["payment_id"] = rail.execute(store, st, receipt, action)["payment_id"]
            elif result["decision"] == "HOLD":
                note, by_model = ex.hold_note(action, result["reasons"])
                st["holds"][receipt["id"]] = {"id": receipt["id"], "action": action, "reasons": result["reasons"],
                                              "note": note, "status": "open", "ts": now_iso()}
                with open(os.path.join(store.outbox, f"{receipt['id']}-note.txt"), "w", encoding="utf-8") as f:
                    f.write(note + "\n")
                if by_model:
                    event["note"] = note
            st["processed"][digest] = receipt["id"]
            st["heartbeat"]["handled"] += 1
            _log(st, "decision", **event)
            store.save_state(st)
        shutil.move(path, os.path.join(store.done, os.path.basename(path)))
        return event

    def cycle(self):
        store, results = self.store, []
        for name in sorted(os.listdir(store.inbox)):
            path = os.path.join(store.inbox, name)
            if name.startswith(".") or not os.path.isfile(path):
                continue
            try:
                results.append(self.handle(path))
            except Exception as exc:  # one bad file never stops the agent
                with store.lock:
                    st = store.state()
                    _log(st, "error", source=name, error=f"{type(exc).__name__}: {exc}")
                    store.save_state(st)
                shutil.move(path, os.path.join(store.done, name + ".error"))
        with store.lock:
            st = store.state()
            beat = st["heartbeat"]
            beat["last"] = now_iso()
            beat["phase"] = "watching"
            beat["source"] = None
            beat["started"] = beat["started"] or beat["last"]
            beat["cycles"] += 1
            store.save_state(st)
        return [r for r in results if r]

    def run_forever(self, stop=None):
        while not (stop and stop.is_set()):
            self.cycle()
            time.sleep(self.poll)
