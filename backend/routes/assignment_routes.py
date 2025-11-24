from flask import Blueprint, request, jsonify, current_app
from datetime import datetime
from ..models import User, Assignment, Job, Customer
from .auth_routes import token_required
from ..db import SessionLocal

assignment_bp = Blueprint('assignments', __name__)

@assignment_bp.route('/assignments', methods=['GET', 'POST'])
@token_required
def handle_assignments():
    current_user = request.current_user
    
    if request.method == 'POST':
        session = SessionLocal()
        
        try:
            data = request.json
            current_app.logger.info(f"📝 Creating assignment with data: {data}")
            
            # Parse date
            assignment_date = datetime.strptime(data['date'], '%Y-%m-%d').date()
            
            # Parse times if provided
            start_time = None
            end_time = None
            if data.get('start_time'):
                try:
                    start_time = datetime.strptime(data['start_time'], '%H:%M').time()
                except ValueError:
                    current_app.logger.warning(f"Invalid start_time format: {data['start_time']}")
            
            if data.get('end_time'):
                try:
                    end_time = datetime.strptime(data['end_time'], '%H:%M').time()
                except ValueError:
                    current_app.logger.warning(f"Invalid end_time format: {data['end_time']}")
            
            # Calculate hours
            estimated_hours = data.get('estimated_hours')
            if isinstance(estimated_hours, str):
                try:
                    estimated_hours = float(estimated_hours) if estimated_hours else None
                except ValueError:
                    estimated_hours = None

            # Get assigned user info
            user_id = data.get('user_id')
            team_member_name = None
            if user_id:
                assigned_user = session.get(User, user_id) 
                if assigned_user:
                    team_member_name = assigned_user.full_name
                else:
                    current_app.logger.warning(f"User {user_id} not found")
            
            # Get creator info
            creator = session.get(User, current_user.id)
            created_by_name = creator.full_name if creator else None
                
            # Create assignment
            assignment = Assignment(
                type=data.get('type', 'job'),
                title=data.get('title', ''),
                date=assignment_date,
                user_id=user_id,
                team_member=team_member_name,
                created_by=current_user.id,
                job_id=data.get('job_id'),
                customer_id=data.get('customer_id'),
                start_time=start_time,
                end_time=end_time,
                estimated_hours=estimated_hours,
                notes=data.get('notes', ''),
                priority=data.get('priority', 'Medium'),
                status=data.get('status', 'Scheduled'),
                job_type=data.get('job_type')
            )
            
            session.add(assignment)
            session.commit()
            session.refresh(assignment)

            current_app.logger.info(f"✅ Assignment created: {assignment.id}")

            # Build response dict
            result = assignment.to_dict()
            
            # Add creator name if not already present
            if 'created_by_name' not in result or not result['created_by_name']:
                result['created_by_name'] = created_by_name

            return jsonify({
                'message': 'Assignment created successfully',
                'assignment': result
            }), 201

        except KeyError as e:
            session.rollback()
            current_app.logger.error(f"Missing required field: {e}")
            return jsonify({'error': f'Missing required field: {str(e)}'}), 400
        except Exception as e:
            session.rollback()
            current_app.logger.error(f"Error creating assignment: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({'error': str(e)}), 500
        finally:
            session.close()
    
    # GET
    if request.method == 'GET':
        session = SessionLocal()
        try:
            current_app.logger.info(f"📋 Fetching assignments for user: {current_user.full_name} (role: {current_user.role})")
            
            query = session.query(Assignment)

            # Non-managers only see their own assignments
            if current_user.role != 'Manager':
                query = query.filter(Assignment.user_id == current_user.id)
            
            assignments = query.order_by(Assignment.date.desc()).all()
            
            current_app.logger.info(f"✅ Found {len(assignments)} assignments")

            result = []
            for a in assignments:
                try:
                    assignment_dict = a.to_dict()
                    
                    # Ensure creator and updater names are included
                    if a.created_by and ('created_by_name' not in assignment_dict or not assignment_dict['created_by_name']):
                        creator = session.get(User, a.created_by)
                        if creator:
                            assignment_dict['created_by_name'] = creator.full_name
                    
                    if a.updated_by and ('updated_by_name' not in assignment_dict or not assignment_dict['updated_by_name']):
                        updater = session.get(User, a.updated_by)
                        if updater:
                            assignment_dict['updated_by_name'] = updater.full_name
                    
                    result.append(assignment_dict)
                except Exception as dict_error:
                    current_app.logger.error(f"Error converting assignment {a.id} to dict: {dict_error}")
                    import traceback
                    traceback.print_exc()
                    continue
            
            return jsonify(result)
        except Exception as e:
            current_app.logger.error(f"Error in GET assignments: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({'error': str(e)}), 500
        finally:
            session.close()


@assignment_bp.route('/assignments/<string:assignment_id>', methods=['GET', 'PUT', 'DELETE'])
@token_required
def handle_single_assignment(assignment_id):
    current_user = request.current_user
    
    session = SessionLocal()
    try:
        assignment = session.get(Assignment, assignment_id) 
        
        if not assignment:
            return jsonify({'error': 'Assignment not found'}), 404
        
        # Authorization Check
        if request.method in ['PUT', 'DELETE', 'GET']:
            is_manager = current_user.role == 'Manager'
            is_assigned_user = assignment.user_id == current_user.id
            is_creator = assignment.created_by == current_user.id
            
            if not is_manager and not is_assigned_user and not is_creator:
                # Allow status updates for assigned users
                if request.method == 'PUT' and list(request.json.keys()) == ['status']:
                    pass 
                else:
                    return jsonify({'error': 'Unauthorized access to assignment'}), 403
        
        # GET
        if request.method == 'GET':
            result = assignment.to_dict()
            
            # Add user names if not present
            if assignment.created_by and ('created_by_name' not in result or not result['created_by_name']):
                creator = session.get(User, assignment.created_by)
                if creator:
                    result['created_by_name'] = creator.full_name
            
            if assignment.updated_by and ('updated_by_name' not in result or not result['updated_by_name']):
                updater = session.get(User, assignment.updated_by)
                if updater:
                    result['updated_by_name'] = updater.full_name
            
            return jsonify(result)
        
        # PUT
        elif request.method == 'PUT':
            data = request.json
            current_app.logger.info(f"📝 Updating assignment {assignment_id} with data: {data}")
            
            if 'type' in data:
                assignment.type = data['type']
            if 'title' in data:
                assignment.title = data['title']
            if 'date' in data:
                assignment.date = datetime.strptime(data['date'], '%Y-%m-%d').date()
            if 'start_time' in data:
                try:
                    assignment.start_time = datetime.strptime(data['start_time'], '%H:%M').time() if data['start_time'] else None
                except ValueError:
                    current_app.logger.warning(f"Invalid start_time: {data['start_time']}")
            if 'end_time' in data:
                try:
                    assignment.end_time = datetime.strptime(data['end_time'], '%H:%M').time() if data['end_time'] else None
                except ValueError:
                    current_app.logger.warning(f"Invalid end_time: {data['end_time']}")
            if 'estimated_hours' in data:
                estimated_hours = data['estimated_hours']
                try:
                    assignment.estimated_hours = float(estimated_hours) if isinstance(estimated_hours, str) else estimated_hours
                except (ValueError, TypeError):
                    current_app.logger.warning(f"Invalid estimated_hours: {estimated_hours}")
            if 'notes' in data:
                assignment.notes = data['notes']
            if 'priority' in data:
                assignment.priority = data['priority']
            if 'status' in data:
                assignment.status = data['status']
            if 'job_type' in data:
                assignment.job_type = data['job_type']
            if 'job_id' in data:
                assignment.job_id = data['job_id']
            if 'customer_id' in data:
                assignment.customer_id = data['customer_id']
            if 'user_id' in data:
                assignment.user_id = data['user_id']
                new_user = session.get(User, data['user_id'])
                if new_user:
                    assignment.team_member = new_user.full_name
                
            assignment.updated_by = current_user.id
            assignment.updated_at = datetime.utcnow()
            
            session.commit()
            session.refresh(assignment)
            
            current_app.logger.info(f"✅ Assignment {assignment_id} updated successfully")
            
            result = assignment.to_dict()
            
            # Add updater name
            updater = session.get(User, current_user.id)
            if updater:
                result['updated_by_name'] = updater.full_name
            
            return jsonify({
                'message': 'Assignment updated successfully',
                'assignment': result
            })
            
        # DELETE
        elif request.method == 'DELETE':
            current_app.logger.info(f"🗑️ Deleting assignment {assignment_id}")
            session.delete(assignment)
            session.commit()
            current_app.logger.info(f"✅ Assignment {assignment_id} deleted")
            
            return jsonify({'message': 'Assignment deleted successfully'})
        
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error in handle_single_assignment: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@assignment_bp.route('/assignments/by-date-range', methods=['GET'])
@token_required 
def get_assignments_by_date_range():
    """Get assignments within a date range"""
    current_user = request.current_user
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    if not start_date or not end_date:
        return jsonify({'error': 'start_date and end_date are required'}), 400
    
    session = SessionLocal()
    try:
        start = datetime.strptime(start_date, '%Y-%m-%d').date()
        end = datetime.strptime(end_date, '%Y-%m-%d').date()
        
        current_app.logger.info(f"📅 Fetching assignments from {start} to {end}")
        
        query = session.query(Assignment).filter(
            Assignment.date >= start,
            Assignment.date <= end
        )
        
        if current_user.role != 'Manager':
            query = query.filter(Assignment.user_id == current_user.id)
            
        assignments = query.order_by(Assignment.date).all()
        
        current_app.logger.info(f"✅ Found {len(assignments)} assignments in date range")
        
        result = []
        for a in assignments:
            try:
                assignment_dict = a.to_dict()
                
                # Add user names
                if a.created_by:
                    creator = session.get(User, a.created_by)
                    if creator:
                        assignment_dict['created_by_name'] = creator.full_name
                
                if a.updated_by:
                    updater = session.get(User, a.updated_by)
                    if updater:
                        assignment_dict['updated_by_name'] = updater.full_name
                
                result.append(assignment_dict)
            except Exception as e:
                current_app.logger.error(f"Error processing assignment {a.id}: {e}")
                continue
        
        return jsonify(result)
    except Exception as e:
        current_app.logger.error(f"Error in get_assignments_by_date_range: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 400
    finally:
        session.close()


@assignment_bp.route('/jobs/available', methods=['GET'])
@token_required 
def get_available_jobs():
    """
    Get jobs that are ready to be scheduled
    
    Simple 3-stage system:
    - Survey: Initial measurement/planning stage
    - Delivery: Items ready for delivery
    - Installation: Ready for installation
    """
    session = SessionLocal()
    try:
        current_app.logger.info("📋 Fetching available jobs for scheduling...")
        
        # ✅ All 3 work stages are schedulable
        schedulable_work_stages = ['Survey', 'Delivery', 'Installation']
        
        jobs = session.query(Job).filter(
            Job.work_stage.in_(schedulable_work_stages)
        ).order_by(Job.created_at.desc()).all()
        
        current_app.logger.info(f"✅ Found {len(jobs)} jobs in schedulable stages")
        
        result = []
        for j in jobs:
            try:
                customer_name = 'Unknown'
                customer_id = None
                
                # Handle both relationship and direct customer_id
                if hasattr(j, 'customer') and j.customer:
                    customer_name = j.customer.name
                    customer_id = j.customer.id
                elif j.customer_id:
                    customer_id = j.customer_id
                    # Try to fetch customer
                    customer = session.get(Customer, j.customer_id)
                    if customer:
                        customer_name = customer.name
                
                result.append({
                    'id': j.id,
                    'job_reference': j.job_reference or f"JOB-{j.id}",
                    'customer_name': customer_name,
                    'customer_id': customer_id,
                    'job_type': j.job_type or 'Interior Design',
                    'stage': j.stage if hasattr(j, 'stage') else 'Unknown',
                    'work_stage': j.work_stage if hasattr(j, 'work_stage') else 'Survey'
                })
            except Exception as job_error:
                current_app.logger.error(f"Error processing job {j.id}: {job_error}")
                import traceback
                traceback.print_exc()
                continue
        
        current_app.logger.info(f"✅ Returning {len(result)} jobs")
        return jsonify(result)
    except Exception as e:
        current_app.logger.error(f"❌ Error in get_available_jobs: {e}")
        import traceback
        traceback.print_exc()
        # ✅ Return empty array instead of error to allow graceful degradation
        current_app.logger.info("⚠️ Returning empty jobs array due to error")
        return jsonify([]), 200
    finally:
        session.close()


@assignment_bp.route('/customers/active', methods=['GET'])
@token_required 
def get_active_customers():
    """Get active customers for assignments"""
    session = SessionLocal()
    try:
        current_app.logger.info("📋 Fetching active customers...")
        
        # Get all customers
        customers = session.query(Customer).order_by(Customer.name).all()
        
        current_app.logger.info(f"✅ Found {len(customers)} customers")
        
        result = []
        for c in customers:
            try:
                result.append({
                    'id': c.id,
                    'name': c.name,
                    'address': c.address or '',
                    'phone': c.phone or '',
                    'stage': c.stage or 'Lead',
                    'status': c.status if hasattr(c, 'status') else 'Active'
                })
            except Exception as customer_error:
                current_app.logger.error(f"Error processing customer {c.id}: {customer_error}")
                import traceback
                traceback.print_exc()
                continue
        
        current_app.logger.info(f"✅ Returning {len(result)} customers")
        return jsonify(result)
    except Exception as e:
        current_app.logger.error(f"❌ Error in get_active_customers: {e}")
        import traceback
        traceback.print_exc()
        # ✅ Return empty array instead of error to allow graceful degradation
        current_app.logger.info("⚠️ Returning empty customers array due to error")
        return jsonify([]), 200
    finally:
        session.close()


@assignment_bp.route('/jobs/work-stages', methods=['GET'])
@token_required
def get_job_work_stages():
    """
    Get all 3 job work stages with metadata
    """
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