from flask import Blueprint, request, jsonify, current_app
from datetime import datetime
from sqlalchemy import text
from ..db import SessionLocal
from .auth_helpers import token_required, require_tenant

tasks_bp = Blueprint('tasks', __name__)

# Valid task fields
VALID_TASK_FIELDS = [
    'type', 'title', 'date', 'start_date', 'end_date', 'customer_name',
    'assigned_to_employee_id', 'team_member', 'project_id', 'client_id', 'job_type',
    'start_time', 'end_time', 'estimated_hours',
    'notes', 'priority', 'status', 'opportunity_id', 'work_stage'
]

def filter_task_data(data):
    """Filter request data to only include valid Task fields"""
    filtered = {}
    for key in VALID_TASK_FIELDS:
        if key in data:
            filtered[key] = data[key]
    # Also accept old field names for backward compatibility
    if 'user_id' in data:
        filtered['assigned_to_employee_id'] = data['user_id']
    if 'customer_id' in data:
        filtered['client_id'] = data['customer_id']
    return filtered

def serialize_task(task_row):
    """Serialize task row to dictionary"""
    return {
        'id': str(task_row.task_id),
        'type': task_row.type,
        'title': task_row.title,
        'date': task_row.date.isoformat() if task_row.date else None,
        'start_date': task_row.start_date.isoformat() if task_row.start_date else None,
        'end_date': task_row.end_date.isoformat() if task_row.end_date else None,
        'start_time': task_row.start_time.strftime('%H:%M') if task_row.start_time else None,
        'end_time': task_row.end_time.strftime('%H:%M') if task_row.end_time else None,
        'estimated_hours': float(task_row.estimated_hours) if task_row.estimated_hours else None,
        'assigned_to_employee_id': task_row.assigned_to_employee_id,
        'user_id': task_row.assigned_to_employee_id,  # Backward compatibility
        'team_member': task_row.team_member,
        'client_id': task_row.client_id,
        'customer_id': task_row.client_id,  # Backward compatibility
        'customer_name': task_row.customer_name,
        'project_id': task_row.project_id,
        'opportunity_id': task_row.opportunity_id,
        'job_type': task_row.job_type,
        'work_stage': task_row.work_stage if hasattr(task_row, 'work_stage') else None,
        'notes': task_row.notes,
        'priority': task_row.priority,
        'status': task_row.status,
        'created_by': task_row.created_by_employee_id,
        'created_by_name': task_row.created_by_name if hasattr(task_row, 'created_by_name') else None,
        'created_at': task_row.created_at.isoformat() if task_row.created_at else None,
        'updated_by': task_row.updated_by_employee_id,
        'updated_by_name': task_row.updated_by_name if hasattr(task_row, 'updated_by_name') else None,
        'updated_at': task_row.updated_at.isoformat() if task_row.updated_at else None
    }

@tasks_bp.route('/tasks', methods=['GET', 'POST'])
@token_required
@require_tenant
def handle_tasks(tenant_id, employee_id):
    if request.method == 'POST':
        session = SessionLocal()
        try:
            data = request.json
            current_app.logger.info(f"📥 RAW data received: {data}")
            
            # Filter valid fields
            data = filter_task_data(data)
            current_app.logger.info(f"📥 Creating task with filtered data: {data}")
            
            # Parse dates
            start_date_value = None
            end_date_value = None
            
            if data.get('start_date'):
                try:
                    start_date_value = datetime.strptime(data['start_date'], '%Y-%m-%d').date()
                except Exception as e:
                    current_app.logger.error(f"❌ Error parsing start_date: {e}")
                    return jsonify({'error': 'Invalid start_date format'}), 400
            elif data.get('date'):
                try:
                    start_date_value = datetime.strptime(data['date'], '%Y-%m-%d').date()
                except Exception as e:
                    current_app.logger.error(f"❌ Error parsing date: {e}")
                    return jsonify({'error': 'Invalid date format'}), 400
            else:
                return jsonify({'error': 'start_date or date is required'}), 400
            
            if data.get('end_date'):
                try:
                    end_date_value = datetime.strptime(data['end_date'], '%Y-%m-%d').date()
                except Exception as e:
                    current_app.logger.error(f"❌ Error parsing end_date: {e}")
                    return jsonify({'error': 'Invalid end_date format'}), 400
            else:
                end_date_value = start_date_value
            
            # Get customer name
            customer_name = data.get('customer_name')
            client_id = data.get('client_id')
            
            if client_id and not customer_name:
                client_query = text("""
                    SELECT client_company_name FROM "StreemLyne_MT"."Client_Master"
                    WHERE client_id = :client_id AND tenant_id = :tenant_id
                """)
                client = session.execute(client_query, {
                    'client_id': client_id,
                    'tenant_id': str(tenant_id)
                }).fetchone()
                if client:
                    customer_name = client.client_company_name
            
            # Parse times
            start_time = None
            end_time = None
            if data.get('start_time'):
                try:
                    start_time = datetime.strptime(data['start_time'], '%H:%M').time()
                except ValueError:
                    current_app.logger.warning(f"Invalid start_time: {data['start_time']}")
            
            if data.get('end_time'):
                try:
                    end_time = datetime.strptime(data['end_time'], '%H:%M').time()
                except ValueError:
                    current_app.logger.warning(f"Invalid end_time: {data['end_time']}")
            
            # Parse hours
            estimated_hours = data.get('estimated_hours')
            if isinstance(estimated_hours, str):
                try:
                    estimated_hours = float(estimated_hours) if estimated_hours else None
                except ValueError:
                    estimated_hours = None
            
            # Get assigned employee name
            assigned_employee_id = data.get('assigned_to_employee_id')
            team_member_name = data.get('team_member')
            
            if assigned_employee_id and not team_member_name:
                emp_query = text("""
                    SELECT employee_name FROM "StreemLyne_MT"."Employee_Master"
                    WHERE employee_id = :employee_id AND tenant_id = :tenant_id
                """)
                emp = session.execute(emp_query, {
                    'employee_id': assigned_employee_id,
                    'tenant_id': str(tenant_id)
                }).fetchone()
                if emp:
                    team_member_name = emp.employee_name
            
            # ✅ Generate sequential task number (Task-001, Task-002, etc.)
            max_task_query = text("""
                SELECT COALESCE(MAX(CAST(SUBSTRING(task_id FROM 6) AS INTEGER)), 0) as max_num
                FROM "StreemLyne_MT"."Tasks_Master"
                WHERE tenant_id = :tenant_id
                AND task_id ~ '^Task-[0-9]+$'
            """)
            max_result = session.execute(max_task_query, {'tenant_id': str(tenant_id)}).fetchone()
            next_task_num = (max_result.max_num if max_result and max_result.max_num else 0) + 1
            task_id = f"Task-{next_task_num:03d}"
            
            current_app.logger.info(f"🆔 Generated task_id: {task_id}")
            
            # ✅ FIXED: Use Tasks_Master table with generated task_id
            insert_query = text("""
                INSERT INTO "StreemLyne_MT"."Tasks_Master"
                (task_id, tenant_id, type, title, date, start_date, end_date, customer_name,
                 assigned_to_employee_id, team_member, created_by_employee_id,
                 project_id, client_id, start_time, end_time, estimated_hours,
                 notes, priority, status, job_type, opportunity_id, work_stage)
                VALUES (:task_id, :tenant_id, :type, :title, :date, :start_date, :end_date, :customer_name,
                        :assigned_to, :team_member, :created_by,
                        :project_id, :client_id, :start_time, :end_time, :estimated_hours,
                        :notes, :priority, :status, :job_type, :opportunity_id, :work_stage)
                RETURNING task_id
            """)
            
            result = session.execute(insert_query, {
                'task_id': task_id,
                'tenant_id': str(tenant_id),
                'type': data.get('type', 'job'),
                'title': data.get('title', ''),
                'date': start_date_value,
                'start_date': start_date_value,
                'end_date': end_date_value,
                'customer_name': customer_name,
                'assigned_to': assigned_employee_id,
                'team_member': team_member_name,
                'created_by': employee_id,
                'project_id': data.get('project_id'),
                'client_id': client_id,
                'start_time': start_time,
                'end_time': end_time,
                'estimated_hours': estimated_hours,
                'notes': data.get('notes', ''),
                'priority': data.get('priority', 'Medium'),
                'status': data.get('status', 'Scheduled'),
                'job_type': data.get('job_type'),
                'opportunity_id': data.get('opportunity_id'),
                'work_stage': data.get('work_stage', 'Survey')
            })
            
            returned_task_id = result.fetchone().task_id
            session.commit()
            
            current_app.logger.info(f"✅ Task created: {returned_task_id}")
            
            # ✅ FIXED: Use Tasks_Master table
            select_query = text("""
                SELECT t.*, e.employee_name as created_by_name
                FROM "StreemLyne_MT"."Tasks_Master" t
                LEFT JOIN "StreemLyne_MT"."Employee_Master" e 
                    ON t.created_by_employee_id = e.employee_id
                WHERE t.task_id = :task_id
            """)
            task = session.execute(select_query, {'task_id': returned_task_id}).fetchone()
            
            # ✅ FIXED: Return task directly without wrapper
            return jsonify(serialize_task(task)), 201
            
        except Exception as e:
            session.rollback()
            current_app.logger.error(f"Error creating task: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({'error': str(e)}), 500
        finally:
            session.close()
    
    # GET
    if request.method == 'GET':
        session = SessionLocal()
        try:
            current_app.logger.info(f"📋 Fetching tasks for tenant: {tenant_id}")
            
            # ✅ FIXED: Use Tasks_Master table
            query = text("""
                SELECT 
                    t.*,
                    creator.employee_name as created_by_name,
                    updater.employee_name as updated_by_name
                FROM "StreemLyne_MT"."Tasks_Master" t
                LEFT JOIN "StreemLyne_MT"."Employee_Master" creator 
                    ON t.created_by_employee_id = creator.employee_id
                LEFT JOIN "StreemLyne_MT"."Employee_Master" updater 
                    ON t.updated_by_employee_id = updater.employee_id
                WHERE t.tenant_id = :tenant_id
                ORDER BY t.created_at DESC
            """)
            
            tasks = session.execute(query, {'tenant_id': str(tenant_id)}).fetchall()
            
            current_app.logger.info(f"✅ Returning {len(tasks)} tasks")
            
            return jsonify([serialize_task(t) for t in tasks])
        except Exception as e:
            current_app.logger.error(f"Error in GET tasks: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({'error': str(e)}), 500
        finally:
            session.close()


@tasks_bp.route('/tasks/<string:task_id>', methods=['GET', 'PUT', 'DELETE'])
@token_required
@require_tenant
def handle_single_task(task_id, tenant_id, employee_id):
    session = SessionLocal()
    try:
        # ✅ FIXED: Use Tasks_Master table
        check_query = text("""
            SELECT task_id FROM "StreemLyne_MT"."Tasks_Master"
            WHERE task_id = :task_id AND tenant_id = :tenant_id
        """)
        task_exists = session.execute(check_query, {
            'task_id': task_id,
            'tenant_id': str(tenant_id)
        }).fetchone()
        
        if not task_exists:
            return jsonify({'error': 'Task not found'}), 404
        
        # GET
        if request.method == 'GET':
            # ✅ FIXED: Use Tasks_Master table
            query = text("""
                SELECT 
                    t.*,
                    creator.employee_name as created_by_name,
                    updater.employee_name as updated_by_name
                FROM "StreemLyne_MT"."Tasks_Master" t
                LEFT JOIN "StreemLyne_MT"."Employee_Master" creator 
                    ON t.created_by_employee_id = creator.employee_id
                LEFT JOIN "StreemLyne_MT"."Employee_Master" updater 
                    ON t.updated_by_employee_id = updater.employee_id
                WHERE t.task_id = :task_id
            """)
            
            task = session.execute(query, {'task_id': task_id}).fetchone()
            return jsonify(serialize_task(task))
        
        # PUT
        elif request.method == 'PUT':
            data = request.json
            current_app.logger.info(f"📝 Updating task {task_id} with data: {data}")
            
            # Filter valid fields
            data = filter_task_data(data)
            
            # Build update query
            update_fields = []
            params = {'task_id': task_id, 'tenant_id': str(tenant_id), 'updated_by': employee_id}
            
            if 'type' in data:
                update_fields.append("type = :type")
                params['type'] = data['type']
            
            if 'title' in data:
                update_fields.append("title = :title")
                params['title'] = data['title']
            
            # Handle dates
            if 'start_date' in data and data['start_date']:
                start_date = datetime.strptime(data['start_date'], '%Y-%m-%d').date()
                update_fields.append("start_date = :start_date")
                update_fields.append("date = :start_date")
                params['start_date'] = start_date
            elif 'date' in data and data['date']:
                date_val = datetime.strptime(data['date'], '%Y-%m-%d').date()
                update_fields.append("date = :date")
                update_fields.append("start_date = :date")
                params['date'] = date_val
            
            if 'end_date' in data and data['end_date']:
                end_date = datetime.strptime(data['end_date'], '%Y-%m-%d').date()
                update_fields.append("end_date = :end_date")
                params['end_date'] = end_date
            
            if 'start_time' in data:
                try:
                    start_time = datetime.strptime(data['start_time'], '%H:%M').time() if data['start_time'] else None
                    update_fields.append("start_time = :start_time")
                    params['start_time'] = start_time
                except ValueError:
                    pass
            
            if 'end_time' in data:
                try:
                    end_time = datetime.strptime(data['end_time'], '%H:%M').time() if data['end_time'] else None
                    update_fields.append("end_time = :end_time")
                    params['end_time'] = end_time
                except ValueError:
                    pass
            
            if 'estimated_hours' in data:
                try:
                    hours = float(data['estimated_hours']) if data['estimated_hours'] else None
                    update_fields.append("estimated_hours = :estimated_hours")
                    params['estimated_hours'] = hours
                except (ValueError, TypeError):
                    pass
            
            if 'notes' in data:
                update_fields.append("notes = :notes")
                params['notes'] = data['notes']
            
            if 'priority' in data:
                update_fields.append("priority = :priority")
                params['priority'] = data['priority']
            
            if 'status' in data:
                update_fields.append("status = :status")
                params['status'] = data['status']
            
            if 'job_type' in data:
                update_fields.append("job_type = :job_type")
                params['job_type'] = data['job_type']
            
            if 'work_stage' in data:
                update_fields.append("work_stage = :work_stage")
                params['work_stage'] = data['work_stage']
            
            if 'project_id' in data:
                update_fields.append("project_id = :project_id")
                params['project_id'] = data['project_id']
            
            # Update client
            if 'client_id' in data:
                update_fields.append("client_id = :client_id")
                params['client_id'] = data['client_id']
                
                if data['client_id']:
                    client_query = text("""
                        SELECT client_company_name FROM "StreemLyne_MT"."Client_Master"
                        WHERE client_id = :client_id AND tenant_id = :tenant_id
                    """)
                    client = session.execute(client_query, {
                        'client_id': data['client_id'],
                        'tenant_id': str(tenant_id)
                    }).fetchone()
                    if client:
                        update_fields.append("customer_name = :customer_name")
                        params['customer_name'] = client.client_company_name
            
            if 'customer_name' in data:
                update_fields.append("customer_name = :customer_name")
                params['customer_name'] = data['customer_name']
            
            # Update assigned employee
            if 'assigned_to_employee_id' in data:
                update_fields.append("assigned_to_employee_id = :assigned_to")
                params['assigned_to'] = data['assigned_to_employee_id']
                
                if data['assigned_to_employee_id']:
                    emp_query = text("""
                        SELECT employee_name FROM "StreemLyne_MT"."Employee_Master"
                        WHERE employee_id = :employee_id AND tenant_id = :tenant_id
                    """)
                    emp = session.execute(emp_query, {
                        'employee_id': data['assigned_to_employee_id'],
                        'tenant_id': str(tenant_id)
                    }).fetchone()
                    if emp:
                        update_fields.append("team_member = :team_member")
                        params['team_member'] = emp.employee_name
            
            if 'team_member' in data:
                update_fields.append("team_member = :team_member")
                params['team_member'] = data['team_member']
            
            if not update_fields:
                return jsonify({'error': 'No fields to update'}), 400
            
            # Add updated_by
            update_fields.append("updated_by_employee_id = :updated_by")
            
            # ✅ FIXED: Use Tasks_Master table
            update_query = text(f"""
                UPDATE "StreemLyne_MT"."Tasks_Master"
                SET {', '.join(update_fields)}
                WHERE task_id = :task_id AND tenant_id = :tenant_id
                RETURNING task_id
            """)
            
            result = session.execute(update_query, params)
            
            if not result.fetchone():
                return jsonify({'error': 'Task not found'}), 404
            
            session.commit()
            
            current_app.logger.info(f"✅ Task {task_id} updated successfully")
            
            # ✅ FIXED: Use Tasks_Master table
            select_query = text("""
                SELECT 
                    t.*,
                    creator.employee_name as created_by_name,
                    updater.employee_name as updated_by_name
                FROM "StreemLyne_MT"."Tasks_Master" t
                LEFT JOIN "StreemLyne_MT"."Employee_Master" creator 
                    ON t.created_by_employee_id = creator.employee_id
                LEFT JOIN "StreemLyne_MT"."Employee_Master" updater 
                    ON t.updated_by_employee_id = updater.employee_id
                WHERE t.task_id = :task_id
            """)
            task = session.execute(select_query, {'task_id': task_id}).fetchone()
            
            # ✅ FIXED: Return task directly without wrapper
            return jsonify(serialize_task(task)), 200
        
        # DELETE
        elif request.method == 'DELETE':
            current_app.logger.info(f"🗑️ Deleting task {task_id}")
            
            # ✅ FIXED: Use Tasks_Master table
            delete_query = text("""
                DELETE FROM "StreemLyne_MT"."Tasks_Master"
                WHERE task_id = :task_id AND tenant_id = :tenant_id
                RETURNING task_id
            """)
            
            result = session.execute(delete_query, {
                'task_id': task_id,
                'tenant_id': str(tenant_id)
            })
            
            if not result.fetchone():
                return jsonify({'error': 'Task not found'}), 404
            
            session.commit()
            current_app.logger.info(f"✅ Task {task_id} deleted")
            
            return jsonify({
                'message': 'Task deleted successfully',
                'id': task_id
            }), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error in handle_single_task: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@tasks_bp.route('/tasks/by-date-range', methods=['GET'])
@token_required
@require_tenant
def get_tasks_by_date_range(tenant_id, employee_id):
    """Get tasks within a date range"""
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    if not start_date or not end_date:
        return jsonify({'error': 'start_date and end_date are required'}), 400
    
    session = SessionLocal()
    try:
        start = datetime.strptime(start_date, '%Y-%m-%d').date()
        end = datetime.strptime(end_date, '%Y-%m-%d').date()
        
        current_app.logger.info(f"📅 Fetching tasks from {start} to {end}")
        
        # ✅ FIXED: Use Tasks_Master table
        query = text("""
            SELECT 
                t.*,
                creator.employee_name as created_by_name,
                updater.employee_name as updated_by_name
            FROM "StreemLyne_MT"."Tasks_Master" t
            LEFT JOIN "StreemLyne_MT"."Employee_Master" creator 
                ON t.created_by_employee_id = creator.employee_id
            LEFT JOIN "StreemLyne_MT"."Employee_Master" updater 
                ON t.updated_by_employee_id = updater.employee_id
            WHERE t.tenant_id = :tenant_id
                AND t.start_date >= :start_date
                AND t.start_date <= :end_date
            ORDER BY t.start_date
        """)
        
        tasks = session.execute(query, {
            'tenant_id': str(tenant_id),
            'start_date': start,
            'end_date': end
        }).fetchall()
        
        current_app.logger.info(f"✅ Found {len(tasks)} tasks in date range")
        
        return jsonify([serialize_task(t) for t in tasks])
    except Exception as e:
        current_app.logger.error(f"Error in get_tasks_by_date_range: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 400
    finally:
        session.close()


@tasks_bp.route('/jobs/available', methods=['GET'])
@token_required
@require_tenant
def get_available_jobs(tenant_id, employee_id):
    """Get projects ready to be scheduled"""
    session = SessionLocal()
    try:
        current_app.logger.info("📋 Fetching available jobs for scheduling...")
        
        # Get projects in schedulable stages
        query = text("""
            SELECT 
                p.project_id,
                p.project_title,
                p.display_id,
                c.client_id,
                c.client_company_name,
                p.status
            FROM "StreemLyne_MT"."Project_Details" p
            LEFT JOIN "StreemLyne_MT"."Client_Master" c 
                ON p.client_id = c.client_id
                AND p.tenant_id = c.tenant_id
            WHERE p.tenant_id = :tenant_id
                AND p.status IN ('Survey', 'Delivery', 'Installation', 'Active', 'In Progress')
            ORDER BY p.created_at DESC
        """)
        
        projects = session.execute(query, {'tenant_id': str(tenant_id)}).fetchall()
        
        current_app.logger.info(f"✅ Found {len(projects)} projects")
        
        result = []
        for p in projects:
            result.append({
                'id': str(p.project_id),
                'job_reference': f"PRJ-{p.display_id}" if p.display_id else f"PRJ-{p.project_id}",
                'customer_name': p.client_company_name or 'Unknown',
                'customer_id': str(p.client_id) if p.client_id else None,
                'job_type': 'Project',
                'stage': 'Active',
                'work_stage': p.status or 'Survey'
            })
        
        return jsonify(result)
    except Exception as e:
        current_app.logger.error(f"❌ Error in get_available_jobs: {e}")
        import traceback
        traceback.print_exc()
        return jsonify([]), 200
    finally:
        session.close()


@tasks_bp.route('/customers/active', methods=['GET'])
@token_required
@require_tenant
def get_active_customers(tenant_id, employee_id):
    """Get active clients for tasks"""
    session = SessionLocal()
    try:
        current_app.logger.info("📋 Fetching active clients...")
        
        query = text("""
            SELECT 
                client_id,
                client_company_name,
                address,
                client_phone,
                stage
            FROM "StreemLyne_MT"."Client_Master"
            WHERE tenant_id = :tenant_id
                AND is_deleted = false
            ORDER BY client_company_name
        """)
        
        clients = session.execute(query, {'tenant_id': str(tenant_id)}).fetchall()
        
        current_app.logger.info(f"✅ Found {len(clients)} clients")
        
        result = []
        for c in clients:
            result.append({
                'id': str(c.client_id),
                'name': c.client_company_name,
                'address': c.address or '',
                'phone': c.client_phone or '',
                'stage': c.stage or 'Lead',
                'status': 'Active'
            })
        
        return jsonify(result)
    except Exception as e:
        current_app.logger.error(f"❌ Error in get_active_customers: {e}")
        import traceback
        traceback.print_exc()
        return jsonify([]), 200
    finally:
        session.close()


@tasks_bp.route('/jobs/work-stages', methods=['GET'])
@token_required
@require_tenant
def get_job_work_stages(tenant_id, employee_id):
    """Get all job work stages with metadata"""
    work_stages = [
        {
            'value': 'Survey',
            'label': 'Survey',
            'description': 'Site survey and measurements',
            'color': '#8B5CF6',
            'icon': '📏',
            'order': 1
        },
        {
            'value': 'Delivery',
            'label': 'Delivery',
            'description': 'Items being delivered',
            'color': '#06B6D4',
            'icon': '🚚',
            'order': 2
        },
        {
            'value': 'Installation',
            'label': 'Installation',
            'description': 'On-site installation',
            'color': '#14B8A6',
            'icon': '🏗️',
            'order': 3
        }
    ]
    
    return jsonify(work_stages), 200