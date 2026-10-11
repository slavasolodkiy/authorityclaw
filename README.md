<!-- ============================================================
     AUTHORITYCLAW · README
     Teenage-Engineering × Nothing × acid-glitch aesthetic
     Sovereign Agent Lab · design system v2
     ============================================================ -->

<div align="center">

<pre>
 █████╗  ██╗   ██╗████████╗██╗  ██╗ ██████╗ ██████╗ ██╗████████╗██╗   ██╗
██╔══██╗ ██║   ██║╚══██╔══╝██║  ██║██╔═══██╗██╔══██╗██║╚══██╔══╝╚██╗ ██╔╝
███████║ ██║   ██║   ██║   ███████║██║   ██║██████╔╝██║   ██║    ╚████╔╝
██╔══██║ ██║   ██║   ██║   ██╔══██║██║   ██║██╔══██╗██║   ██║     ╚██╔╝
██║  ██║ ╚██████╔╝   ██║   ██║  ██║╚██████╔╝██║  ██║██║   ██║      ██║
╚═╝  ╚═╝  ╚═════╝    ╚═╝   ╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═╝╚═╝   ╚═╝      ╚═╝
 ▄▄· ▄▄▌  ▄▄▌
▐█ ▌▪██•  ██•       THE MODEL READS · THE GATE DECIDES
██ ▄▄██ ▪ ██ ▪      THE AGENT CANNOT AUTHORISE ITSELF
▐███▌▐█▌ ▄▐█▌ ▄
·▀▀▀ .▀▀▀ .▀▀▀
</pre>

# `AUTHORITYCLAW`

**A long-running payments agent with a deterministic authority gate:** the model reads invoices, but every proposed payment must pass the gate before the simulated payment rail will execute it.

<img src="https://img.shields.io/badge/NVIDIA%20CLAW%20CHALLENGE-FIRST%20PLACE%20%C2%B7%20LONDON%202026-ff9500?style=for-the-badge&labelColor=0b0d11" alt="first place">
<img src="https://img.shields.io/badge/DECISIONS-ALLOW%20%C2%B7%20HOLD%20%C2%B7%20REJECT-c8ff00?style=for-the-badge&labelColor=0b0d11" alt="decisions">
<img src="https://img.shields.io/badge/RECEIPTS-tamper--evident-35f2ff?style=for-the-badge&labelColor=0b0d11" alt="receipts">
<img src="https://img.shields.io/badge/FORMAL%20MIRROR-Z3--checked-9b7bff?style=for-the-badge&labelColor=0b0d11" alt="formal">
<img src="https://img.shields.io/badge/PYTHON-3.10%2B%20%C2%B7%20zero%20demo%20deps-00e676?style=for-the-badge&labelColor=0b0d11" alt="python">

[Project page](https://www.solodkiy.cv/authorityclaw.html) · [Full research trail — Sovereign Agent Lab](https://www.solodkiy.cv/sovereign-agent-lab.html)

</div>

---

![Recorded challenge dashboard](docs/verified-dashboard.png)

## ▚ THE GATE IN ONE BREATH

AuthorityClaw is a long-running accounts-payable agent for a fictional small business. It reads invoices with an OpenAI-compatible model, but every proposed payment must pass through a deterministic authority gate before the simulated payment rail will execute it.

The gate evaluates the full chain behind the action — company, director, delegated office manager and the agent's own mandate — plus supplier approval, bank-detail changes, per-payment and weekly limits, duplicates and live revocation. Every outcome is **ALLOW**, **HOLD** or **REJECT**, with a tamper-evident receipt.

```text
 INVOICE INBOX        EXTRACTION            AUTHORITY GATE           PAYMENT RAIL
 ┌──────────┐   ┌──────────────────┐   ┌──────────────────────┐   ┌──────────────┐
 │ unread   │──►│ model reads      │──►│ deterministic checks │──►│ simulated    │
 │ invoices │   │ facts + flags    │   │ chain·supplier·limits│   │ execution    │
 │          │   │ injections       │   │ ALLOW/HOLD/REJECT    │   │ gated by     │
 └──────────┘   │ (rules fallback) │   │ + hash receipt       │   │ valid receipt│
                └──────────────────┘   └──────────────────────┘   └──────────────┘
                     proposes only           decides always            never decides
```

The authority chain can only narrow on its way down. Revoke any rung and everything below it stops:

```text
Northside Roasters Ltd ── the company
       │
Jane Okafor ── Director · up to £25,000 a payment, £50,000 a week
       │
Tom Hale ── Office manager · up to £1,500 a payment, £5,000 a week   ✕ REVOKED
       │
Payments agent ── approved invoices · up to £1,000 a payment, £3,000 a week
                   No authority: a rung above is revoked
```

## ▚ RECORDED CHALLENGE RUN

The NVIDIA London Claw Agent Challenge snapshot ran on an Olares One with an NVIDIA GeForce RTX 5090 Laptop GPU (24 GB) and the local `unsloth/Qwen3.6-27B-GGUF:Q4_K_M` model through `llama.cpp`.

- 4/4 end-to-end tests passed
- six invoices were read by the local model
- seven decision receipts were written
- the receipt chain verified successfully
- all payments were simulated; no real money moved

NVIDIA awarded the demonstration First Place. This is external recognition of the work, **not** an independent technical validation, compliance certification or regulatory approval.

The recorded run used AuthorityClaw's own persistent Python harness and called the existing local model service directly. An OpenClaw-compatible skill is included under `skills/authority-gate`. The Olares Market NemoClaw package and OpenShell were present on the same machine, but NemoClaw/OpenClaw runtime integration is not claimed for this recorded run.

## ▚ WHY IT MATTERS

A sandbox can control what an agent can technically reach. It does not prove that the organisation still authorises the action. AuthorityClaw makes that second question explicit and executable.

| SCENARIO | DECISION |
|---|---|
| Routine approved invoices | `ALLOW` and simulated payment |
| Known supplier changes bank details | `HOLD` for independent verification |
| Unapproved £4,900 invoice contains a prompt injection | `REJECT`; invoice instructions remain untrusted data |
| £1,240 exceeds the agent's limit but fits Tom's | `HOLD`, then human approval and payment |
| Jane revokes Tom while the agent remains running | next normal invoice is immediately `REJECT` |
| A past receipt is modified | chain verification identifies the break |

## ▚ POST-CHALLENGE FORMAL CHECK

The four original scenario tests covered the demo story, not every possible input. After the challenge, the authority rules were mirrored as first-order formulas and checked with Z3. The audit found six edge cases in the pre-fix implementation used for the recorded run; every counterexample was replayed against the real Python code, fixed, and kept as a regression test.

| FINDING | CURRENT RULE |
|---|---|
| `NaN`, infinite, zero or negative amounts could bypass comparisons | Amounts must be positive and finite in both the gate and the payment rail |
| A human approver's weekly limit was not accumulated | Every payment is counted against every authority link it uses |
| Revocation did not always reach a second-level delegate | Approval checks the approver's complete chain |
| An amount within the director's capacity could be refused instead of escalated | A hold is routed to the lowest person in the chain who can authorise it |
| A self-referential delegation could fail to reach an officer | Every authority chain must terminate at an officer of the company |

The formal model is a hand-written mirror of the implementation, not an automatic proof of all Python code. The useful link is the replay: each solver counterexample must reproduce against the implementation and remain covered by tests. Under the published bounds, the current formal model satisfies eight stated properties, including recursive revocation and weekly-limit invariants. Autonomous payments executed solely under the agent mandate do not exceed its £3,000 weekly limit; a human may separately approve a held payment under their own live authority.

```bash
pip install z3-solver
python3 formal/check_authority.py --rules current
```

Full property table and bounds: [`formal/RESULTS.md`](formal/RESULTS.md).

## ▚ QUICK START

Python 3.10+; no third-party Python dependencies for the demo itself.

```bash
python3 -m unittest discover -s tests
python3 -m authorityclaw reset
python3 -m authorityclaw run --poll 2 --host 127.0.0.1
```

In a second terminal:

```bash
python3 -m authorityclaw feed --delay 2 --only 01 02 03 04 05
# Use the dashboard to approve the held Brick Lane invoice and revoke Tom.
python3 -m authorityclaw feed --only 06
python3 -m authorityclaw verify
```

The dashboard opens at `http://127.0.0.1:8765` by default. Do not bind it to a public interface: this competition prototype has no authentication.

## ▚ USE A MODEL

AuthorityClaw accepts any OpenAI-compatible Chat Completions endpoint:

```bash
export AUTHORITYCLAW_LLM_URL="https://example.invalid/v1"
export AUTHORITYCLAW_LLM_MODEL="your-model-id"
export AUTHORITYCLAW_LLM_KEY="optional-api-key"
python3 -m authorityclaw run --poll 2 --host 127.0.0.1
```

The model extracts invoice facts and flags suspicious instructions. It never grants authority and never sends a payment directly. Without a model, an explicit rules fallback keeps the demo reproducible and labels itself honestly in the dashboard.

## ▚ OPENCLAW-COMPATIBLE SKILL

Copy `skills/authority-gate` into an OpenClaw workspace's `skills` directory. The skill instructs an agent to process payments only through:

```bash
python3 -m authorityclaw pay --file <invoice>
```

Keep `AUTHORITYCLAW_HOME` outside any directory the agent may edit. The payment rail rejects execution without a valid gate receipt.

## ▚ REPOSITORY MAP

```text
├── authorityclaw/agent.py              # long-running inbox loop
├── authorityclaw/extract.py            # model-backed extraction and explicit fallback
├── authorityclaw/gate.py               # deterministic authority and payment checks
├── authorityclaw/rail.py               # simulated receipt-gated payment rail
├── authorityclaw/store.py              # state, ledger and hash-chained receipts
├── authorityclaw/server.py             # dashboard server
├── authorityclaw/web/index.html        # dashboard
├── skills/authority-gate/SKILL.md      # OpenClaw-compatible skill
├── tests/                              # end-to-end scenarios + replayed solver counterexamples
├── formal/                             # bounded first-order model, checks and results
└── evidence/                           # sanitised run summaries
```

## ▚ COLOPHON

The company, people, invoices, suppliers and bank details are **fictional**. Built by **Vladislav (Slava) Solodkiy** in London for the 2026 NVIDIA London Claw Agent Challenge. MIT licence.

<div align="center">

`THE MODEL READS · THE GATE DECIDES · THE CHAIN IS INTACT`

</div>
