from flask import Blueprint, request, jsonify, current_app
from sqlalchemy import text
import json

from ..db import SessionLocal
from .auth_helpers import token_required, require_tenant

financial_docs_bp = Blueprint("financial_docs", __name__)


@financial_docs_bp.route("/financial-docs/receipts/<int:submission_id>", methods=["DELETE"])
@token_required
@require_tenant
def delete_receipt(submission_id, tenant_id, employee_id):
    """Delete a receipt form submission."""
    session = SessionLocal()
    try:
        result = session.execute(
            text("""
                DELETE FROM "StreemLyne_MT"."Customer_Form_Submissions"
                WHERE form_submission_id = :id AND tenant_id = :tid
                RETURNING form_submission_id
            """),
            {"id": submission_id, "tid": str(tenant_id)},
        ).fetchone()
        if not result:
            return jsonify({"error": "Not found"}), 404
        session.commit()
        return jsonify({"success": True}), 200
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error deleting receipt {submission_id}: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()


def _ilike(value: str) -> str:
    return f"%{value.strip()}%"


@financial_docs_bp.route("/financial-docs", methods=["GET"])
@token_required
@require_tenant
def list_financial_docs(tenant_id, employee_id):
    """
    Tenant-wide listing for any financial document type.
    Query params:
      type        : quotations | invoices | proformas | payment-terms |
                    receipts | deposit-receipts | final-receipts
      page        : int (default 1)
      per_page    : int (default 20)
      search      : doc number or customer name
      status      : exact status string
      room        : room name (partial match)
    """
    doc_type = request.args.get("type", "quotations").lower()
    page = max(1, int(request.args.get("page", 1)))
    per_page = min(100, max(1, int(request.args.get("per_page", 20))))
    offset = (page - 1) * per_page
    search = request.args.get("search", "").strip()
    status = request.args.get("status", "").strip()
    room = request.args.get("room", "").strip()

    session = SessionLocal()
    try:
        if doc_type == "quotations":
            return _list_quotations(session, tenant_id, page, per_page, offset, search, status, room)
        elif doc_type == "invoices":
            return _list_invoices(session, tenant_id, page, per_page, offset, search, status, room, "invoice")
        elif doc_type == "proformas":
            return _list_invoices(session, tenant_id, page, per_page, offset, search, status, room, "proforma")
        elif doc_type == "payment-terms":
            return _list_payment_terms(session, tenant_id, page, per_page, offset, search, status, room)
        elif doc_type in ("receipts", "deposit-receipts", "final-receipts"):
            receipt_subtype = {
                "receipts": "receipt",
                "deposit-receipts": "deposit",
                "final-receipts": "final",
            }[doc_type]
            return _list_receipts(session, tenant_id, page, per_page, offset, search, status, room, receipt_subtype)
        else:
            return jsonify({"error": f"Unknown doc type: {doc_type}"}), 400
    except Exception as e:
        current_app.logger.exception(f"Error listing financial docs ({doc_type}): {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()


# ── Quotations ────────────────────────────────────────────────────────────────

def _list_quotations(session, tenant_id, page, per_page, offset, search, status, room):
    where = ["q.tenant_id = :tenant_id"]
    params: dict = {"tenant_id": str(tenant_id)}

    if search:
        where.append("(q.reference_number ILIKE :search OR c.client_company_name ILIKE :search)")
        params["search"] = _ilike(search)
    if status:
        where.append("q.status = :status")
        params["status"] = status
    if room:
        where.append("q.room_name ILIKE :room")
        params["room"] = _ilike(room)

    w = " AND ".join(where)

    counts = session.execute(text(f"""
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN LOWER(q.status) = 'draft'  THEN 1 ELSE 0 END) AS drafts,
            SUM(CASE WHEN LOWER(q.status) != 'draft' THEN 1 ELSE 0 END) AS sent
        FROM "StreemLyne_MT"."Quotations" q
        INNER JOIN "StreemLyne_MT"."Client_Master" c ON q.client_id = c.client_id
        WHERE {w}
    """), params).fetchone()

    rooms_rows = session.execute(text(f"""
        SELECT DISTINCT q.room_name
        FROM "StreemLyne_MT"."Quotations" q
        INNER JOIN "StreemLyne_MT"."Client_Master" c ON q.client_id = c.client_id
        WHERE {w} AND q.room_name IS NOT NULL AND q.room_name != ''
        ORDER BY q.room_name
    """), params).fetchall()

    rows = session.execute(text(f"""
        SELECT q.quotation_id, q.reference_number, q.quote_reference,
               q.client_id, c.client_company_name,
               q.room_name, q.status, q.created_at,
               COALESCE((
                   SELECT SUM(
                       CASE WHEN COALESCE(discount_percent, 0) > 0
                            THEN COALESCE(discounted_amount, amount * quantity)
                            ELSE amount * quantity
                       END
                   )
                   FROM "StreemLyne_MT"."Quotation_Items"
                   WHERE quotation_id = q.quotation_id
               ), 0) AS subtotal,
               COALESCE(q.global_discount_percent, 0) AS discount_pct,
               COALESCE(q.vat_percentage, 20) AS vat_pct
        FROM "StreemLyne_MT"."Quotations" q
        INNER JOIN "StreemLyne_MT"."Client_Master" c ON q.client_id = c.client_id
        WHERE {w}
        ORDER BY q.created_at DESC
        LIMIT :lim OFFSET :off
    """), {**params, "lim": per_page, "off": offset}).fetchall()

    # Unfiltered status breakdown
    status_rows = session.execute(text("""
        WITH item_subs AS (
            SELECT qi.quotation_id,
                   SUM(
                       CASE WHEN COALESCE(qi.discount_percent, 0) > 0
                            THEN COALESCE(qi.discounted_amount, qi.amount * qi.quantity)
                            ELSE qi.amount * qi.quantity
                       END
                   ) AS item_sub
            FROM "StreemLyne_MT"."Quotation_Items" qi
            GROUP BY qi.quotation_id
        )
        SELECT q.status,
               COUNT(*) AS cnt,
               COALESCE(ROUND(CAST(SUM(
                   COALESCE(its.item_sub, 0)
                   * (1 - COALESCE(q.global_discount_percent, 0) / 100.0)
                   * (1 + COALESCE(q.vat_percentage, 20) / 100.0)
               ) AS NUMERIC), 2), 0) AS total_value,
               COALESCE(SUM(CAST(NULLIF(q.quote_reference, '') AS NUMERIC)), 0) AS ref_sum
        FROM "StreemLyne_MT"."Quotations" q
        LEFT JOIN item_subs its ON its.quotation_id = q.quotation_id
        WHERE q.tenant_id = :tenant_id
        GROUP BY q.status
        ORDER BY q.status
    """), {"tenant_id": str(tenant_id)}).fetchall()

    status_totals = [
        {
            "status":      r.status or "Unknown",
            "count":       int(r.cnt),
            "total_value": float(r.total_value or 0),
            "ref_sum":     float(r.ref_sum or 0),
        }
        for r in status_rows
    ]
    overall_value   = sum(st["total_value"] for st in status_totals)
    overall_ref_sum = sum(st["ref_sum"]     for st in status_totals)

    data = []
    for r in rows:
        subtotal = float(r.subtotal or 0)
        disc = float(r.discount_pct or 0)
        vat = float(r.vat_pct) if r.vat_pct is not None else 20.0
        after_disc = subtotal * (1 - disc / 100)
        total = round(after_disc * (1 + vat / 100), 2)
        data.append({
            "id":            r.quotation_id,
            "doc_number":    r.reference_number or f"#{r.quotation_id}",
            "doc_reference": getattr(r, "quote_reference", None) or "",
            "customer_name": r.client_company_name or "",
            "room":          r.room_name or "",
            "amount":        total,
            "status":        r.status or "Draft",
            "created_at":    r.created_at.isoformat() if r.created_at else None,
        })

    return jsonify({
        "data":            data,
        "total":           int(counts.total or 0),
        "drafts":          int(counts.drafts or 0),
        "sent":            int(counts.sent or 0),
        "status_totals":   status_totals,
        "overall_value":   round(overall_value, 2),
        "overall_ref_sum": round(overall_ref_sum, 2),
        "page":            page,
        "per_page":        per_page,
        "rooms":           [r.room_name for r in rooms_rows],
    }), 200


# ── Invoices / Proformas ──────────────────────────────────────────────────────

def _list_invoices(session, tenant_id, page, per_page, offset, search, status, room, kind):
    table = "Invoice_Master" if kind == "invoice" else "Proforma_Master"
    num_col = "invoice_number" if kind == "invoice" else "proforma_number"
    id_col = "invoice_id" if kind == "invoice" else "invoice_id"

    # Both use Invoice_Master; proformas are distinguished by status LIKE 'Proforma%'
    if kind == "invoice":
        type_filter = "AND (i.status NOT LIKE 'Proforma%')"
    else:
        type_filter = "AND i.status LIKE 'Proforma%'"

    where = [f"i.tenant_id = :tenant_id {type_filter}"]
    params: dict = {"tenant_id": str(tenant_id)}

    if search:
        where.append(f"(i.{num_col} ILIKE :search OR c.client_company_name ILIKE :search)")
        params["search"] = _ilike(search)
    if status:
        where.append("i.status = :status")
        params["status"] = status
    if room:
        where.append("i.room_name ILIKE :room")
        params["room"] = _ilike(room)

    w = " AND ".join(where)

    # Try Invoice_Master first; proformas may use a separate table
    try:
        counts = session.execute(text(f"""
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN LOWER(i.status) = 'draft' THEN 1 ELSE 0 END) AS drafts,
                SUM(CASE WHEN LOWER(i.status) = 'sent'  THEN 1 ELSE 0 END) AS sent
            FROM "StreemLyne_MT"."Invoice_Master" i
            INNER JOIN "StreemLyne_MT"."Client_Master" c ON i.client_id = c.client_id
            WHERE {w}
        """), params).fetchone()

        rooms_rows = session.execute(text(f"""
            SELECT DISTINCT i.room_name
            FROM "StreemLyne_MT"."Invoice_Master" i
            INNER JOIN "StreemLyne_MT"."Client_Master" c ON i.client_id = c.client_id
            WHERE {w} AND i.room_name IS NOT NULL AND i.room_name != ''
            ORDER BY i.room_name
        """), params).fetchall()

        rows = session.execute(text(f"""
            SELECT i.invoice_id, i.invoice_number,
                   i.client_id, c.client_company_name,
                   i.room_name, i.status, i.created_at,
                   COALESCE(i.quote_reference, '') AS quote_reference,
                   COALESCE((
                       SELECT SUM(
                           CASE WHEN COALESCE(d.discount_percent, 0) > 0
                                THEN COALESCE(d.discounted_amount, d.amount * d.quantity)
                                ELSE d.amount * d.quantity
                           END
                       )
                       FROM "StreemLyne_MT"."Invoice_Details" d
                       WHERE d.invoice_id = i.invoice_id
                   ), 0) AS subtotal,
                   COALESCE(i.global_discount_percent, 0) AS global_disc,
                   COALESCE(i.vat_rate, 20) AS vat_pct
            FROM "StreemLyne_MT"."Invoice_Master" i
            INNER JOIN "StreemLyne_MT"."Client_Master" c ON i.client_id = c.client_id
            WHERE {w}
            ORDER BY i.created_at DESC
            LIMIT :lim OFFSET :off
        """), {**params, "lim": per_page, "off": offset}).fetchall()

        # Unfiltered status breakdown
        status_rows = session.execute(text(f"""
            WITH item_subs AS (
                SELECT d.invoice_id,
                       SUM(
                           CASE WHEN COALESCE(d.discount_percent, 0) > 0
                                THEN COALESCE(d.discounted_amount, d.amount * d.quantity)
                                ELSE d.amount * d.quantity
                           END
                       ) AS item_sub
                FROM "StreemLyne_MT"."Invoice_Details" d
                GROUP BY d.invoice_id
            )
            SELECT i.status,
                   COUNT(*) AS cnt,
                   COALESCE(ROUND(CAST(SUM(
                       COALESCE(its.item_sub, 0)
                       * (1 - COALESCE(i.global_discount_percent, 0) / 100.0)
                       * (1 + COALESCE(i.vat_rate, 20) / 100.0)
                   ) AS NUMERIC), 2), 0) AS total_value,
                   COALESCE(SUM(CAST(NULLIF(i.quote_reference, '') AS NUMERIC)), 0) AS ref_sum
            FROM "StreemLyne_MT"."Invoice_Master" i
            LEFT JOIN item_subs its ON its.invoice_id = i.invoice_id
            WHERE i.tenant_id = :tenant_id {type_filter}
            GROUP BY i.status
            ORDER BY i.status
        """), {"tenant_id": str(tenant_id)}).fetchall()

    except Exception:
        return jsonify({"data": [], "total": 0, "drafts": 0, "sent": 0, "status_totals": [], "overall_value": 0, "overall_ref_sum": 0, "page": page, "per_page": per_page, "rooms": []}), 200

    status_totals = [
        {
            "status":      r.status or "Unknown",
            "count":       int(r.cnt),
            "total_value": float(r.total_value or 0),
            "ref_sum":     float(r.ref_sum or 0),
        }
        for r in status_rows
    ]
    overall_value   = sum(st["total_value"] for st in status_totals)
    overall_ref_sum = sum(st["ref_sum"]     for st in status_totals)

    data = []
    for r in rows:
        subtotal = float(r.subtotal or 0)
        global_disc = float(r.global_disc or 0)
        vat_pct = float(r.vat_pct) if r.vat_pct is not None else 20.0
        after_disc = subtotal * (1 - global_disc / 100)
        total = round(after_disc * (1 + vat_pct / 100), 2)
        data.append({
            "id":            r.invoice_id,
            "doc_number":    r.invoice_number or f"#{r.invoice_id}",
            "doc_reference": getattr(r, "quote_reference", None) or "",
            "customer_name": r.client_company_name or "",
            "room":          r.room_name or "",
            "amount":        total,
            "status":        r.status or "Draft",
            "created_at":    r.created_at.isoformat() if r.created_at else None,
        })

    return jsonify({
        "data":            data,
        "total":           int(counts.total or 0),
        "drafts":          int(counts.drafts or 0),
        "sent":            int(counts.sent or 0),
        "status_totals":   status_totals,
        "overall_value":   round(overall_value, 2),
        "overall_ref_sum": round(overall_ref_sum, 2),
        "page":            page,
        "per_page":        per_page,
        "rooms":           [r.room_name for r in rooms_rows],
    }), 200


# ── Payment Terms ─────────────────────────────────────────────────────────────

def _list_payment_terms(session, tenant_id, page, per_page, offset, search, status, room):
    where = ["pt.tenant_id = :tenant_id"]
    params: dict = {"tenant_id": str(tenant_id)}

    if search:
        where.append("(pt.pt_number ILIKE :search OR c.client_company_name ILIKE :search)")
        params["search"] = _ilike(search)
    if status:
        where.append("pt.status = :status")
        params["status"] = status
    if room:
        where.append("pt.room_name ILIKE :room")
        params["room"] = _ilike(room)

    w = " AND ".join(where)

    counts = session.execute(text(f"""
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN LOWER(pt.status) = 'draft' THEN 1 ELSE 0 END) AS drafts,
            SUM(CASE WHEN LOWER(pt.status) = 'sent'  THEN 1 ELSE 0 END) AS sent
        FROM "StreemLyne_MT"."Payment_Terms_Master" pt
        INNER JOIN "StreemLyne_MT"."Client_Master" c ON pt.client_id = c.client_id
        WHERE {w}
    """), params).fetchone()

    rows = session.execute(text(f"""
        SELECT pt.pt_id, pt.pt_number,
               pt.client_id, c.client_company_name,
               pt.status, pt.created_at,
               COALESCE(pt.total_amount_due, 0) AS total_amount_due
        FROM "StreemLyne_MT"."Payment_Terms_Master" pt
        INNER JOIN "StreemLyne_MT"."Client_Master" c ON pt.client_id = c.client_id
        WHERE {w}
        ORDER BY pt.created_at DESC
        LIMIT :lim OFFSET :off
    """), {**params, "lim": per_page, "off": offset}).fetchall()

    data = []
    for r in rows:
        data.append({
            "id":            r.pt_id,
            "doc_number":    r.pt_number or f"#{r.pt_id}",
            "customer_name": r.client_company_name or "",
            "room":          "",
            "amount":        float(r.total_amount_due or 0),
            "status":        r.status or "Draft",
            "created_at":    r.created_at.isoformat() if r.created_at else None,
        })

    return jsonify({
        "data":     data,
        "total":    int(counts.total or 0),
        "drafts":   int(counts.drafts or 0),
        "sent":     int(counts.sent or 0),
        "page":     page,
        "per_page": per_page,
        "rooms":    [],
    }), 200


# ── Receipts ─────────────────────────────────────────────────────────────────

def _list_receipts(session, tenant_id, page, per_page, offset, search, status, room, subtype):
    """subtype: 'receipt' | 'deposit' | 'final'"""
    where = ["fs.tenant_id = :tenant_id", "fs.form_type LIKE 'receipt_%'"]
    params: dict = {"tenant_id": str(tenant_id)}

    w_base = " AND ".join(where)

    # We filter by subtype in Python since receipt_type is inside form_data JSON
    counts_row = session.execute(text(f"""
        SELECT COUNT(*) AS total FROM "StreemLyne_MT"."Customer_Form_Submissions" fs
        WHERE {w_base}
    """), params).fetchone()

    rows = session.execute(text(f"""
        SELECT fs.form_submission_id, fs.form_data, fs.submitted_at, fs.client_id,
               c.client_company_name
        FROM "StreemLyne_MT"."Customer_Form_Submissions" fs
        LEFT JOIN "StreemLyne_MT"."Client_Master" c ON fs.client_id = c.client_id
        WHERE {w_base}
        ORDER BY fs.submitted_at DESC
    """), params).fetchall()

    data = []
    for r in rows:
        try:
            fd = json.loads(r.form_data) if isinstance(r.form_data, str) else (r.form_data or {})
        except Exception:
            fd = {}

        rt = (fd.get("receiptType") or fd.get("receipt_type") or "receipt").lower()
        kind = "deposit" if "deposit" in rt else "final" if "final" in rt else "receipt"

        if subtype != "receipt" and kind != subtype:
            continue
        if subtype == "receipt" and kind in ("deposit", "final"):
            continue

        cust_name = (
            fd.get("customerName") or fd.get("customer_name") or
            r.client_company_name or ""
        )
        receipt_num = fd.get("receiptNumber") or fd.get("receipt_number") or f"#{r.form_submission_id}"
        room_val = fd.get("roomName") or fd.get("room_name") or fd.get("room") or ""
        amount = float(fd.get("paidAmount") or fd.get("paid_amount") or 0)
        status_val = fd.get("status") or "Issued"

        if search and search.lower() not in cust_name.lower() and search.lower() not in receipt_num.lower():
            continue
        if status and status_val.lower() != status.lower():
            continue
        if room and room.lower() not in room_val.lower():
            continue

        data.append({
            "id":            r.form_submission_id,
            "doc_number":    receipt_num,
            "customer_name": cust_name,
            "room":          room_val,
            "amount":        amount,
            "status":        status_val,
            "created_at":    r.submitted_at.isoformat() if r.submitted_at else None,
        })

    # Apply pagination after Python filtering
    filtered_total = len(data)
    drafts = sum(1 for d in data if d["status"].lower() == "draft")
    sent = sum(1 for d in data if d["status"].lower() in ("sent", "issued"))
    data = data[offset: offset + per_page]

    return jsonify({
        "data":     data,
        "total":    filtered_total,
        "drafts":   drafts,
        "sent":     sent,
        "page":     page,
        "per_page": per_page,
        "rooms":    list({d["room"] for d in data if d["room"]}),
    }), 200


# ── Dashboard financial stats ─────────────────────────────────────────────────

@financial_docs_bp.route("/financial-docs/dashboard-stats", methods=["GET"])
@token_required
@require_tenant
def financial_dashboard_stats(tenant_id, employee_id):
    session = SessionLocal()
    try:
        # Quotes: sent-to-customer and confirmed counts + values
        quote_rows = session.execute(text("""
            WITH item_subs AS (
                SELECT qi.quotation_id,
                       SUM(CASE WHEN COALESCE(qi.discount_percent,0) > 0
                                THEN COALESCE(qi.discounted_amount, qi.amount*qi.quantity)
                                ELSE qi.amount*qi.quantity END) AS item_sub
                FROM "StreemLyne_MT"."Quotation_Items" qi
                GROUP BY qi.quotation_id
            )
            SELECT q.status,
                   COUNT(*) AS cnt,
                   COALESCE(SUM(CAST(NULLIF(q.quote_reference, '') AS NUMERIC)), 0) AS ref_sum,
                   COALESCE(ROUND(CAST(SUM(
                       COALESCE(its.item_sub, 0)
                       * (1 - COALESCE(q.global_discount_percent, 0) / 100.0)
                       * (1 + COALESCE(q.vat_percentage, 20) / 100.0)
                   ) AS NUMERIC), 2), 0) AS total_value
            FROM "StreemLyne_MT"."Quotations" q
            LEFT JOIN item_subs its ON its.quotation_id = q.quotation_id
            WHERE q.tenant_id = :tid
            GROUP BY q.status
        """), {"tid": str(tenant_id)}).fetchall()

        quote_sent = next((r for r in quote_rows if r.status and "sent" in r.status.lower()), None)
        quote_confirmed = next((r for r in quote_rows if r.status and "confirm" in r.status.lower()), None)

        # All quotes for modal (sent + confirmed)
        sent_docs = session.execute(text("""
            SELECT q.quotation_id AS id, q.reference_number AS doc_number,
                   c.client_company_name AS customer_name, q.status, q.created_at,
                   COALESCE(q.quote_reference, '') AS doc_reference,
                   COALESCE((
                       SELECT SUM(CASE WHEN COALESCE(qi.discount_percent,0) > 0
                                  THEN COALESCE(qi.discounted_amount, qi.amount*qi.quantity)
                                  ELSE qi.amount*qi.quantity END)
                       FROM "StreemLyne_MT"."Quotation_Items" qi WHERE qi.quotation_id = q.quotation_id
                   ), 0) * (1 - COALESCE(q.global_discount_percent,0)/100.0) * (1 + COALESCE(q.vat_percentage,20)/100.0) AS total
            FROM "StreemLyne_MT"."Quotations" q
            INNER JOIN "StreemLyne_MT"."Client_Master" c ON q.client_id = c.client_id
            WHERE q.tenant_id = :tid AND (LOWER(q.status) LIKE '%sent%' OR LOWER(q.status) LIKE '%confirm%')
            ORDER BY q.created_at DESC
        """), {"tid": str(tenant_id)}).fetchall()

        # Invoices: monthly earnings (invoice total grouped by month)
        monthly_rows = session.execute(text("""
            WITH item_subs AS (
                SELECT d.invoice_id,
                       SUM(CASE WHEN COALESCE(d.discount_percent,0) > 0
                                THEN COALESCE(d.discounted_amount, d.amount*d.quantity)
                                ELSE d.amount*d.quantity END) AS item_sub
                FROM "StreemLyne_MT"."Invoice_Details" d
                GROUP BY d.invoice_id
            )
            SELECT TO_CHAR(i.created_at, 'YYYY-MM') AS month,
                   COUNT(*) AS cnt,
                   ROUND(CAST(SUM(
                       COALESCE(its.item_sub,0)
                       * (1 - COALESCE(i.global_discount_percent,0)/100.0)
                       * (1 + COALESCE(i.vat_rate,20)/100.0)
                   ) AS NUMERIC), 2) AS invoice_total,
                   COALESCE(SUM(CAST(NULLIF(i.quote_reference,'') AS NUMERIC)), 0) AS ref_total
            FROM "StreemLyne_MT"."Invoice_Master" i
            LEFT JOIN item_subs its ON its.invoice_id = i.invoice_id
            WHERE i.tenant_id = :tid AND i.status NOT LIKE 'Proforma%'
            GROUP BY TO_CHAR(i.created_at, 'YYYY-MM')
            ORDER BY month DESC
            LIMIT 24
        """), {"tid": str(tenant_id)}).fetchall()

        # All invoices for monthly modal
        invoice_docs = session.execute(text("""
            WITH item_subs AS (
                SELECT d.invoice_id,
                       SUM(CASE WHEN COALESCE(d.discount_percent,0) > 0
                                THEN COALESCE(d.discounted_amount, d.amount*d.quantity)
                                ELSE d.amount*d.quantity END) AS item_sub
                FROM "StreemLyne_MT"."Invoice_Details" d
                GROUP BY d.invoice_id
            )
            SELECT i.invoice_id AS id, i.invoice_number AS doc_number,
                   c.client_company_name AS customer_name,
                   i.status, i.created_at,
                   COALESCE(i.quote_reference, '') AS doc_reference,
                   TO_CHAR(i.created_at, 'YYYY-MM') AS month,
                   ROUND(CAST(
                       COALESCE(its.item_sub,0)
                       * (1 - COALESCE(i.global_discount_percent,0)/100.0)
                       * (1 + COALESCE(i.vat_rate,20)/100.0)
                   AS NUMERIC), 2) AS total
            FROM "StreemLyne_MT"."Invoice_Master" i
            INNER JOIN "StreemLyne_MT"."Client_Master" c ON i.client_id = c.client_id
            LEFT JOIN item_subs its ON its.invoice_id = i.invoice_id
            WHERE i.tenant_id = :tid AND i.status NOT LIKE 'Proforma%'
            ORDER BY i.created_at DESC
        """), {"tid": str(tenant_id)}).fetchall()

        # Invoice status breakdown (sent, paid partially, received)
        inv_status_rows = session.execute(text("""
            WITH item_subs AS (
                SELECT d.invoice_id,
                       SUM(CASE WHEN COALESCE(d.discount_percent,0) > 0
                                THEN COALESCE(d.discounted_amount, d.amount*d.quantity)
                                ELSE d.amount*d.quantity END) AS item_sub
                FROM "StreemLyne_MT"."Invoice_Details" d
                GROUP BY d.invoice_id
            )
            SELECT i.status,
                   COUNT(*) AS cnt,
                   COALESCE(ROUND(CAST(SUM(
                       COALESCE(its.item_sub,0)
                       * (1 - COALESCE(i.global_discount_percent,0)/100.0)
                       * (1 + COALESCE(i.vat_rate,20)/100.0)
                   ) AS NUMERIC), 2), 0) AS total_value
            FROM "StreemLyne_MT"."Invoice_Master" i
            LEFT JOIN item_subs its ON its.invoice_id = i.invoice_id
            WHERE i.tenant_id = :tid AND i.status NOT LIKE 'Proforma%'
            GROUP BY i.status
        """), {"tid": str(tenant_id)}).fetchall()

        def inv_stat(keyword):
            r = next((x for x in inv_status_rows if x.status and keyword in x.status.lower()), None)
            return {"count": int(r.cnt) if r else 0, "total_value": float(r.total_value or 0) if r else 0}

        total_earnings = sum(float(r.invoice_total or 0) for r in monthly_rows)
        total_ref = sum(float(r.ref_total or 0) for r in monthly_rows)

        return jsonify({
            "quotes": {
                "sent": {
                    "count":       int(quote_sent.cnt) if quote_sent else 0,
                    "total_value": float(quote_sent.total_value) if quote_sent else 0,
                    "ref_sum":     float(quote_sent.ref_sum) if quote_sent else 0,
                },
                "confirmed": {
                    "count":       int(quote_confirmed.cnt) if quote_confirmed else 0,
                    "total_value": float(quote_confirmed.total_value) if quote_confirmed else 0,
                    "ref_sum":     float(quote_confirmed.ref_sum) if quote_confirmed else 0,
                },
                "docs": [
                    {
                        "id":            r.id,
                        "doc_number":    r.doc_number or f"#{r.id}",
                        "customer_name": r.customer_name or "",
                        "status":        r.status or "",
                        "doc_reference": r.doc_reference or "",
                        "total":         round(float(r.total or 0), 2),
                        "created_at":    r.created_at.isoformat() if r.created_at else None,
                    }
                    for r in sent_docs
                ],
            },
            "invoices": {
                "sent":          inv_stat("sent"),
                "paid_partially": inv_stat("partial"),
                "received":      inv_stat("received"),
                "total_earnings": round(total_earnings, 2),
                "total_ref":      round(total_ref, 2),
                "profit":         round(total_earnings - total_ref, 2),
                "monthly": [
                    {
                        "month":         r.month,
                        "count":         int(r.cnt),
                        "invoice_total": float(r.invoice_total or 0),
                        "ref_total":     float(r.ref_total or 0),
                        "profit":        round(float(r.invoice_total or 0) - float(r.ref_total or 0), 2),
                    }
                    for r in monthly_rows
                ],
                "docs": [
                    {
                        "id":            r.id,
                        "doc_number":    r.doc_number or f"#{r.id}",
                        "customer_name": r.customer_name or "",
                        "status":        r.status or "",
                        "doc_reference": r.doc_reference or "",
                        "month":         r.month,
                        "total":         float(r.total or 0),
                        "created_at":    r.created_at.isoformat() if r.created_at else None,
                    }
                    for r in invoice_docs
                ],
            },
        }), 200

    except Exception as e:
        current_app.logger.error(f"Error in financial_dashboard_stats: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()


# ── Admin insights (revenue by job type, confirmation rate, outstanding) ──────

@financial_docs_bp.route("/financial-docs/admin-insights", methods=["GET"])
@token_required
@require_tenant
def admin_insights(tenant_id, employee_id):
    session = SessionLocal()
    try:
        tid = str(tenant_id)

        # 1. Revenue by room/job type — confirmed quotations grouped by room_name
        job_revenue_rows = session.execute(text("""
            WITH item_subs AS (
                SELECT qi.quotation_id,
                       SUM(CASE WHEN COALESCE(qi.discount_percent,0) > 0
                                THEN COALESCE(qi.discounted_amount, qi.amount*qi.quantity)
                                ELSE qi.amount*qi.quantity END) AS item_sub
                FROM "StreemLyne_MT"."Quotation_Items" qi
                GROUP BY qi.quotation_id
            )
            SELECT
                COALESCE(NULLIF(TRIM(q.room_name), ''), 'Other') AS job_type,
                COUNT(*) AS quote_count,
                COALESCE(ROUND(CAST(SUM(
                    COALESCE(its.item_sub, 0)
                    * (1 - COALESCE(q.global_discount_percent, 0) / 100.0)
                    * (1 + COALESCE(q.vat_percentage, 20) / 100.0)
                ) AS NUMERIC), 2), 0) AS total_value
            FROM "StreemLyne_MT"."Quotations" q
            LEFT JOIN item_subs its ON its.quotation_id = q.quotation_id
            WHERE q.tenant_id = :tid
              AND (LOWER(q.status) LIKE '%confirm%' OR LOWER(q.status) LIKE '%sent%')
            GROUP BY COALESCE(NULLIF(TRIM(q.room_name), ''), 'Other')
            ORDER BY total_value DESC
        """), {"tid": tid}).fetchall()

        # 2. Quote confirmation rate
        quote_totals = session.execute(text("""
            SELECT
                COUNT(*) AS total_quotes,
                SUM(CASE WHEN LOWER(status) LIKE '%sent%' THEN 1 ELSE 0 END) AS sent,
                SUM(CASE WHEN LOWER(status) LIKE '%confirm%' THEN 1 ELSE 0 END) AS confirmed,
                SUM(CASE WHEN LOWER(status) NOT LIKE '%draft%' THEN 1 ELSE 0 END) AS non_draft
            FROM "StreemLyne_MT"."Quotations"
            WHERE tenant_id = :tid
        """), {"tid": tid}).fetchone()

        sent_count      = int(quote_totals.sent or 0)
        confirmed_count = int(quote_totals.confirmed or 0)
        total_quotes    = int(quote_totals.total_quotes or 0)
        non_draft       = int(quote_totals.non_draft or 0)
        confirmation_rate = round((confirmed_count / sent_count * 100) if sent_count > 0 else 0, 1)

        # 3. Overdue invoices — sent or partially paid, issued 30+ days ago
        overdue_rows = session.execute(text("""
            WITH item_subs AS (
                SELECT d.invoice_id,
                       SUM(CASE WHEN COALESCE(d.discount_percent,0) > 0
                                THEN COALESCE(d.discounted_amount, d.amount*d.quantity)
                                ELSE d.amount*d.quantity END) AS item_sub
                FROM "StreemLyne_MT"."Invoice_Details" d
                GROUP BY d.invoice_id
            )
            SELECT
                i.invoice_id AS id,
                i.invoice_number AS doc_number,
                c.client_company_name AS customer_name,
                i.status,
                i.created_at,
                (CURRENT_DATE - i.created_at::date) AS days_overdue,
                ROUND(CAST(
                    COALESCE(its.item_sub, 0)
                    * (1 - COALESCE(i.global_discount_percent, 0) / 100.0)
                    * (1 + COALESCE(i.vat_rate, 20) / 100.0)
                AS NUMERIC), 2) AS total
            FROM "StreemLyne_MT"."Invoice_Master" i
            INNER JOIN "StreemLyne_MT"."Client_Master" c ON i.client_id = c.client_id
            LEFT JOIN item_subs its ON its.invoice_id = i.invoice_id
            WHERE i.tenant_id = :tid
              AND i.status NOT LIKE 'Proforma%'
              AND LOWER(i.status) NOT IN ('draft', 'received', 'paid', 'cancelled', 'rejected')
              AND i.created_at::date <= CURRENT_DATE - INTERVAL '30 days'
            ORDER BY i.created_at ASC
        """), {"tid": tid}).fetchall()

        overdue_total = sum(float(r.total or 0) for r in overdue_rows)

        return jsonify({
            "revenue_by_job_type": [
                {
                    "job_type":    r.job_type,
                    "quote_count": int(r.quote_count),
                    "total_value": float(r.total_value),
                }
                for r in job_revenue_rows
            ],
            "confirmation_rate": {
                "rate":       confirmation_rate,
                "sent":       sent_count,
                "confirmed":  confirmed_count,
                "total":      total_quotes,
                "non_draft":  non_draft,
            },
            "overdue_invoices": {
                "count":       len(overdue_rows),
                "total_value": round(overdue_total, 2),
                "docs": [
                    {
                        "id":           r.id,
                        "doc_number":   r.doc_number or f"#{r.id}",
                        "customer_name":r.customer_name or "",
                        "status":       r.status or "",
                        "total":        float(r.total or 0),
                        "days_overdue": int(r.days_overdue or 0),
                        "created_at":   r.created_at.isoformat() if r.created_at else None,
                    }
                    for r in overdue_rows
                ],
            },
        }), 200

    except Exception as e:
        current_app.logger.error(f"Error in admin_insights: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()


# ── Inline status update ──────────────────────────────────────────────────────

@financial_docs_bp.route("/financial-docs/<int:doc_id>/status", methods=["PATCH"])
@token_required
@require_tenant
def update_doc_status(doc_id, tenant_id, employee_id):
    """Update status for any financial document type."""
    body = request.get_json(silent=True) or {}
    doc_type = body.get("doc_type", "").lower()
    new_status = body.get("status", "").strip()

    if not new_status:
        return jsonify({"error": "status is required"}), 400

    session = SessionLocal()
    try:
        if doc_type == "quotations":
            result = session.execute(text("""
                UPDATE "StreemLyne_MT"."Quotations"
                SET status = :status, updated_at = NOW()
                WHERE quotation_id = :id AND tenant_id = :tid
                RETURNING quotation_id
            """), {"status": new_status, "id": doc_id, "tid": str(tenant_id)}).fetchone()

        elif doc_type == "invoices":
            result = session.execute(text("""
                UPDATE "StreemLyne_MT"."Invoice_Master"
                SET status = :status
                WHERE invoice_id = :id AND tenant_id = :tid
                  AND (status NOT LIKE 'Proforma%%')
                RETURNING invoice_id
            """), {"status": new_status, "id": doc_id, "tid": str(tenant_id)}).fetchone()

        elif doc_type == "proformas":
            result = session.execute(text("""
                UPDATE "StreemLyne_MT"."Invoice_Master"
                SET status = :status
                WHERE invoice_id = :id AND tenant_id = :tid
                  AND status LIKE 'Proforma%%'
                RETURNING invoice_id
            """), {"status": new_status, "id": doc_id, "tid": str(tenant_id)}).fetchone()

        elif doc_type == "payment-terms":
            result = session.execute(text("""
                UPDATE "StreemLyne_MT"."Payment_Terms"
                SET status = :status
                WHERE pt_id = :id AND tenant_id = :tid
                RETURNING pt_id
            """), {"status": new_status, "id": doc_id, "tid": str(tenant_id)}).fetchone()

        else:
            return jsonify({"error": f"Status update not supported for {doc_type}"}), 400

        if not result:
            return jsonify({"error": "Document not found"}), 404

        session.commit()
        return jsonify({"success": True, "status": new_status}), 200

    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error updating status for {doc_type}/{doc_id}: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()
