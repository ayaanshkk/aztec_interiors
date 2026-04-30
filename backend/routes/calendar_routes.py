from flask import Blueprint, request, jsonify, current_app
from sqlalchemy import text
from datetime import datetime, timedelta

from ..db import SessionLocal
from .auth_helpers import token_required, require_tenant

calendar_bp = Blueprint('calendar', __name__)

@calendar_bp.route('/calendar/tasks', methods=['GET'])
@token_required
@require_tenant
def get_calendar_tasks(tenant_id, employee_id):
    """Get all tasks for calendar view with date range filtering"""
    session = SessionLocal()
    try:
        # Get query parameters
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        assigned_to = request.args.get('assigned_to_employee_id')
        
        # Build WHERE conditions
        where_conditions = ["t.tenant_id = :tenant_id"]
        params = {'tenant_id': str(tenant_id)}
        
        # Date range filtering
        if start_date:
            where_conditions.append("t.start_date >= :start_date")
            params['start_date'] = start_date
        
        if end_date:
            where_conditions.append("t.start_date <= :end_date")
            params['end_date'] = end_date
        
        # Employee filtering
        if assigned_to:
            where_conditions.append("t.assigned_to_employee_id = :assigned_to")
            params['assigned_to'] = int(assigned_to)
        
        where_clause = " AND ".join(where_conditions)
        
        query = text(f"""
            SELECT 
                t.task_id,
                t.title,
                t.type,
                t.start_date,
                t.end_date,
                t.start_time,
                t.end_time,
                t.estimated_hours,
                t.assigned_to_employee_id,
                t.team_member,
                t.client_id,
                t.project_id,
                t.opportunity_id,
                t.job_type,
                t.priority,
                t.status,
                t.notes,
                c.client_company_name as customer_name
            FROM "StreemLyne_MT"."Tasks" t
            LEFT JOIN "StreemLyne_MT"."Client_Master" c 
                ON t.client_id = c.client_id
            WHERE {where_clause}
            ORDER BY t.start_date ASC, t.start_time ASC
        """)
        
        tasks = session.execute(query, params).fetchall()
        
        # Format for calendar
        result = []
        for task in tasks:
            # Create calendar event
            event = {
                'id': task.task_id,
                'title': task.title,
                'type': task.type,
                'start': task.start_date.isoformat() if task.start_date else None,
                'end': task.end_date.isoformat() if task.end_date else None,
                'startTime': task.start_time.strftime('%H:%M') if task.start_time else None,
                'endTime': task.end_time.strftime('%H:%M') if task.end_time else None,
                'estimatedHours': task.estimated_hours,
                'assignedTo': task.team_member,
                'assignedToEmployeeId': task.assigned_to_employee_id,
                'customerId': task.client_id,
                'customerName': task.customer_name,
                'projectId': task.project_id,
                'opportunityId': task.opportunity_id,
                'jobType': task.job_type,
                'priority': task.priority,
                'status': task.status,
                'notes': task.notes,
                'allDay': task.start_time is None
            }
            result.append(event)
        
        return jsonify(result), 200
        
    except Exception as e:
        current_app.logger.error(f"Error fetching calendar tasks: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@calendar_bp.route('/calendar/tasks/<task_id>/move', methods=['PATCH'])
@token_required
@require_tenant
def move_calendar_task(task_id, tenant_id, employee_id):
    """Move a task to a new date (for drag and drop)"""
    session = SessionLocal()
    try:
        data = request.get_json()
        
        new_start_date = data.get('start_date')
        new_end_date = data.get('end_date')
        
        if not new_start_date:
            return jsonify({'error': 'Start date is required'}), 400
        
        # If no end date provided, use start date
        if not new_end_date:
            new_end_date = new_start_date
        
        update_query = text("""
            UPDATE "StreemLyne_MT"."Tasks"
            SET start_date = :start_date,
                end_date = :end_date,
                date = :start_date,
                updated_at = CURRENT_TIMESTAMP,
                updated_by_employee_id = :updated_by
            WHERE task_id = :task_id AND tenant_id = :tenant_id
        """)
        
        session.execute(update_query, {
            'start_date': new_start_date,
            'end_date': new_end_date,
            'task_id': task_id,
            'tenant_id': str(tenant_id),
            'updated_by': employee_id
        })
        session.commit()
        
        current_app.logger.info(f"✅ Task {task_id} moved to {new_start_date}")
        
        return jsonify({
            'success': True,
            'message': 'Task moved successfully'
        }), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error moving task: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@calendar_bp.route('/calendar/events', methods=['GET'])
@token_required
@require_tenant
def get_calendar_events(tenant_id, employee_id):
    """Get all calendar events (tasks + other events if any)
    
    This combines tasks with any other calendar-worthy events
    """
    session = SessionLocal()
    try:
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        
        # Get tasks
        where_conditions = ["tenant_id = :tenant_id"]
        params = {'tenant_id': str(tenant_id)}
        
        if start_date:
            where_conditions.append("start_date >= :start_date")
            params['start_date'] = start_date
        
        if end_date:
            where_conditions.append("start_date <= :end_date")
            params['end_date'] = end_date
        
        where_clause = " AND ".join(where_conditions)
        
        tasks_query = text(f"""
            SELECT 
                task_id as id,
                'task' as event_type,
                title,
                start_date,
                end_date,
                start_time,
                end_time,
                team_member,
                status,
                priority
            FROM "StreemLyne_MT"."Tasks"
            WHERE {where_clause}
            ORDER BY start_date ASC
        """)
        
        tasks = session.execute(tasks_query, params).fetchall()
        
        # Format events
        events = []
        for task in tasks:
            # Build full datetime strings if time is present
            start_str = task.start_date.isoformat()
            end_str = task.end_date.isoformat() if task.end_date else start_str
            
            if task.start_time:
                start_str += f'T{task.start_time.strftime("%H:%M:%S")}'
            if task.end_time and task.end_date:
                end_str += f'T{task.end_time.strftime("%H:%M:%S")}'
            
            events.append({
                'id': str(task.id),
                'title': task.title,
                'start': start_str,
                'end': end_str,
                'allDay': task.start_time is None,
                'type': task.event_type,
                'assignedTo': task.team_member,
                'status': task.status,
                'priority': task.priority,
                'backgroundColor': _get_event_color(task.status, task.priority)
            })
        
        return jsonify(events), 200
        
    except Exception as e:
        current_app.logger.error(f"Error fetching calendar events: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


def _get_event_color(status, priority):
    """Get calendar event color based on status and priority"""
    if status == 'Completed':
        return '#10b981'  # Green
    elif status == 'In Progress':
        return '#3b82f6'  # Blue
    elif status == 'Cancelled':
        return '#6b7280'  # Gray
    elif priority == 'High':
        return '#ef4444'  # Red
    elif priority == 'Medium':
        return '#f59e0b'  # Orange
    else:
        return '#8b5cf6'  # Purple (default)


@calendar_bp.route('/calendar/availability', methods=['GET'])
@token_required
@require_tenant
def get_team_availability(tenant_id, employee_id):
    """Get team availability for a date range"""
    session = SessionLocal()
    try:
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        
        if not start_date or not end_date:
            return jsonify({'error': 'start_date and end_date are required'}), 400
        
        # Get all tasks in date range grouped by employee
        query = text("""
            SELECT 
                assigned_to_employee_id,
                team_member,
                COUNT(*) as task_count,
                SUM(estimated_hours) as total_hours
            FROM "StreemLyne_MT"."Tasks"
            WHERE tenant_id = :tenant_id
                AND start_date >= :start_date
                AND start_date <= :end_date
                AND assigned_to_employee_id IS NOT NULL
            GROUP BY assigned_to_employee_id, team_member
            ORDER BY total_hours DESC
        """)
        
        availability = session.execute(query, {
            'tenant_id': str(tenant_id),
            'start_date': start_date,
            'end_date': end_date
        }).fetchall()
        
        result = []
        for row in availability:
            result.append({
                'employee_id': row.assigned_to_employee_id,
                'employee_name': row.team_member,
                'task_count': row.task_count,
                'total_hours': float(row.total_hours) if row.total_hours else 0,
                'availability_status': 'busy' if (row.total_hours or 0) > 40 else 'available'
            })
        
        return jsonify(result), 200
        
    except Exception as e:
        current_app.logger.error(f"Error fetching team availability: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()