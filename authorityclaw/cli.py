"""python -m authorityclaw <command>"""
import argparse
import json
import os
import shutil
import sys
import time
import urllib.request

from . import actions
from .agent import Agent
from .store import Store

DEFAULT_HOME = os.environ.get("AUTHORITYCLAW_HOME", os.path.join(os.getcwd(), "authorityclaw-state"))
INVOICES = os.path.join(actions.DEMO_DIR, "invoices")


def _api(port, path, payload):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.load(resp)


def _via_server_or_direct(args, path, payload, direct):
    try:
        return _api(args.port, path, payload)
    except OSError:
        return direct()


def main(argv=None):
    p = argparse.ArgumentParser(prog="authorityclaw", description="A payments agent that can only pay within its mandate.")
    p.add_argument("--home", default=DEFAULT_HOME, help="state directory (default: $AUTHORITYCLAW_HOME or ./authorityclaw-state)")
    p.add_argument("--port", type=int, default=8765)
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="run the long-running agent (and the dashboard)")
    r.add_argument("--poll", type=float, default=3.0)
    r.add_argument("--host", default="127.0.0.1", help="use 0.0.0.0 to open the dashboard from another device")
    r.add_argument("--no-dashboard", action="store_true")

    sub.add_parser("reset", help="start fresh with the demo company, people and mandate")
    f = sub.add_parser("feed", help="drop demo invoices into the inbox one by one")
    f.add_argument("--delay", type=float, default=6.0)
    f.add_argument("--only", nargs="*", help="invoice number prefixes, e.g. 01 02 06")
    pay = sub.add_parser("pay", help="process one invoice file now (used by the OpenClaw skill)")
    pay.add_argument("--file", required=True)
    for name in ("approve", "decline"):
        a = sub.add_parser(name, help=f"{name} a held payment")
        a.add_argument("hold_id")
        a.add_argument("--by", default="tom")
    for name in ("revoke", "restore"):
        a = sub.add_parser(name, help=f"{name} a mandate, delegation or office by id (e.g. del-tom)")
        a.add_argument("target_id")
        a.add_argument("--by", default="jane")
    sub.add_parser("verify", help="check the receipt hash chain")
    sub.add_parser("status", help="print the authority chain and today's position")
    args = p.parse_args(argv)

    if args.cmd == "reset":
        actions.reset(args.home)
        print(f"Reset. Demo company loaded into {args.home}")
        return 0

    store = Store(args.home)
    if not store.config():
        actions.reset(args.home)
        store = Store(args.home)

    if args.cmd == "run":
        agent = Agent(store, poll=args.poll)
        if not args.no_dashboard:
            from .server import serve
            serve(store, args.host, args.port)
            print(f"Dashboard: http://{'127.0.0.1' if args.host in ('127.0.0.1', '0.0.0.0') else args.host}:{args.port}"
                  + ("  (also reachable from other devices on your network)" if args.host == "0.0.0.0" else ""))
        print(f"Watching {store.inbox} every {args.poll:g}s. Ctrl+C to stop.")
        try:
            agent.run_forever()
        except KeyboardInterrupt:
            print("\nStopped.")
        return 0

    if args.cmd == "feed":
        files = sorted(os.listdir(INVOICES))
        if args.only:
            files = [n for n in files if any(n.startswith(prefix) for prefix in args.only)]
        for i, name in enumerate(files):
            shutil.copy(os.path.join(INVOICES, name), os.path.join(store.inbox, name))
            print(f"-> inbox: {name}")
            if i < len(files) - 1:
                time.sleep(args.delay)
        return 0

    if args.cmd == "pay":
        target = os.path.join(store.inbox, os.path.basename(args.file))
        shutil.copy(args.file, target)
        results = Agent(store).cycle()
        print(json.dumps(results[-1] if results else {"note": "already processed"}, indent=2, ensure_ascii=False))
        return 0

    if args.cmd in ("approve", "decline"):
        fn = actions.approve_hold if args.cmd == "approve" else actions.decline_hold
        out = _via_server_or_direct(args, f"/api/holds/{args.hold_id}/{args.cmd}", {"by": args.by},
                                    lambda: fn(store, args.hold_id, args.by))
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 0

    if args.cmd in ("revoke", "restore"):
        fn = actions.revoke if args.cmd == "revoke" else actions.restore
        out = _via_server_or_direct(args, f"/api/{args.cmd}", {"id": args.target_id, "by": args.by},
                                    lambda: fn(store, args.target_id, args.by))
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 0

    if args.cmd == "verify":
        ok, bad, count, last = store.verify_chain()
        print(f"{'OK' if ok else 'BROKEN'}: {count} receipts, chain head {last[:16]}" + ("" if ok else f", first bad {bad}"))
        return 0 if ok else 1

    if args.cmd == "status":
        snap = actions.snapshot(store)
        for link in snap["chain"]:
            lim = link.get("limits", {})
            print(f"{link['holder']:<28} {link['role']:<32} £{lim.get('max_single', 0):>8,.0f} per payment"
                  f"  £{lim.get('max_weekly', 0):>8,.0f} a week  [{link['status']}]")
        print(f"This week: £{snap['week_spent']:,.2f} of £{snap['limits'].get('max_weekly', 0):,.0f}"
              f"  payments: {snap['payments']}  open holds: {len(snap['open_holds'])}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
