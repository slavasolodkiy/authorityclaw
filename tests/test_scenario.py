import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.pop("AUTHORITYCLAW_LLM_URL", None)

from authorityclaw import actions, rail  # noqa: E402
from authorityclaw.agent import Agent  # noqa: E402
from authorityclaw.store import Store  # noqa: E402

INVOICES = os.path.join(actions.DEMO_DIR, "invoices")


def drop(store, prefix):
    name = next(n for n in sorted(os.listdir(INVOICES)) if n.startswith(prefix))
    shutil.copy(os.path.join(INVOICES, name), os.path.join(store.inbox, name))


class DemoStory(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.store = actions.reset(self.home)
        self.agent = Agent(self.store, poll=0)

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def decide(self, prefix):
        drop(self.store, prefix)
        out = self.agent.cycle()
        self.assertEqual(len(out), 1)
        return out[0]

    def codes(self, event):
        return {r["code"] for r in event["reasons"]}

    def test_full_story(self):
        self.assertEqual(self.decide("01")["decision"], "ALLOW")
        self.assertEqual(self.decide("02")["decision"], "ALLOW")

        held = self.decide("03")
        self.assertEqual(held["decision"], "HOLD")
        self.assertIn("bank_details_changed", self.codes(held))

        injected = self.decide("04")
        self.assertEqual(injected["decision"], "REJECT")
        self.assertTrue(injected["injection"])
        self.assertIn("payee_not_approved", self.codes(injected))

        over = self.decide("05")
        self.assertEqual(over["decision"], "HOLD")
        self.assertIn("above_agent_limit", self.codes(over))

        approved = actions.approve_hold(self.store, over["receipt"], by="tom")
        self.assertEqual(approved["decision"], "APPROVED")
        self.assertTrue(approved["payment_id"].startswith("FP-"))

        declined = actions.decline_hold(self.store, held["receipt"], by="tom")
        self.assertEqual(declined["decision"], "DECLINED")

        actions.revoke(self.store, "del-tom", by="jane")
        after = self.decide("06")
        self.assertEqual(after["decision"], "REJECT")
        self.assertIn("delegation_revoked", self.codes(after))

        dup = self.decide("07")
        self.assertEqual(dup["decision"], "REJECT")
        self.assertIn("duplicate", self.codes(dup))

        ledger = self.store.ledger()
        self.assertEqual([e["invoice_ref"] for e in ledger], ["INV-2291", "HD-7710", "BLP-0932"])
        st = self.store.state()
        self.assertAlmostEqual(sum(st["weekly"].values()), 2092.40, places=2)
        self.assertTrue(self.store.verify_chain()[0])

    def test_revoked_person_cannot_approve(self):
        over = self.decide("05")
        actions.revoke(self.store, "del-tom", by="jane")
        attempt = actions.approve_hold(self.store, over["receipt"], by="tom")
        self.assertEqual(attempt["decision"], "REJECT")
        jane = actions.approve_hold(self.store, over["receipt"], by="jane")
        self.assertEqual(jane["decision"], "APPROVED")

    def test_rail_refuses_without_receipt(self):
        st = self.store.state()
        fake = {"id": "R9999", "decision": "HOLD"}
        with self.assertRaises(PermissionError):
            rail.execute(self.store, st, fake, {"payee": "x", "amount": 1, "sort_code": "1", "account": "1",
                                                "invoice_ref": "x"})

    def test_tampering_breaks_the_chain(self):
        self.decide("01")
        self.decide("02")
        path = self.store.paths["receipts"]
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
        rec = json.loads(lines[0])
        rec["action"]["amount"] = 64000
        lines[0] = json.dumps(rec, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        self.assertFalse(self.store.verify_chain()[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
