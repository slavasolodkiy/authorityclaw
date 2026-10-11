"""Replays of the counterexamples found by the formal check.

Each test sets up the situation the solver produced and asserts the safe outcome,
running the real AuthorityClaw code end to end: invoice -> reader -> gate -> rail.
Against the pre-fix implementation used for the recorded challenge run (challenge
code commit 1c2a1cd), every F-test fails; with the fixes they all pass.
"""
import json
import math
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.pop("AUTHORITYCLAW_LLM_URL", None)

from authorityclaw import actions  # noqa: E402
from authorityclaw import extract as ex  # noqa: E402
from authorityclaw.agent import Agent  # noqa: E402

SUPPLIERS = {
    "Beanline Imports": ("11-22-33", "41235678"),
    "Hackney Dairy Co": ("22-33-44", "52346789"),
    "Brick Lane Packaging": ("33-44-55", "63457890"),
}


def demo_config():
    with open(os.path.join(actions.DEMO_DIR, "config.json"), encoding="utf-8") as f:
        return json.load(f)


class Harness(unittest.TestCase):
    def start(self, config=None):
        self.home = tempfile.mkdtemp()
        path = None
        if config is not None:
            path = os.path.join(self.home, "test-config.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(config, f)
        self.store = actions.reset(os.path.join(self.home, "state"), path)
        self.agent = Agent(self.store, poll=0)

    def tearDown(self):
        shutil.rmtree(getattr(self, "home", ""), ignore_errors=True)

    def invoice(self, payee, ref, amount):
        sort_code, account = SUPPLIERS[payee]
        text = (f"Invoice: {ref}\nPay to: {payee}\nSort code: {sort_code}\nAccount: {account}\n"
                f"Amount due: £{amount:,.2f}\nDescription: test\n")
        with open(os.path.join(self.store.inbox, f"{ref}.txt"), "w", encoding="utf-8") as f:
            f.write(text)
        out = self.agent.cycle()
        self.assertEqual(len(out), 1)
        return out[0]

    def invoice_read_by_model(self, payee, ref, amount_json):
        """Return a controlled model JSON response; amount_json is its raw numeric token."""
        sort_code, account = SUPPLIERS[payee]
        reply = ('{"payee": "%s", "invoice_ref": "%s", "amount": %s, "currency": "GBP", "sort_code": "%s", '
                 '"account": "%s", "due_date": "2026-10-20", "description": "test", '
                 '"suspicious_instructions": true}' % (payee, ref, amount_json, sort_code, account))
        env = {"AUTHORITYCLAW_LLM_URL": "http://model.invalid/v1", "AUTHORITYCLAW_LLM_MODEL": "local-model",
               "AUTHORITYCLAW_MODEL_NOTES": "0"}
        with patch.dict(os.environ, env), patch.object(ex, "call_llm", return_value=reply):
            with open(os.path.join(self.store.inbox, f"{ref}.txt"), "w", encoding="utf-8") as f:
                f.write(f"Invoice {ref} from {payee}\n")
            out = self.agent.cycle()
        self.assertEqual(len(out), 1)
        return out[0]

    def ledger_amounts(self):
        return [entry["amount"] for entry in self.store.ledger()]


class FormalFindings(Harness):
    def assert_weekly_limit_held(self):
        amounts = self.ledger_amounts()
        self.assertTrue(all(math.isfinite(a) and a > 0 for a in amounts),
                        f"a non-positive or non-finite amount reached the payment rail: {amounts}")
        paid = sum(a for a in amounts if math.isfinite(a) and a > 0)
        self.assertLessEqual(paid, 3000, f"the agent paid £{paid:,.2f} in one week; its limit is £3,000")

    def test_f1_nan_amount_is_refused_and_cannot_switch_off_the_weekly_limit(self):
        self.start()
        first = self.invoice_read_by_model("Hackney Dairy Co", "HD-NAN", "NaN")
        self.assertNotEqual(first["decision"], "ALLOW", "an amount of NaN was paid")
        for i in range(4):
            self.invoice("Hackney Dairy Co", f"HD-W{i}", 1000)
        self.assert_weekly_limit_held()

    def test_f2_negative_amount_is_refused_and_cannot_wind_back_the_weekly_count(self):
        self.start()
        first = self.invoice_read_by_model("Hackney Dairy Co", "HD-NEG", "-2000")
        self.assertNotEqual(first["decision"], "ALLOW", "a negative amount was paid")
        for i in range(4):
            self.invoice("Hackney Dairy Co", f"HD-W{i}", 1000)
        self.assert_weekly_limit_held()

    def test_f3_an_approver_cannot_exceed_their_own_weekly_limit(self):
        self.start()
        approved = 0.0
        for i in range(4):
            held = self.invoice("Brick Lane Packaging", f"BLP-{i}", 1500)
            self.assertEqual(held["decision"], "HOLD")
            out = actions.approve_hold(self.store, held["receipt"], by="tom")
            if out["decision"] == "APPROVED":
                approved += 1500
        self.assertLessEqual(approved, 5000, f"Tom approved £{approved:,.2f} this week; his limit is £5,000 a week")

    def test_f4_revocation_reaches_a_second_level_delegate(self):
        cfg = demo_config()
        cfg["delegations"].append({
            "id": "del-sam", "from": "tom", "to": "sam", "to_name": "Sam Reed", "role": "Accounts assistant",
            "source": "Delegation from Tom Hale (test)", "capacity": {"max_single": 1200, "max_weekly": 3000},
            "valid_until": "2026-12-31"})
        cfg["mandates"][0]["granted_by"] = "sam"
        self.start(cfg)
        held = self.invoice("Brick Lane Packaging", "BLP-SAM", 1100)
        self.assertEqual(held["decision"], "HOLD")
        actions.revoke(self.store, "del-tom", by="jane")
        out = actions.approve_hold(self.store, held["receipt"], by="sam")
        self.assertEqual(out["decision"], "REJECT")

    def test_f4b_removing_the_director_stops_a_second_level_delegate(self):
        cfg = demo_config()
        cfg["delegations"].append({
            "id": "del-sam", "from": "tom", "to": "sam", "to_name": "Sam Reed", "role": "Accounts assistant",
            "source": "Delegation from Tom Hale (test)", "capacity": {"max_single": 1200, "max_weekly": 3000},
            "valid_until": "2026-12-31"})
        cfg["mandates"][0]["granted_by"] = "sam"
        self.start(cfg)
        held = self.invoice("Brick Lane Packaging", "BLP-SAM2", 1100)
        actions.revoke(self.store, "jane", by="the board")
        self.assertEqual(actions.approve_hold(self.store, held["receipt"], by="sam")["decision"], "REJECT")

    def test_f5_the_director_can_be_asked_within_her_own_authority(self):
        self.start()
        out = self.invoice("Brick Lane Packaging", "BLP-2000", 2000)
        self.assertEqual(out["decision"], "HOLD")
        self.assertEqual(actions.approve_hold(self.store, out["receipt"], by="tom")["decision"], "REJECT")
        self.assertEqual(actions.approve_hold(self.store, out["receipt"], by="jane")["decision"], "APPROVED")

    def test_f6_authority_must_trace_back_to_an_officer(self):
        cfg = demo_config()
        cfg["delegations"][0]["from"] = "tom"
        self.start(cfg)
        out = self.invoice("Hackney Dairy Co", "HD-LOOP", 100)
        self.assertEqual(out["decision"], "REJECT")


class StillTrue(Harness):
    def test_revoking_tom_still_stops_a_one_level_chain(self):
        self.start()
        held = self.invoice("Brick Lane Packaging", "BLP-1", 1240)
        actions.revoke(self.store, "del-tom", by="jane")
        self.assertEqual(actions.approve_hold(self.store, held["receipt"], by="tom")["decision"], "REJECT")
        self.assertEqual(self.invoice("Hackney Dairy Co", "HD-1", 100)["decision"], "REJECT")

    def test_weekly_limit_holds_for_ordinary_amounts(self):
        self.start()
        decisions = [self.invoice("Hackney Dairy Co", f"HD-{i}", 1000)["decision"] for i in range(4)]
        self.assertEqual(decisions, ["ALLOW", "ALLOW", "ALLOW", "HOLD"])
        FormalFindings.assert_weekly_limit_held(self)


if __name__ == "__main__":
    unittest.main(verbosity=2)
