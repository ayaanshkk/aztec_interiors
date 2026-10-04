"""
One-time migration: renumber all existing invoices, proformas, and quotations
to the new AL-INV-XXXXXX / AL-PRO-XXXXXX / AL-QT-XXXXXX format.

Run from the backend directory:
    python -m backend.migrate_numbering

Records are renumbered per-tenant, ordered by their original ID (oldest first),
so the lowest-ID document gets -000001, the next gets -000002, etc.

Safe to re-run — if a record already matches the new format it is skipped.
"""

import sys
import os

# Allow running as `python backend/migrate_numbering.py` from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import text
from backend.db import SessionLocal


def renumber_invoices_all(session, dry_run: bool) -> int:
    """Renumber ALL regular invoices globally (unique constraint spans all tenants)."""
    rows = session.execute(text("""
        SELECT invoice_id, invoice_number, tenant_id
        FROM "StreemLyne_MT"."Invoice_Master"
        WHERE invoice_number NOT LIKE 'AL-PRO-%'
        ORDER BY invoice_id ASC
    """)).fetchall()

    to_update = []
    for seq, row in enumerate(rows, start=1):
        new_num = f"AL-INV-{seq:06d}"
        if row.invoice_number != new_num:
            to_update.append((row.invoice_id, row.invoice_number, new_num))

    for inv_id, old_num, new_num in to_update:
        print(f"  Invoice {inv_id}: {old_num!r} → {new_num!r}")

    if not dry_run and to_update:
        # Phase 1: move to temp names to avoid unique conflicts mid-update
        for inv_id, old_num, new_num in to_update:
            session.execute(text("""
                UPDATE "StreemLyne_MT"."Invoice_Master"
                SET invoice_number = :tmp
                WHERE invoice_id = :id
            """), {"tmp": f"_MIGR_{inv_id}", "id": inv_id})
        # Phase 2: set final names
        for inv_id, old_num, new_num in to_update:
            session.execute(text("""
                UPDATE "StreemLyne_MT"."Invoice_Master"
                SET invoice_number = :new
                WHERE invoice_id = :id
            """), {"new": new_num, "id": inv_id})

    return len(to_update)


def renumber_proformas_all(session, dry_run: bool) -> int:
    """Renumber ALL proformas globally."""
    rows = session.execute(text("""
        SELECT invoice_id, invoice_number
        FROM "StreemLyne_MT"."Invoice_Master"
        WHERE invoice_number LIKE 'PRO-%'
           OR invoice_number LIKE 'AL-PRO-%'
        ORDER BY invoice_id ASC
    """)).fetchall()

    to_update = []
    for seq, row in enumerate(rows, start=1):
        new_num = f"AL-PRO-{seq:06d}"
        if row.invoice_number != new_num:
            to_update.append((row.invoice_id, row.invoice_number, new_num))

    for inv_id, old_num, new_num in to_update:
        print(f"  Proforma {inv_id}: {old_num!r} → {new_num!r}")

    if not dry_run and to_update:
        for inv_id, old_num, new_num in to_update:
            session.execute(text("""
                UPDATE "StreemLyne_MT"."Invoice_Master"
                SET invoice_number = :tmp
                WHERE invoice_id = :id
            """), {"tmp": f"_MIGR_PRO_{inv_id}", "id": inv_id})
        for inv_id, old_num, new_num in to_update:
            session.execute(text("""
                UPDATE "StreemLyne_MT"."Invoice_Master"
                SET invoice_number = :new
                WHERE invoice_id = :id
            """), {"new": new_num, "id": inv_id})

    return len(to_update)


def renumber_quotations_all(session, dry_run: bool) -> int:
    """Renumber ALL quotations globally (unique constraint spans all tenants)."""
    rows = session.execute(text("""
        SELECT quotation_id, reference_number, tenant_id
        FROM "StreemLyne_MT"."Quotations"
        ORDER BY quotation_id ASC
    """)).fetchall()

    to_update = []
    for seq, row in enumerate(rows, start=1):
        new_num = f"AL-QT-{seq:06d}"
        if row.reference_number != new_num:
            to_update.append((row.quotation_id, row.reference_number, new_num))

    for qt_id, old_num, new_num in to_update:
        print(f"  Quote {qt_id}: {old_num!r} → {new_num!r}")

    if not dry_run and to_update:
        # Phase 1: move to temp names to avoid unique conflicts mid-update
        for qt_id, old_num, new_num in to_update:
            session.execute(text("""
                UPDATE "StreemLyne_MT"."Quotations"
                SET reference_number = :tmp
                WHERE quotation_id = :id
            """), {"tmp": f"_MIGR_{qt_id}", "id": qt_id})
        # Phase 2: set final names
        for qt_id, old_num, new_num in to_update:
            session.execute(text("""
                UPDATE "StreemLyne_MT"."Quotations"
                SET reference_number = :new
                WHERE quotation_id = :id
            """), {"new": new_num, "id": qt_id})

    return len(to_update)


def run(dry_run: bool = False):
    mode = "DRY RUN (no changes written)" if dry_run else "LIVE (changes will be committed)"
    print(f"\n{'='*60}")
    print(f"  Numbering migration — {mode}")
    print(f"{'='*60}\n")

    session = SessionLocal()
    try:
        print("-- Invoices (all tenants) --")
        total_inv = renumber_invoices_all(session, dry_run)

        print("\n-- Proformas (all tenants) --")
        total_pro = renumber_proformas_all(session, dry_run)

        print("\n-- Quotations (all tenants) --")
        total_qt = renumber_quotations_all(session, dry_run)

        if not dry_run:
            session.commit()
            print(f"\n✅ Committed. Updated: {total_inv} invoices, {total_pro} proformas, {total_qt} quotations.")
        else:
            print(f"\n✅ Dry-run complete. Would update: {total_inv} invoices, {total_pro} proformas, {total_qt} quotations.")
            print("   Re-run with --live to apply changes.")

    except Exception as e:
        session.rollback()
        print(f"\n❌ Error — rolled back: {e}")
        raise
    finally:
        session.close()


if __name__ == "__main__":
    dry_run = "--live" not in sys.argv
    run(dry_run=dry_run)
