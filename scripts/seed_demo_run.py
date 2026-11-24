"""Create a demo run to try the review screen without an agent.

    venv/bin/python scripts/seed_demo_run.py [--owner someone@firm.com]

Makes one run for a made-up company (MFRS, Company level) and saves a full
balance sheet, profit or loss and cash flow statement through the figure
store's own functions, using the made-up figures in
`prototypes/review-prototype-v2.html`. Two things are left in on purpose:

- Other payables last year is saved as 389,200, a misreading of the printed
  398,200, so the balance sheet does not balance last year.
- Other receivables this year is marked unsure.

The owner defaults to the first admin account. Prints the new run's number.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv  # noqa: E402

from app import db  # noqa: E402
from app.catalog import loader  # noqa: E402
from app.figures import store  # noqa: E402
from app.runs import store as runs  # noqa: E402
from app.utils.paths import PROJECT_ROOT  # noqa: E402

COMPANY = "Seri Maju Trading Sdn. Bhd."
AGENT = store.Actor("agent", "seed")

# (template field: sheet, row), printed label, CY, PY, how it was saved.
# Amounts are as printed, with the sign of their effect on the total above
# them (outflows and expenses negative). "total" lines are printed totals.
SOFP = ("mfrs-company-sofp-cunoncu-v1", 7, [
    ("Non-current assets", None),
    (("SOFP-Sub-CuNonCu", 39), "Property, plant and equipment", 4812300, 4356900, "no_breakdown"),
    (("SOFP-CuNonCu", 11), "Right-of-use assets", 386400, 441600, None),
    (("SOFP-Sub-CuNonCu", 69), "Intangible assets", 92750, 110300, "no_breakdown"),
    (("SOFP-CuNonCu", 20), "Deferred tax assets", 64200, 58900, None),
    (("SOFP-CuNonCu", 23), "Total non-current assets", 5355650, 4967700, "printed"),
    ("Current assets", None),
    (("SOFP-Sub-CuNonCu", 136), "Inventories", 1947800, 1702450, "no_breakdown"),
    (("SOFP-Sub-CuNonCu", 139), "Trade receivables", 2385600, 2104300, None),
    (("SOFP-Sub-CuNonCu", 166), "Other receivables, deposits and prepayments", 318450, 276900, None),
    (("SOFP-Sub-CuNonCu", 182), "Cash and bank balances", 1264900, 986750, None),
    (("SOFP-CuNonCu", 36), "Total current assets", 5916750, 5070400, "printed"),
    (("SOFP-CuNonCu", 37), "Total assets", 11272400, 10038100, "printed"),
    ("Equity", None),
    (("SOFP-Sub-CuNonCu", 200), "Share capital", 2000000, 2000000, None),
    (("SOFP-CuNonCu", 41), "Retained earnings", 4618350, 3902700, None),
    (("SOFP-CuNonCu", 47), "Total equity", 6618350, 5902700, "printed"),
    ("Non-current liabilities", None),
    (("SOFP-Sub-CuNonCu", 269), "Borrowings", 1450000, 1680000, None),
    (("SOFP-CuNonCu", 52), "Lease liabilities", 298600, 352400, None),
    (("SOFP-CuNonCu", 57), "Deferred tax liabilities", 187300, 164800, None),
    (("SOFP-CuNonCu", 60), "Total non-current liabilities", 1935900, 2197200, "printed"),
    ("Current liabilities", None),
    (("SOFP-Sub-CuNonCu", 404), "Trade payables", 1628400, 1214650, None),
    (("SOFP-Sub-CuNonCu", 434), "Other payables and accruals", 512750, 389200, None),
    (("SOFP-Sub-CuNonCu", 381), "Borrowings", 420000, 230000, None),
    (("SOFP-CuNonCu", 63), "Lease liabilities", 88900, 53800, None),
    (("SOFP-CuNonCu", 66), "Current tax liabilities", 68100, 41550, None),
    (("SOFP-CuNonCu", 73), "Total current liabilities", 2718150, 1938200, "printed"),
    (("SOFP-CuNonCu", 74), "Total liabilities", 4654050, 4135400, "printed"),
    (("SOFP-CuNonCu", 75), "Total equity and liabilities", 11272400, 10038100, "printed"),
])
SOPL = ("mfrs-company-sopl-function-v1", 8, [
    (("SOPL-Analysis-Function", 15), "Revenue", 18642300, 16205800, None),
    (("SOPL-Analysis-Function", 42), "Cost of sales", -13208750, -11634200, None),
    (("SOPL-Function", 9), "Gross profit", 5433550, 4571600, "printed"),
    (("SOPL-Analysis-Function", 89), "Other income", 142600, 118300, None),
    (("SOPL-Function", 11), "Selling and distribution expenses", -1386400, -1242750, None),
    (("SOPL-Function", 12), "Administrative expenses", -2724900, -2318600, None),
    (("SOPL-Function", 17), "Finance costs", -128450, -141900, None),
    (("SOPL-Function", 20), "Profit before tax", 1336400, 986650, "printed"),
    (("SOPL-Function", 21), "Tax expense", -420750, -244350, None),
    (("SOPL-Function", 26), "Profit for the year", 915650, 742300, "printed"),
    # A company's whole profit belongs to its owners, even with no split printed.
    (("SOPL-Function", 28), "Profit for the year", 915650, 742300, None),
])
SOCF = ("mfrs-company-socf-indirect-v1", 10, [
    ("Operating activities", None),
    (("SOCF-Indirect", 8), "Profit before tax", 1336400, 986650, None),
    (("SOCF-Indirect", 11), "Depreciation", 612800, 574300, None),
    (("SOCF-Indirect", 22), "Finance costs", 128450, 141900, None),
    (("SOCF-Indirect", 74), "Changes in working capital", 48450, -47600, None),
    (("SOCF-Indirect", 73), "Tax paid", -394200, -251600, None),
    (("SOCF-Indirect", 75), "Net cash from operating activities", 1731900, 1403650, "printed"),
    ("Investing activities", None),
    (("SOCF-Indirect", 97), "Purchase of property, plant and equipment", -1013000, -688400, None),
    (("SOCF-Indirect", 107), "Net cash used in investing activities", -1013000, -688400, "printed"),
    ("Financing activities", None),
    (("SOCF-Indirect", 124), "Dividends paid", -200000, -150000, None),
    (("SOCF-Indirect", 120), "Repayment of borrowings", -40000, -210000, None),
    (("SOCF-Indirect", 109), "Payment of lease liabilities", -72300, -68900, None),
    (("SOCF-Indirect", 125), "Interest paid", -128450, -141900, None),
    (("SOCF-Indirect", 127), "Net cash used in financing activities", -440750, -570800, "printed"),
    (None, None),
    (("SOCF-Indirect", 130), "Net increase in cash", 278150, 144450, "printed"),
    (("SOCF-Indirect", 131), "Cash at beginning of year", 986750, 842300, None),
    (("SOCF-Indirect", 132), "Cash at end of year", 1264900, 986750, None),
])
_REASONS = {
    "Other receivables, deposits and prepayments": (
        "Note 11 includes 42,000 due from a director, which may belong in amounts due from related parties."),
    "Changes in working capital": "The report prints working capital changes as one line.",
}


def _concept(conn, template_id: str, sheet: str, row: int) -> str:
    found = conn.execute(
        "SELECT canonical_target_id FROM template_slots WHERE template_id = ? AND sheet = ? AND row = ?",
        (template_id, sheet, row)).fetchone()
    if found is None:
        raise SystemExit(f"The template {template_id} has no line at {sheet} row {row}.")
    return found[0]


def _sign(conn, concept_uuid: str) -> float:
    """+1 or -1: how the template's totals add this line (cost of sales is subtracted)."""
    up = conn.execute("SELECT coefficient FROM concept_edges WHERE child_uuid = ? ORDER BY id LIMIT 1",
                      (concept_uuid,)).fetchone()
    parent = conn.execute("SELECT parent_uuid FROM concept_edges WHERE child_uuid = ? ORDER BY id LIMIT 1",
                          (concept_uuid,)).fetchone()
    if up is None:
        return 1.0
    # Follow the first parent until a line no total adds up.
    return float(up[0]) * _sign(conn, parent[0])


def _writes(conn, statement) -> list[store.FigureWrite]:
    template_id, page, lines = statement
    writes, section = [], ""
    for order, item in enumerate(lines, start=1):
        if item[0] is None or isinstance(item[0], str):
            section = item[0] or ""
            continue
        (sheet, row), printed, cy, py, how = item
        concept = _concept(conn, template_id, sheet, row)
        sign = 1.0 if how == "printed" else _sign(conn, concept)
        for period, amount in (("CY", cy), ("PY", py)):
            value = amount * sign
            line = store.Line(printed, page, amount, order, sign, section)
            unsure = printed == "Other receivables, deposits and prepayments" and period == "CY"
            writes.append(store.FigureWrite(
                concept, period, "Company", value, [line], certainty="unsure" if unsure else "sure",
                reason=_REASONS.get(printed, "") if (unsure or printed in _REASONS) else "",
                total=how if how in ("printed", "no_breakdown") else None))
    return writes


def seed(owner: str | None = None) -> int:
    loader.load_catalogue()
    with db.connect(immediate=True) as conn:
        if owner is None:
            admin = conn.execute("SELECT email FROM users WHERE is_admin = 1 AND disabled = 0 "
                                 "ORDER BY created_at LIMIT 1").fetchone()
            if admin is None:
                raise SystemExit("There is no admin account to own the run; pass --owner.")
            owner = admin[0]
        elif conn.execute("SELECT 1 FROM users WHERE email = ?", (owner.strip().lower(),)).fetchone() is None:
            raise SystemExit(f"There is no account for {owner}; create it first.")
        owner = owner.strip().lower()
        run_id = runs.create_run(
            conn, company=COMPANY, year=2025, standard="MFRS", level="Company", owner_email=owner,
            statements=[("SOFP", "CuNonCu"), ("SOPL", "Function"), ("SOCF", "Indirect")], status="in_review")
        for statement in (SOFP, SOPL, SOCF):
            for result in store.save_figures(conn, run_id, _writes(conn, statement), AGENT):
                if not result["ok"]:
                    raise SystemExit(f"A demo figure was refused: {result['refused']}")
    return run_id


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--owner", help="email of the account that owns the run")
    args = parser.parse_args()
    load_dotenv(PROJECT_ROOT / ".env")
    db.init_db()
    print(f"Created demo run {seed(args.owner)}: {COMPANY}")


if __name__ == "__main__":
    main()
