from flask import Blueprint, session, redirect, url_for, request, flash, render_template, jsonify
from werkzeug.security import generate_password_hash
import datetime
import random
import json
from ..database.db import get_db, query_db
from ..auth.routes import admin_required
from ..utils.email import send_email
from ..utils.ai import generate_gemini_message

bp = Blueprint('admin', __name__)

@bp.route('/dashboard')
@admin_required
def dashboard():
    """Admin dashboard, scope the query by church_id to ensure data isolation."""
    church_id = session.get('church_id')
    church = query_db('SELECT * FROM churches WHERE id = ?', [church_id], one=True)
    return render_template('admin_dashboard.html', church=church)

@bp.route('/setup', methods=['GET', 'POST'])
@admin_required
def setup():
    church_id = session.get('church_id')
    db = get_db()
    if request.method == 'POST':
        name = request.form['name']
        scheduling_rules = request.form['scheduling_rules']

        db.execute('UPDATE churches SET name = ?, scheduling_rules = ? WHERE id = ?',
                   (name, scheduling_rules, church_id))

        db.execute('DELETE FROM worship_services WHERE church_id = ?', (church_id,))

        service_days = request.form.getlist('service_day')
        service_times = request.form.getlist('service_time')
        service_activities = request.form.getlist('service_activities')
        for day, time_val, activities in zip(service_days, service_times, service_activities):
            if day.strip() and time_val.strip() and activities.strip():
                db.execute('INSERT INTO worship_services (church_id, day, time, activities) VALUES (?, ?, ?, ?)',
                           (church_id, day.strip(), time_val.strip(), activities.strip()))
        db.commit()
        flash('Church setup updated')
        return redirect(url_for('admin.setup'))

    church = query_db('SELECT * FROM churches WHERE id = ?', [church_id], one=True)
    services = query_db('SELECT * FROM worship_services WHERE church_id = ?', [church_id])
    
    # Sort services by day and time
    day_order = {
        'Sunday': 0, 'Monday': 1, 'Tuesday': 2, 'Wednesday': 3,
        'Thursday': 4, 'Friday': 5, 'Saturday': 6
    }
    
    # Convert time strings to datetime.time objects for proper sorting
    from datetime import datetime
    def parse_time(time_str):
        try:
            return datetime.strptime(time_str.strip(), '%I:%M %p').time()
        except ValueError:
            # Return a default time for invalid formats
            return datetime.strptime('12:00 AM', '%I:%M %p').time()
    
    # Sort the services list
    services = sorted(services, key=lambda x: (
        day_order.get(x['day'].strip(), 7),
        parse_time(x['time'])
    ))
    
    return render_template('admin_setup.html', church=church, services=services)

@bp.route('/generate_roster', methods=['GET', 'POST'])
@admin_required
def generate_roster():
    if request.method == 'POST':
        month = int(request.form['month'])
        year = int(request.form['year'])
        church_id = session.get('church_id')

        services = query_db('SELECT * FROM worship_services WHERE church_id = ?', [church_id])
        if not services:
            flash('No worship services defined. Please set up worship services first.')
            return redirect(url_for('admin.setup'))

        members = query_db(
            'SELECT * FROM users WHERE church_id = ? AND role = "member"',
            [church_id]
        )
        if not members:
            flash('No members to assign duties.')
            return redirect(url_for('admin.generate_roster'))

        eligibility_records = query_db(
            'SELECT user_id, activity FROM activity_eligibility WHERE church_id = ?',
            [church_id]
        )
        eligibility = {}
        for record in eligibility_records:
            if record['activity'] not in eligibility:
                eligibility[record['activity']] = []
            eligibility[record['activity']].append(record['user_id'])

        db = get_db()
        start_date = datetime.date(year, month, 1)
        if month == 12:
            end_date = datetime.date(year + 1, 1, 1)
        else:
            end_date = datetime.date(year, month + 1, 1)

        db.execute(
            'DELETE FROM duty_roster WHERE church_id = ? AND duty_date >= ? AND duty_date < ?',
            (church_id, start_date.isoformat(), end_date.isoformat())
        )

        day_to_weekday = {
            'Monday': 0, 'Tuesday': 1, 'Wednesday': 2, 'Thursday': 3,
            'Friday': 4, 'Saturday': 5, 'Sunday': 6
        }

        activity_member_index = {}
        date_iter = start_date
        while date_iter < end_date:
            for service in services:
                service_day = service['day'].strip().title()
                service_weekday = day_to_weekday.get(service_day)
                
                if service_weekday == date_iter.weekday():
                    activities = list(set([act.strip() for act in service['activities'].split(',')]))
                    assigned_activities = set()
                    
                    for activity in activities:
                        if activity in assigned_activities:
                            continue
                            
                        eligible_member_ids = eligibility.get(activity, [])
                        if not eligible_member_ids:
                            continue
                            
                        eligible_members = [m for m in members if m['id'] in eligible_member_ids]
                        if not eligible_members:
                            continue
                            
                        if activity not in activity_member_index:
                            activity_member_index[activity] = 0
                            
                        member = eligible_members[activity_member_index[activity] % len(eligible_members)]
                        activity_member_index[activity] += 1
                        
                        existing_assignment = query_db(
                            '''SELECT * FROM duty_roster 
                               WHERE church_id = ? AND duty_date = ? AND activity = ?''',
                            [church_id, date_iter.isoformat(), activity],
                            one=True
                        )
                        
                        if not existing_assignment:
                            db.execute(
                                'INSERT INTO duty_roster (church_id, duty_date, activity, user_id) VALUES (?, ?, ?, ?)',
                                (church_id, date_iter.isoformat(), activity, member['id'])
                            )
                            assigned_activities.add(activity)
                            send_email(
                                member['email'],
                                "Duty Roster Assignment",
                                f"You are assigned to {activity} on {date_iter.isoformat()} at {service['time']}."
                            )
            
            date_iter += datetime.timedelta(days=1)

        db.commit()
        flash('Duty roster generated successfully.')
        return redirect(url_for('admin.roster'))

    return render_template('admin_generate_roster.html')

@bp.route('/roster')
@admin_required
def roster():
    """View entire duty roster for the current admin's church only."""
    church_id = session.get('church_id')
    
    services = query_db('SELECT * FROM worship_services WHERE church_id = ?', [church_id])
    if not services:
        flash('No worship services defined. Please set up worship services first.')
        return redirect(url_for('admin.setup'))
    
    raw_assignments = query_db(
        '''SELECT dr.duty_date, dr.activity, u.name as member_name, dr.id as roster_id
           FROM duty_roster dr 
           JOIN users u ON dr.user_id = u.id 
           WHERE dr.church_id = ? 
           ORDER BY dr.duty_date''',
        [church_id]
    )
    
    assignments_by_service = {}
    day_to_weekday = {
        'Monday': 0, 'Tuesday': 1, 'Wednesday': 2, 'Thursday': 3,
        'Friday': 4, 'Saturday': 5, 'Sunday': 6
    }
    
    for assignment in raw_assignments:
        date = datetime.date.fromisoformat(assignment['duty_date'])
        weekday = date.weekday()
        
        for service in services:
            service_day = service['day'].strip().title()
            service_weekday = day_to_weekday.get(service_day)
            
            if service_weekday == weekday:
                service_key = f"{assignment['duty_date']} {service['time']}"
                
                if service_key not in assignments_by_service:
                    assignments_by_service[service_key] = {
                        'date': assignment['duty_date'],
                        'time': service['time'],
                        'day': service['day'],
                        'assignments': []
                    }
                
                assignments_by_service[service_key]['assignments'].append({
                    'activity': assignment['activity'],
                    'member': assignment['member_name'],
                    'roster_id': assignment['roster_id']
                })
    
    sorted_service_keys = sorted(assignments_by_service.keys())
    
    return render_template('admin_roster.html', 
                         services=services,
                         assignments_by_service=assignments_by_service,
                         sorted_service_keys=sorted_service_keys)

@bp.route('/roster/delete_all', methods=['POST'])
@admin_required
def delete_all_rosters():
    """Delete all duty roster entries for the admin's church."""
    church_id = session.get('church_id')
    db = get_db()
    db.execute('DELETE FROM duty_roster WHERE church_id = ?', [church_id])
    db.commit()
    flash('All roster assignments have been deleted.')
    return redirect(url_for('admin.roster'))

@bp.route('/roster/delete_service/<date>/<time>', methods=['POST'])
@admin_required
def delete_service_roster(date, time):
    """Delete all duty roster entries for a specific service date and time."""
    church_id = session.get('church_id')
    db = get_db()
    db.execute('DELETE FROM duty_roster WHERE church_id = ? AND duty_date = ?', 
               [church_id, date])
    db.commit()
    flash(f'Roster assignments for {date} at {time} have been deleted.')
    return redirect(url_for('admin.roster'))

@bp.route('/substitutions', methods=['GET', 'POST'])
@admin_required
def substitutions():
    church_id = session.get('church_id')
    db = get_db()

    if request.method == 'POST':
        req_id = request.form['request_id']
        action = request.form['action']

        sub_req = query_db(
            '''SELECT sr.*, dr.church_id
               FROM substitution_requests sr
               JOIN duty_roster dr ON sr.duty_id = dr.id
               WHERE sr.id = ? AND dr.church_id = ?''',
            [req_id, church_id],
            one=True
        )
        if not sub_req:
            flash('Invalid request (substitution request not found or belongs to another church).')
            return redirect(url_for('admin.substitutions'))

        if action == 'approve':
            db.execute('UPDATE substitution_requests SET status = ? WHERE id = ?', ('approved', req_id))
            db.execute('UPDATE duty_roster SET user_id = ? WHERE id = ?', 
                      (sub_req['requested_substitute_id'], sub_req['duty_id']))

            requester = query_db('SELECT * FROM users WHERE id = ?', [sub_req['requester_id']], one=True)
            substitute = query_db('SELECT * FROM users WHERE id = ?', 
                                [sub_req['requested_substitute_id']], one=True)

            if requester:
                send_email(requester['email'], "Substitution Approved", 
                         "Your substitution request has been approved.")
            if substitute:
                send_email(substitute['email'], "New Duty Assignment", 
                         "You have been assigned a new duty.")

            db.commit()

        elif action == 'deny':
            db.execute('UPDATE substitution_requests SET status = ? WHERE id = ?', ('denied', req_id))
            db.commit()

        flash('Substitution request updated.')
        return redirect(url_for('admin.substitutions'))

    requests_list = query_db(
      '''SELECT sr.*, dr.duty_date, dr.activity,
                u1.name as requester_name, u2.name as substitute_name
         FROM substitution_requests sr
         JOIN duty_roster dr ON sr.duty_id = dr.id
         JOIN users u1 ON sr.requester_id = u1.id
         JOIN users u2 ON sr.requested_substitute_id = u2.id
         WHERE dr.church_id = ?''',
      [church_id]
    )
    return render_template('admin_substitutions.html', requests=requests_list)

@bp.route('/eligibility', methods=['GET', 'POST'])
@admin_required
def eligibility():
    """Manage which members are eligible for which activities."""
    church_id = session.get('church_id')
    db = get_db()

    if request.method == 'POST':
        db.execute('DELETE FROM activity_eligibility WHERE church_id = ?', [church_id])
        
        members = query_db('SELECT id FROM users WHERE church_id = ? AND role = "member"', [church_id])
        all_activities = set()
        services = query_db('SELECT activities FROM worship_services WHERE church_id = ?', [church_id])
        for service in services:
            activities = [act.strip() for act in service['activities'].split(',')]
            all_activities.update(activities)
        
        for member in members:
            for activity in all_activities:
                checkbox_name = f"eligibility_{member['id']}_{activity}"
                if checkbox_name in request.form:
                    db.execute(
                        'INSERT INTO activity_eligibility (church_id, user_id, activity) VALUES (?, ?, ?)',
                        [church_id, member['id'], activity]
                    )
        
        db.commit()
        flash('Activity eligibility updated successfully.')
        return redirect(url_for('admin.eligibility'))

    members = query_db(
        'SELECT id, name FROM users WHERE church_id = ? AND role = "member" ORDER BY name',
        [church_id]
    )
    
    all_activities = set()
    services = query_db('SELECT activities FROM worship_services WHERE church_id = ?', [church_id])
    for service in services:
        activities = [act.strip() for act in service['activities'].split(',')]
        all_activities.update(activities)
    all_activities = sorted(list(all_activities))
    
    eligibility = set()
    eligibility_records = query_db(
        'SELECT user_id, activity FROM activity_eligibility WHERE church_id = ?',
        [church_id]
    )
    for record in eligibility_records:
        eligibility.add((record['user_id'], record['activity']))
    
    return render_template(
        'admin_eligibility.html',
        members=members,
        all_activities=all_activities,
        eligibility=eligibility
    )

@bp.route('/generate_dummy_members', methods=['GET', 'POST'])
@admin_required
def generate_dummy_members():
    church_id = session.get('church_id')
    db = get_db()
    if request.method == 'POST':
        db.execute('DELETE FROM users WHERE church_id = ? AND role = "member"', (church_id,))

        first_names = ["James", "John", "Robert", "Michael", "William", "David", "Richard", "Joseph", "Thomas", "Charles",
                    "Christopher", "Daniel", "Matthew", "Anthony", "Donald", "Mark", "Paul", "Steven", "Andrew", "Kenneth",
                    "Joshua", "Kevin", "Brian", "George", "Timothy", "Ronald", "Edward", "Jason", "Jeffrey", "Ryan",
                    "Jacob", "Gary", "Nicholas", "Eric", "Jonathan", "Stephen", "Larry", "Justin", "Scott", "Brandon"]
        last_names = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez", "Martinez",
                    "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin",
                    "Lee", "Perez", "Thompson", "White", "Harris", "Sanchez", "Clark", "Ramirez", "Lewis", "Robinson",
                    "Walker", "Young", "Allen", "King", "Wright", "Scott", "Torres", "Nguyen", "Hill", "Flores"]

        count = int(request.form.get('count', 40)) or 40

        for i in range(count):
            first_name = first_names[i % len(first_names)]  # Use modulo to cycle through names if count > len(first_names)
            last_name = random.choice(last_names)
            name = f"{first_name} {last_name}"
            email = f"{first_name.lower()}.{last_name.lower()}@example.com"
            hashed_pw = generate_password_hash("memberpass")

            db.execute(
                'INSERT INTO users (name, email, password, role, church_id) VALUES (?, ?, ?, ?, ?)',
                (name, email, hashed_pw, "member", church_id)
            )
        db.commit()
        flash(f"Inserted {count} dummy members.")
        return redirect(url_for('admin.dashboard'))

    return render_template('generate_dummy_members.html')

@bp.route('/service/update', methods=['POST'])
@admin_required
def update_service():
    church_id = session.get('church_id')
    data = request.get_json()
    
    if not data or 'id' not in data:
        return jsonify({'success': False, 'error': 'Missing service ID'}), 400
        
    db = get_db()
    db.execute(
        'UPDATE worship_services SET day = ?, time = ?, activities = ? WHERE id = ? AND church_id = ?',
        (data['day'], data['time'], data['activities'], data['id'], church_id)
    )
    db.commit()
    return jsonify({'success': True})

@bp.route('/service/add', methods=['POST'])
@admin_required
def add_service():
    church_id = session.get('church_id')
    data = request.get_json()
    
    if not data or not all(key in data for key in ['day', 'time', 'activities']):
        return jsonify({'success': False, 'error': 'Missing required fields'}), 400
        
    db = get_db()
    cursor = db.execute(
        'INSERT INTO worship_services (church_id, day, time, activities) VALUES (?, ?, ?, ?)',
        (church_id, data['day'], data['time'], data['activities'])
    )
    service_id = cursor.lastrowid
    db.commit()
    return jsonify({'success': True, 'id': service_id})

@bp.route('/service/delete', methods=['POST'])
@admin_required
def delete_service():
    church_id = session.get('church_id')
    data = request.get_json()
    
    if not data or 'id' not in data:
        return jsonify({'success': False, 'error': 'Missing service ID'}), 400
        
    db = get_db()
    db.execute('DELETE FROM worship_services WHERE id = ? AND church_id = ?', (data['id'], church_id))
    db.commit()
    return jsonify({'success': True})


# admin/routes.py

@bp.route('/parse_worship_setup', methods=['POST'])
@admin_required
def parse_worship_setup():
    """Handle AI assistant requests for worship service setup."""
    data = request.get_json()
    if not data or 'instruction' not in data:
        return jsonify({'success': False, 'error': 'Missing instruction'}), 400

    church_id = session.get('church_id')
    try:
        # 1) Grab the existing services.
        existing_services = query_db(
            'SELECT * FROM worship_services WHERE church_id = ?',
            [church_id]
        )

        # 2) Convert them into a simple Python list of dicts, so we can feed that to the AI.
        #    We'll split activities into a list so the AI sees them clearly.
        existing_list = []
        for row in existing_services:
            acts = [act.strip() for act in row['activities'].split(',')]
            existing_list.append({
                "day": row['day'],
                "time": row['time'],
                "activities": acts
            })

        # 3) Call the AI, passing both the user's raw instruction and the existing services as context.
        new_services = generate_gemini_message(data['instruction'], existing_list)

        # 4) We now apply our two-pass logic (delete first, then upsert) or whatever logic you prefer.
        db = get_db()

        # Build a map of existing services keyed by (day, time).
        existing_map = {}
        for s in existing_services:
            key = (s['day'].strip(), s['time'].strip())
            existing_map[key] = s

        # PASS 1: Delete anything with "delete":true
        for service in new_services:
            if service.get('delete') is True:
                day = service['day'].strip()
                time = service['time'].strip()
                if (day, time) in existing_map:
                    db.execute(
                        'DELETE FROM worship_services WHERE id = ?',
                        (existing_map[(day, time)]['id'],)
                    )
                    del existing_map[(day, time)]

        # PASS 2: Upsert anything with "delete" != true
        for service in new_services:
            if not service.get('delete'):
                day = service['day'].strip()
                time = service['time'].strip()
                # If AI omitted activities or gave an empty list, you can decide how to handle it.
                # Possibly preserve the old ones if user simply changed day/time.
                if 'activities' not in service or not service['activities']:
                    # OPTIONAL: If user didn't mention new activities, let's see if old service existed:
                    old = existing_map.get((day, time))
                    if old:
                        # Keep the old activities
                        activity_string = old['activities']
                    else:
                        # No old entry, so default to empty
                        activity_string = ""
                else:
                    # AI did provide new activities
                    if isinstance(service['activities'], list):
                        activity_string = ", ".join(service['activities'])
                    else:
                        activity_string = str(service['activities'])

                if (day, time) in existing_map:
                    # Update
                    db.execute(
                        'UPDATE worship_services SET activities = ? WHERE id = ?',
                        (activity_string, existing_map[(day, time)]['id'])
                    )
                else:
                    # Insert new
                    cursor = db.execute(
                        '''INSERT INTO worship_services (church_id, day, time, activities)
                           VALUES (?, ?, ?, ?)''',
                        (church_id, day, time, activity_string)
                    )
                    new_id = cursor.lastrowid
                    existing_map[(day, time)] = {
                        'id': new_id,
                        'church_id': church_id,
                        'day': day,
                        'time': time,
                        'activities': activity_string
                    }

        db.commit()

        # Finally, reload everything for a fresh list to return to the client.
        updated_rows = query_db(
            'SELECT * FROM worship_services WHERE church_id = ?',
            [church_id]
        )

        worship_services = []
        for row in updated_rows:
            acts = [act.strip() for act in row['activities'].split(',')] if row['activities'] else []
            worship_services.append({
                'id': row['id'],
                'day': row['day'],
                'time': row['time'],
                'activities': acts
            })

        # Sort by day/time for consistent display
        day_order = {
            'Sunday': 0, 'Monday': 1, 'Tuesday': 2, 'Wednesday': 3,
            'Thursday': 4, 'Friday': 5, 'Saturday': 6
        }
        worship_services.sort(key=lambda x: (
            day_order.get(x['day'].strip(), 7),
            x['time'].strip()
        ))

        return jsonify({
            'success': True,
            'worship_services': worship_services
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
