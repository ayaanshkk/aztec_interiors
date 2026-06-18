from flask import Blueprint, request, jsonify, current_app
from sqlalchemy import text
import secrets
import string
import json
from datetime import datetime, timedelta

from ..db import SessionLocal
from .auth_helpers import token_required, require_tenant

form_token_bp = Blueprint("form_token", __name__)

# In-memory token store (use Redis in production)
form_tokens: dict = {}


# ─────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────

def generate_secure_token(length: int = 32) -> str:
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))


# ─────────────────────────────────────────
# TOKEN MANAGEMENT
# ─────────────────────────────────────────

@form_token_bp.route('/customers/<int:customer_id>/generate-form-link', methods=['POST'])
@token_required
@require_tenant
def generate_customer_form_link(customer_id, tenant_id, employee_id):
    """Generate a time-limited form link for a specific customer"""
    session = SessionLocal()
    try:
        customer = session.execute(
            text("""
                SELECT client_id FROM "StreemLyne_MT"."Client_Master"
                WHERE client_id = :client_id AND tenant_id = :tenant_id
            """),
            {'client_id': customer_id, 'tenant_id': str(tenant_id)}
        ).fetchone()

        if not customer:
            return jsonify({'success': False, 'error': 'Customer not found'}), 404

        data      = request.get_json(silent=True) or {}
        form_type = data.get('formType', 'bedroom')
        token     = generate_secure_token()
        expiration = datetime.now() + timedelta(hours=24)

        form_tokens[token] = {
            'customer_id': customer_id,
            'tenant_id':   tenant_id,
            'form_type':   form_type,
            'created_at':  datetime.now(),
            'expires_at':  expiration,
            'used':        False,
        }

        current_app.logger.debug(f"Generated token {token} for customer {customer_id}")

        return jsonify({
            'success':    True,
            'token':      token,
            'form_type':  form_type,
            'expires_at': expiration.isoformat(),
            'message':    f'{form_type.title()} form link generated successfully',
        }), 200

    except Exception as e:
        current_app.logger.exception(f"Failed to generate form link for customer {customer_id}")
        return jsonify({'success': False, 'error': f'Failed to generate form link: {str(e)}'}), 500
    finally:
        session.close()


@form_token_bp.route('/validate-form-token/<token>', methods=['GET'])
def validate_form_token(token):
    """Validate a form token — public endpoint"""
    try:
        if token not in form_tokens:
            return jsonify({'valid': False, 'error': 'Invalid token'}), 404

        token_data = form_tokens[token]

        if datetime.now() > token_data['expires_at']:
            del form_tokens[token]
            return jsonify({'valid': False, 'error': 'Token has expired'}), 410

        if token_data['used']:
            return jsonify({'valid': False, 'error': 'Token has already been used'}), 410

        return jsonify({
            'valid':       True,
            'expires_at':  token_data['expires_at'].isoformat(),
            'customer_id': token_data.get('customer_id'),
            'form_type':   token_data.get('form_type'),
        }), 200

    except Exception as e:
        current_app.logger.exception("Token validation failed")
        return jsonify({'valid': False, 'error': f'Validation failed: {str(e)}'}), 500


@form_token_bp.route('/cleanup-expired-tokens', methods=['POST'])
def cleanup_expired_tokens():
    """Remove expired tokens from the in-memory store"""
    try:
        now     = datetime.now()
        expired = [t for t, d in form_tokens.items() if now > d['expires_at']]
        for t in expired:
            del form_tokens[t]

        return jsonify({
            'success':          True,
            'cleaned_tokens':   len(expired),
            'remaining_tokens': len(form_tokens),
        }), 200

    except Exception as e:
        current_app.logger.exception("Cleanup failed")
        return jsonify({'success': False, 'error': f'Cleanup failed: {str(e)}'}), 500


# ─────────────────────────────────────────
# FORM SUBMISSION (public)
# ─────────────────────────────────────────

@form_token_bp.route('/submit-customer-form', methods=['POST'])
def submit_customer_form():
    """Submit a customer form — public endpoint (token or walk-in)"""
    session = SessionLocal()
    try:
        data           = request.get_json(silent=True) or {}
        token          = data.get('token')
        form_data      = data.get('formData', {})
        is_walkin_mode = data.get('isWalkinMode', False)

        if not form_data:
            return jsonify({'success': False, 'error': 'Missing form data'}), 400

        client_id = None
        tenant_id = None

        # ── Walk-in customer ──────────────────────────────────────────
        if is_walkin_mode:
            customer_name     = form_data.get('customer_name', '').strip()
            customer_phone    = form_data.get('customer_phone', '').strip()
            customer_address  = form_data.get('customer_address', '').strip()
            customer_postcode = (form_data.get('customer_postcode') or form_data.get('postcode', '')).strip()

            for field, value in [
                ('Customer name',     customer_name),
                ('Customer phone',    customer_phone),
                ('Customer address',  customer_address),
                ('Customer postcode', customer_postcode),
            ]:
                if not value:
                    return jsonify({'success': False, 'error': f'{field} is required for walk-in submission'}), 400

            tenant_id = '7'

            existing = session.execute(
                text("""
                    SELECT client_id FROM "StreemLyne_MT"."Client_Master"
                    WHERE tenant_id = :tenant_id
                    AND (client_phone = :phone OR client_company_name = :name)
                    AND (is_deleted IS NULL OR is_deleted = FALSE)
                    LIMIT 1
                """),
                {'tenant_id': str(tenant_id), 'phone': customer_phone, 'name': customer_name}
            ).fetchone()

            if existing:
                client_id = existing.client_id
                current_app.logger.info(f"Found existing walk-in customer: {client_id}")
            else:
                result = session.execute(
                    text("""
                        INSERT INTO "StreemLyne_MT"."Client_Master"
                        (tenant_id, client_company_name, client_phone, address, post_code,
                         client_type, created_at, is_deleted)
                        VALUES (:tenant_id, :name, :phone, :address, :postcode,
                                'walk_in', CURRENT_TIMESTAMP, FALSE)
                        RETURNING client_id
                    """),
                    {
                        'tenant_id': str(tenant_id),
                        'name':      customer_name,
                        'phone':     customer_phone,
                        'address':   customer_address,
                        'postcode':  customer_postcode,
                    }
                )
                client_id = result.fetchone().client_id
                session.flush()
                current_app.logger.info(f"Created new walk-in customer: {client_id}")

            form_data['customer_id'] = str(client_id)

        # ── Token-based submission ────────────────────────────────────
        elif token:
            if token not in form_tokens:
                return jsonify({'success': False, 'error': 'Invalid or expired token'}), 400

            token_data = form_tokens[token]

            if datetime.now() > token_data['expires_at']:
                del form_tokens[token]
                return jsonify({'success': False, 'error': 'Token has expired'}), 410

            if token_data['used']:
                return jsonify({'success': False, 'error': 'Token has already been used'}), 410

            client_id = token_data.get('customer_id')
            tenant_id = token_data.get('tenant_id')

            if client_id and tenant_id:
                client = session.execute(
                    text("""
                        SELECT client_id FROM "StreemLyne_MT"."Client_Master"
                        WHERE client_id = :client_id AND tenant_id = :tenant_id
                    """),
                    {'client_id': client_id, 'tenant_id': str(tenant_id)}
                ).fetchone()

                if not client:
                    return jsonify({'success': False, 'error': 'Associated customer not found'}), 404

                form_tokens[token]['used'] = True

        # ── Fallback: client_id in form_data ─────────────────────────
        if client_id is None:
            raw_id = form_data.get('customer_id', '')
            if raw_id and str(raw_id).strip():
                client_id = int(raw_id)
                current_app.logger.info(f"Extracted client_id from form_data: {client_id}")

        if client_id is None:
            return jsonify({
                'success': False,
                'error':   'Customer ID is required. Please select a customer or use walk-in mode.',
            }), 400

        if tenant_id is None:
            tenant_id = '7'

        # ── Resolve project_id ────────────────────────────────────────
        project_id = (
            request.args.get('projectId') or
            data.get('projectId') or
            data.get('project_id') or
            form_data.get('project_id') or
            form_data.get('projectId')
        )
        if project_id in ('', 'null', 'undefined'):
            project_id = None

        # ── Determine form_type ───────────────────────────────────────
        form_type = form_data.get('form_type', 'general')
        if form_type == 'kitchen':
            form_type = 'kitchen_checklist'
        elif form_type == 'bedroom':
            form_type = 'bedroom_checklist'

        current_app.logger.info(
            f"Saving form: tenant_id={tenant_id}, client_id={client_id}, form_type={form_type}"
        )

        result = session.execute(
            text("""
                INSERT INTO "StreemLyne_MT"."Customer_Form_Submissions"
                (tenant_id, client_id, project_id, form_type, form_data,
                 token_used, submitted_by, submission_status)
                VALUES (:tenant_id, :client_id, :project_id, :form_type, :form_data,
                        :token, :submitted_by, 'submitted')
                RETURNING form_submission_id
            """),
            {
                'tenant_id':    str(tenant_id),
                'client_id':    int(client_id),
                'project_id':   int(project_id) if project_id else None,
                'form_type':    form_type,
                'form_data':    json.dumps(form_data),
                'token':        token or '',
                'submitted_by': 'Walk-in Customer' if is_walkin_mode else 'Public Form',
            }
        )

        form_id = result.fetchone().form_submission_id
        session.commit()
        current_app.logger.info(f"Form submitted successfully: form_id={form_id}")

        # ── Notification ──────────────────────────────────────────────
        try:
            customer_row = session.execute(
                text("""
                    SELECT client_company_name FROM "StreemLyne_MT"."Client_Master"
                    WHERE client_id = :client_id AND tenant_id = :tenant_id
                """),
                {'client_id': client_id, 'tenant_id': str(tenant_id)}
            ).fetchone()

            customer_name    = customer_row.client_company_name if customer_row else 'Unknown Customer'
            room             = form_data.get('room', 'general')
            customer_phone   = form_data.get('customer_phone', '')
            customer_address = form_data.get('customer_address', '')

            message = f"📋 New {room} {form_type} submitted\n👤 Customer: {customer_name}"
            if customer_phone:
                message += f"\n📞 Phone: {customer_phone}"
            if customer_address:
                short_addr = customer_address[:50] + '...' if len(customer_address) > 50 else customer_address
                message += f"\n📍 Address: {short_addr}"
            if is_walkin_mode:
                message += "\n✍️ Submitted by: Walk-in Customer"

            session.execute(
                text("""
                    INSERT INTO "StreemLyne_MT"."Notification_Master"
                    (tenant_id, client_id, notification_type, priority, message, read, dismissed)
                    VALUES (:tenant_id, :client_id, 'form_submission', 'high', :message, false, false)
                """),
                {'tenant_id': str(tenant_id), 'client_id': int(client_id), 'message': message}
            )
            session.commit()
            current_app.logger.info("Form submission notification created")
        except Exception as notif_error:
            current_app.logger.warning(f"Failed to create form notification: {notif_error}")

        return jsonify({
            'success':            True,
            'customer_id':        client_id,
            'client_id':          client_id,
            'project_id':         project_id,
            'form_submission_id': form_id,
            'message':            (
                'Walk-in customer created and form submitted successfully'
                if is_walkin_mode else 'Form submitted successfully'
            ),
        }), 201

    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Form submission failed: {e}")
        return jsonify({'success': False, 'error': f'Form submission failed: {str(e)}'}), 500
    finally:
        session.close()

@form_token_bp.route('/form-submissions', methods=['GET'])
@token_required
@require_tenant
def get_form_submissions(tenant_id, employee_id):
    """Get form submissions, optionally filtered by customer_id"""
    session = SessionLocal()
    try:
        where_conditions = ["fs.tenant_id = :tenant_id"]
        params = {'tenant_id': str(tenant_id)}

        customer_id = request.args.get('customer_id')
        if customer_id:
            where_conditions.append("fs.client_id = :client_id")
            params['client_id'] = int(customer_id)

        where_clause = " AND ".join(where_conditions)

        query = text(f"""
            SELECT 
                fs.form_submission_id,
                fs.client_id,
                fs.form_type,
                fs.form_data,
                fs.submitted_at,
                fs.created_at,
                c.client_company_name
            FROM "StreemLyne_MT"."Customer_Form_Submissions" fs
            LEFT JOIN "StreemLyne_MT"."Client_Master" c ON fs.client_id = c.client_id
            WHERE {where_clause}
            ORDER BY fs.submitted_at DESC
        """)

        submissions = session.execute(query, params).fetchall()

        result = []
        for s in submissions:
            form_data = s.form_data
            if isinstance(form_data, str):
                try:
                    form_data = json.loads(form_data)
                except Exception:
                    form_data = {}

            result.append({
                'id': s.form_submission_id,
                'customer_id': s.client_id,
                'customer_name': s.client_company_name or 'N/A',
                'form_type': form_data.get('form_type', s.form_type or 'unknown'),
                'room': form_data.get('room', ''),
                'form_data': form_data,
                'created_at': (s.submitted_at or s.created_at).isoformat() if (s.submitted_at or s.created_at) else None,
            })

        return jsonify(result), 200

    except Exception as e:
        current_app.logger.exception(f"Error fetching form submissions: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

# ─────────────────────────────────────────
# FORM SUBMISSION MANAGEMENT (authenticated)
# ─────────────────────────────────────────

@form_token_bp.route('/form-submissions/<int:submission_id>', methods=['GET', 'PUT', 'DELETE'])
@token_required
@require_tenant
def handle_form_submission(submission_id, tenant_id, employee_id):
    """Get, update, or delete a specific form submission"""
    session = SessionLocal()
    try:
        submission = session.execute(
            text("""
                SELECT * FROM "StreemLyne_MT"."Customer_Form_Submissions"
                WHERE form_submission_id = :form_id AND tenant_id = :tenant_id
            """),
            {'form_id': submission_id, 'tenant_id': str(tenant_id)}
        ).fetchone()

        if not submission:
            return jsonify({'error': 'Form submission not found'}), 404

        if request.method == 'GET':
            client = session.execute(
                text('SELECT client_company_name FROM "StreemLyne_MT"."Client_Master" WHERE client_id = :cid'),
                {'cid': submission.client_id}
            ).fetchone()

            return jsonify({
                'id':            submission.form_submission_id,
                'client_id':     submission.client_id,
                'customer_name': client.client_company_name if client else 'N/A',
                'form_data':     submission.form_data,
                'submitted_at':  submission.submitted_at.isoformat() if submission.submitted_at else None,
            }), 200

        elif request.method == 'PUT':
            updated = (request.get_json(silent=True) or {}).get('formData')
            if not updated:
                return jsonify({'error': 'Missing form data'}), 400

            session.execute(
                text("""
                    UPDATE "StreemLyne_MT"."Customer_Form_Submissions"
                    SET form_data = :form_data
                    WHERE form_submission_id = :form_id AND tenant_id = :tenant_id
                """),
                {'form_data': json.dumps(updated), 'form_id': submission_id, 'tenant_id': str(tenant_id)}
            )
            session.commit()

            return jsonify({
                'success':            True,
                'message':            'Form updated successfully',
                'form_submission_id': submission_id,
            }), 200

        elif request.method == 'DELETE':
            session.execute(
                text("""
                    DELETE FROM "StreemLyne_MT"."Customer_Form_Submissions"
                    WHERE form_submission_id = :form_id AND tenant_id = :tenant_id
                """),
                {'form_id': submission_id, 'tenant_id': str(tenant_id)}
            )
            session.commit()

            return jsonify({
                'success': True,
                'message': 'Form submission deleted successfully',
                'id':      submission_id,
            }), 200

    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error handling form submission {submission_id}: {e}")
        return jsonify({'error': f'Operation failed: {str(e)}'}), 500
    finally:
        session.close()


# ─────────────────────────────────────────
# CUSTOMERS LOOKUP (for form dropdowns)
# ─────────────────────────────────────────

@form_token_bp.route('/customers', methods=['GET'])
@token_required
@require_tenant
def get_customers_for_forms(tenant_id, employee_id):
    """Return all active customers for the current tenant"""
    session = SessionLocal()
    try:
        rows = session.execute(
            text("""
                SELECT
                    client_id   AS id,
                    client_company_name AS name,
                    address,
                    client_phone AS phone,
                    client_email AS email,
                    post_code    AS postcode
                FROM "StreemLyne_MT"."Client_Master"
                WHERE tenant_id = :tenant_id
                AND (is_deleted IS NULL OR is_deleted = FALSE)
                ORDER BY client_company_name ASC
            """),
            {'tenant_id': str(tenant_id)}
        ).fetchall()

        return jsonify([
            {
                'id':       str(r.id),
                'name':     r.name     or 'N/A',
                'address':  r.address  or '',
                'phone':    r.phone    or '',
                'email':    r.email    or '',
                'postcode': r.postcode or '',
            }
            for r in rows
        ]), 200

    except Exception as e:
        current_app.logger.exception(f"Failed to fetch customers: {e}")
        return jsonify({'error': f'Failed to fetch customers: {str(e)}'}), 500
    finally:
        session.close()

@form_token_bp.route('/form-submissions/<int:submission_id>/pdf', methods=['GET'])
@token_required
@require_tenant
def download_submission_pdf(submission_id, tenant_id, employee_id):
    """Generate PDF for a specific form submission"""
    from flask import current_app
    session = SessionLocal()
    try:
        submission = session.execute(
            text("""
                SELECT form_data FROM "StreemLyne_MT"."Customer_Form_Submissions"
                WHERE form_submission_id = :id AND tenant_id = :tenant_id
            """),
            {'id': submission_id, 'tenant_id': str(tenant_id)}
        ).fetchone()

        if not submission:
            return jsonify({'error': 'Submission not found'}), 404

        form_data = submission.form_data
        if isinstance(form_data, str):
            form_data = json.loads(form_data)

        # Delegate to the checklist PDF generator
        from flask import request as flask_request
        import flask
        with current_app.test_request_context(
            '/checklists/download-pdf',
            method='POST',
            json={'formData': form_data},
            content_type='application/json'
        ):
            from .checklist_routes import download_checklist_pdf
            return download_checklist_pdf()

    except Exception as e:
        current_app.logger.exception(f"Submission PDF failed: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()