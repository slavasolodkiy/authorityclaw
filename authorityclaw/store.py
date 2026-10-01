"""File-backed state for AuthorityClaw: config, working state, receipts, ledger."""
import hashlib
import json
import os
import tempfile
import threading
from datetime import datetime, timezone


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def canon(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


GENESIS = "0" * 64


class Store:
    def __init__(self, home):
        self.home = os.path.abspath(home)
        self.lock = threading.RLock()
        self.inbox = os.path.join(self.home, "inbox")
        self.done = os.path.join(self.home, "processed")
        self.outbox = os.path.join(self.home, "outbox")
        for d in (self.home, self.inbox, self.done, self.outbox):
            os.makedirs(d, exist_ok=True)
        self.paths = {
            "config": os.path.join(self.home, "config.json"),
            "state": os.path.join(self.home, "state.json"),
            "receipts": os.path.join(self.home, "receipts.jsonl"),
            "ledger": os.path.join(self.home, "ledger.jsonl"),
        }

    # ---- json helpers -------------------------------------------------
    def _read(self, key, default):
        path = self.paths[key]
        if not os.path.exists(path):
            return default
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def _write(self, key, obj):
        fd, tmp = tempfile.mkstemp(dir=self.home, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=2, ensure_ascii=False)
        os.replace(tmp, self.paths[key])

    def _lines(self, key):
        path = self.paths[key]
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    # ---- config & state -----------------------------------------------
    def config(self):
        with self.lock:
            return self._read("config", {})

    def write_config(self, cfg):
        with self.lock:
            self._write("config", cfg)

    @staticmethod
    def empty_state():
        return {
            "revoked": {},      # id -> {"by": name, "ts": iso}
            "suppliers": {},    # payee -> payment memory
            "weekly": {},       # ISO week -> total paid
            "paid_refs": {},    # "payee|invoice_ref" -> payment id
            "processed": {},    # source sha256 -> receipt id
            "holds": {},        # receipt id -> hold record
            "events": [],
            "heartbeat": {"started": None, "last": None, "cycles": 0, "handled": 0},
        }

    def state(self):
        with self.lock:
            return self._read("state", self.empty_state())

    def save_state(self, st):
        with self.lock:
            st["events"] = st["events"][-300:]
            self._write("state", st)

    # ---- receipts: an append-only hash chain --------------------------
    def receipts(self):
        return self._lines("receipts")

    def append_receipt(self, body):
        with self.lock:
            chain = self.receipts()
            rec = dict(body)
            rec["seq"] = len(chain) + 1
            rec["id"] = f"R{rec['seq']:04d}"
            rec["ts"] = now_iso()
            rec["prev_hash"] = chain[-1]["hash"] if chain else GENESIS
            rec["hash"] = sha256_text(canon(rec))
            with open(self.paths["receipts"], "a", encoding="utf-8") as f:
                f.write(canon(rec) + "\n")
            return rec

    def verify_chain(self):
        """Returns (ok, first_bad_id, count, last_hash)."""
        prev, chain = GENESIS, self.receipts()
        for rec in chain:
            body = {k: v for k, v in rec.items() if k != "hash"}
            if rec.get("prev_hash") != prev or sha256_text(canon(body)) != rec.get("hash"):
                return False, rec.get("id"), len(chain), prev
            prev = rec["hash"]
        return True, None, len(chain), prev

    # ---- ledger ---------------------------------------------------------
    def ledger(self):
        return self._lines("ledger")

    def append_ledger(self, entry):
        with self.lock:
            with open(self.paths["ledger"], "a", encoding="utf-8") as f:
                f.write(canon(entry) + "\n")
