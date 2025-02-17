import os
import json
import sqlite3
import datetime
import random
from functools import wraps

from flask import Flask, g, render_template, request, redirect, url_for, session, flash, jsonify
from flask_wtf.csrf import CSRFProtect

# For loading secrets from .env
from dotenv import load_dotenv

# For secure password storage
from werkzeug.security import generate_password_hash, check_password_hash

import google.generativeai as genai

load_dotenv()  # Loads environment variables from .env if present

app = Flask(__name__)

# -----------------------------------------------------------------------------
# SECURITY CONFIGURATION
# -----------------------------------------------------------------------------
# Load secret key from environment, fall back to a dev-only default if missing.
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY', 'f000c92d905b18ba4a027d29685e2577d25a9db1d270e1411e4f6bfa218c4489')
app.config["WTF_CSRF_ENABLED"] = True
app.config["WTF_CSRF_SECRET_KEY"] = "something-random"

# Secure cookies
app.config['SESSION_COOKIE_SECURE'] = False     # Send cookies only over HTTPS
app.config['SESSION_COOKIE_HTTPONLY'] = True   # Disallow JavaScript access to session cookie
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'  # Helps mitigate CSRF

# Enable CSRF protection for all form submissions
csrf = CSRFProtect(app)

DATABASE = 'duty_roster.db'

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db

def query_db(query, args=(), one=False):
    """Helper for parameterized SQL queries, avoiding manual DB repetition."""
    cur = get_db().execute(query, args)
    rv = cur.fetchall()
    cur.close()
    return (rv[0] if rv else None) if one else rv

# Use environment variable for your Generative AI API key
def generate_gemini_message(prompt: str, json_response_format: bool = False) -> str:
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        print("Warning: GENAI_API_KEY not set in environment.")
    genai.configure(api_key=api_key)

    # Example usage with your existing approach
    model = genai.GenerativeModel(model_name="gemini-1.5-flash")
    system_prompt = "You are an assistant that outputs only valid JSON with no extra text or commentary."
    combined_prompt = f"{system_prompt}\n{prompt}"

    if json_response_format:
        response = model.generate_content(
            combined_prompt,
            generation_config={'response_mime_type': 'application/json'}
        )
    else:
        response = model.generate_content(combined_prompt)

    print("Gemini response text:", response.text)
    return response.text

def init_db():
    with app.app_context():
        db = get_db()
        with app.open_resource('schema.sql', mode='r') as f:
            db.executescript(f.read())
        db.commit()

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def send_email(to, subject, body):
    """Stub for sending email; replace with real SMTP logic or an email service."""
    print(f"Sending email to {to} | Subject: {subject}\n{body}\n")

# -----------------------------------------------------------------------------
# AUTH DECORATORS
# -----------------------------------------------------------------------------
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session or session.get('role') != 'admin':
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/')
def index():
    if 'user_id' in session:
        if session.get('role') == 'admin':
            return redirect(url_for('admin_setup'))
        else:
            return redirect(url_for('member_dashboard'))
    return redirect(url_for('login'))


# -----------------------------------------------------------------------------
# LOGIN: Now uses hashed passwords with check_password_hash
# -----------------------------------------------------------------------------
@app.route('/login', methods=['GET', 'POST'])
@csrf.exempt  # Typically you'd use a WTForm for login, but can exempt a raw form
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        # Fetch user by email only
        user = query_db('SELECT * FROM users WHERE email = ?', [email], one=True)
        if user and check_password_hash(user['password'], password):
            # Correct password
            session['user_id'] = user['id']
            session['role'] = user['role']
            session['church_id'] = user['church_id']
            return redirect(url_for('index'))

        flash('Invalid credentials')
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


# -----------------------------------------------------------------------------
# ADMIN ROUTES
# -----------------------------------------------------------------------------
@app.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    """Admin dashboard, scope the query by church_id to ensure data isolation."""
    church_id = session.get('church_id')
    church = query_db('SELECT * FROM churches WHERE id = ?', [church_id], one=True)
    return render_template('admin_dashboard.html', church=church)

@app.route('/admin/setup', methods=['GET', 'POST'])
@admin_required
def admin_setup():
    church_id = session.get('church_id')
    db = get_db()
    if request.method == 'POST':
        name = request.form['name']
        scheduling_rules = request.form['scheduling_rules']

        # Always scope updates to the admin’s church_id for isolation
        db.execute('UPDATE churches SET name = ?, scheduling_rules = ? WHERE id = ?',
                   (name, scheduling_rules, church_id))

        # Delete all existing worship service records for this church
        db.execute('DELETE FROM worship_services WHERE church_id = ?', (church_id,))

        # Re-insert worship services from the POST form fields
        service_days = request.form.getlist('service_day')
        service_times = request.form.getlist('service_time')
        service_activities = request.form.getlist('service_activities')
        for day, time_val, activities in zip(service_days, service_times, service_activities):
            if day.strip() and time_val.strip() and activities.strip():
                db.execute('INSERT INTO worship_services (church_id, day, time, activities) VALUES (?, ?, ?, ?)',
                           (church_id, day.strip(), time_val.strip(), activities.strip()))
        db.commit()
        flash('Church setup updated')
        return redirect(url_for('admin_setup'))

    # GET: load the church record and current worship services
    church = query_db('SELECT * FROM churches WHERE id = ?', [church_id], one=True)
    services = query_db('SELECT * FROM worship_services WHERE church_id = ?', [church_id])
    return render_template('admin_setup.html', church=church, services=services)

@app.route('/admin/generate_roster', methods=['GET', 'POST'])
@admin_required
def admin_generate_roster():
    if request.method == 'POST':
        month = int(request.form['month'])
        year = int(request.form['year'])
        church_id = session.get('church_id')

        # Load the church record
        church = query_db('SELECT * FROM churches WHERE id = ?', [church_id], one=True)

        # You can store worship activities either in the church record or in worship_services
        # For demonstration, fallback to some default if none
        # (You might want to unify this approach or remove it if you use worship_services instead)
        if church and church['scheduling_rules']:
            # Just as a placeholder
            activities = ['Singing', 'Prayer', 'Preaching', 'Officiating']
        else:
            activities = ['Singing', 'Prayer', 'Preaching', 'Officiating']

        # Fetch members for this church
        members = query_db(
            'SELECT * FROM users WHERE church_id = ? AND role = "member"',
            [church_id]
        )
        if not members:
            flash('No members to assign duties.')
            return redirect(url_for('admin_generate_roster'))

        db = get_db()
        start_date = datetime.date(year, month, 1)
        if month == 12:
            end_date = datetime.date(year + 1, 1, 1)
        else:
            end_date = datetime.date(year, month + 1, 1)

        # Remove existing roster entries for that month (church_id scoped)
        db.execute(
            'DELETE FROM duty_roster WHERE church_id = ? AND duty_date >= ? AND duty_date < ?',
            (church_id, start_date.isoformat(), end_date.isoformat())
        )

        current_member_index = 0
        date_iter = start_date
        while date_iter < end_date:
            # Example: if we only schedule on Sundays
            if date_iter.weekday() == 6:  # Sunday
                activity = random.choice(activities)
                member = members[current_member_index % len(members)]
                current_member_index += 1
                db.execute(
                    'INSERT INTO duty_roster (church_id, duty_date, activity, user_id) VALUES (?, ?, ?, ?)',
                    (church_id, date_iter.isoformat(), activity, member['id'])
                )
                send_email(
                    member['email'],
                    "Duty Roster Assignment",
                    f"You are assigned to {activity} on {date_iter.isoformat()}."
                )
            date_iter += datetime.timedelta(days=1)

        db.commit()
        flash('Duty roster generated successfully.')
        return redirect(url_for('admin_dashboard'))

    return render_template('admin_generate_roster.html')


@app.route('/admin/substitutions', methods=['GET', 'POST'])
@admin_required
def admin_substitutions():
    church_id = session.get('church_id')
    db = get_db()

    if request.method == 'POST':
        req_id = request.form['request_id']
        action = request.form['action']

        # First fetch the substitution request in a church_id–safe manner
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
            return redirect(url_for('admin_substitutions'))

        if action == 'approve':
            db.execute('UPDATE substitution_requests SET status = ? WHERE id = ?', ('approved', req_id))
            db.execute('UPDATE duty_roster SET user_id = ? WHERE id = ?', (sub_req['requested_substitute_id'], sub_req['duty_id']))

            requester = query_db('SELECT * FROM users WHERE id = ?', [sub_req['requester_id']], one=True)
            substitute = query_db('SELECT * FROM users WHERE id = ?', [sub_req['requested_substitute_id']], one=True)

            if requester:
                send_email(requester['email'], "Substitution Approved", "Your substitution request has been approved.")
            if substitute:
                send_email(substitute['email'], "New Duty Assignment", "You have been assigned a new duty.")

            db.commit()

        elif action == 'deny':
            db.execute('UPDATE substitution_requests SET status = ? WHERE id = ?', ('denied', req_id))
            db.commit()

        flash('Substitution request updated.')
        return redirect(url_for('admin_substitutions'))

    # Only fetch sub requests for this admin’s church
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


@app.route('/admin/roster')
@admin_required
def admin_roster():
    """View entire duty roster for the current admin’s church only."""
    church_id = session.get('church_id')
    assignments = query_db(
        '''SELECT dr.*, u.name as member_name, u.email as member_email
           FROM duty_roster dr
           JOIN users u ON dr.user_id = u.id
           WHERE dr.church_id = ?
           ORDER BY dr.duty_date''',
        [church_id]
    )
    return render_template('admin_roster.html', assignments=assignments)


# -----------------------------------------------------------------------------
# DEMO: Generating dummy members with hashed passwords
# -----------------------------------------------------------------------------
@app.route('/admin/generate_dummy_members', methods=['GET', 'POST'])
@admin_required
def generate_dummy_members():
    church_id = session.get('church_id')
    db = get_db()
    if request.method == 'POST':
        # Clear existing member records for this church
        db.execute('DELETE FROM users WHERE church_id = ? AND role = "member"', (church_id,))

        first_names = ["John", "Michael", "David", "James", "Robert", "William", "Richard", "Charles", "Joseph", "Thomas"]
        last_names  = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Miller", "Davis", "Garcia", "Rodriguez", "Wilson"]

        count = int(request.form.get('count', 20)) or 20

        for _ in range(count):
            first = random.choice(first_names)
            last  = random.choice(last_names)
            name  = f"{first} {last}"
            email = f"{first.lower()}.{last.lower()}{random.randint(1,1000)}@example.com"

            # Instead of plaintext, store a hashed password
            hashed_pw = generate_password_hash("memberpass")

            db.execute(
                'INSERT INTO users (name, email, password, role, church_id) VALUES (?, ?, ?, ?, ?)',
                (name, email, hashed_pw, "member", church_id)
            )
        db.commit()
        flash(f"Inserted {count} dummy members.")
        return redirect(url_for('admin_dashboard'))

    return render_template('generate_dummy_members.html')


# -----------------------------------------------------------------------------
# AI-ASSISTED WORSHIP SERVICES
# -----------------------------------------------------------------------------
@app.route('/admin/parse_worship_setup', methods=['POST'])
@admin_required
@csrf.exempt
def parse_worship_setup():
    """
    Receives plain-English instructions, calls the Gemini API, returns structured JSON,
    then replaces worship_services for the admin’s church only.
    """
    data = request.get_json()
    instruction = data.get('instruction', '')
    church_id = session.get('church_id')

    # Optionally fetch existing data for context
    current_services = query_db('SELECT * FROM worship_services WHERE church_id = ?', [church_id])
    current_services_str = ""
    for svc in current_services:
        current_services_str += f"{svc['day']} at {svc['time']}: {svc['activities']}; "

    context_prompt = (
        f"Current worship services: {current_services_str}. "
        f"Based on the following instructions, update the worship services. "
        f"Instruction: {instruction} "
        f"Return a JSON object with exactly one key: 'worship_services', "
        f"whose value is an array of objects with keys 'day', 'time', and 'activities'."
    )

    try:
        response_text = generate_gemini_message(context_prompt, json_response_format=True)
        updated = json.loads(response_text)
    except Exception as e:
        print("Exception parsing Gemini response:", e)
        return jsonify({"error": "Invalid JSON returned from Gemini API"}), 500

    # Remove old services for this church
    db = get_db()
    db.execute('DELETE FROM worship_services WHERE church_id = ?', (church_id,))

    # Insert new services
    worship_services = updated.get("worship_services", [])
    for svc in worship_services:
        day = svc.get("day", "").strip()
        time_val = svc.get("time", "").strip()
        acts_list = svc.get("activities", [])
        if isinstance(acts_list, list):
            activities = ", ".join(a.strip() for a in acts_list if a.strip())
        else:
            activities = acts_list.strip()

        if day and time_val and activities:
            db.execute(
                'INSERT INTO worship_services (church_id, day, time, activities) VALUES (?, ?, ?, ?)',
                (church_id, day, time_val, activities)
            )
    db.commit()

    return jsonify(updated), 200


@app.route('/admin/update_service', methods=['POST'])
@admin_required
@csrf.exempt
def update_service():
    data = request.get_json()
    service_id = data.get("id")
    day = data.get("day", "").strip()
    time_val = data.get("time", "").strip()
    activities = data.get("activities", "").strip()
    church_id = session.get("church_id")

    db = get_db()
    # Only update the row if it matches the admin’s church
    db.execute(
        "UPDATE worship_services SET day = ?, time = ?, activities = ? WHERE id = ? AND church_id = ?",
        (day, time_val, activities, service_id, church_id)
    )
    db.commit()
    return jsonify({"success": True}), 200

@app.route('/admin/delete_service', methods=['POST'])
@admin_required
@csrf.exempt
def delete_service():
    data = request.get_json()
    service_id = data.get("id")
    church_id = session.get("church_id")

    db = get_db()
    db.execute("DELETE FROM worship_services WHERE id = ? AND church_id = ?", (service_id, church_id))
    db.commit()
    return jsonify({"success": True}), 200

@app.route('/admin/add_service', methods=['POST'])
@admin_required
@csrf.exempt
def add_service():
    data = request.get_json()
    day = data.get("day", "").strip()
    time_val = data.get("time", "").strip()
    activities = data.get("activities", "").strip()
    church_id = session.get("church_id")

    db = get_db()
    cur = db.execute(
        "INSERT INTO worship_services (church_id, day, time, activities) VALUES (?, ?, ?, ?)",
        (church_id, day, time_val, activities)
    )
    db.commit()
    new_id = cur.lastrowid
    return jsonify({"success": True, "id": new_id}), 200


# -----------------------------------------------------------------------------
# MEMBER ROUTES
# -----------------------------------------------------------------------------
@app.route('/member/dashboard')
@login_required
def member_dashboard():
    """Shows the logged-in member’s upcoming assignments, limited by their user_id + church_id."""
    user_id = session.get('user_id')
    church_id = session.get('church_id')
    today = datetime.date.today().isoformat()

    assignments = query_db(
        '''SELECT * FROM duty_roster
           WHERE user_id = ? AND church_id = ? AND duty_date >= ?
           ORDER BY duty_date''',
        [user_id, church_id, today]
    )
    return render_template('member_dashboard.html', assignments=assignments)

@app.route('/member/request_substitution/<int:duty_id>', methods=['GET', 'POST'])
@login_required
def member_request_substitution(duty_id):
    """A member can request substitution only for a duty that belongs to them (and matches their church)."""
    user_id = session.get('user_id')
    church_id = session.get('church_id')

    duty = query_db(
        'SELECT * FROM duty_roster WHERE id = ? AND user_id = ? AND church_id = ?',
        [duty_id, user_id, church_id],
        one=True
    )
    if not duty:
        flash('Invalid duty assignment or you do not have access.')
        return redirect(url_for('member_dashboard'))

    if request.method == 'POST':
        substitute_email = request.form['substitute_email']
        message = request.form['message']

        # Must find a substitute user in the same church
        substitute = query_db(
            'SELECT * FROM users WHERE email = ? AND church_id = ?',
            [substitute_email, church_id],
            one=True
        )
        if not substitute:
            flash('Substitute not found in your church.')
            return redirect(url_for('member_request_substitution', duty_id=duty_id))

        db = get_db()
        db.execute(
            '''INSERT INTO substitution_requests
               (duty_id, requester_id, requested_substitute_id, status, message)
               VALUES (?, ?, ?, ?, ?)''',
            (duty_id, user_id, substitute['id'], 'pending', message)
        )
        db.commit()
        flash('Substitution request submitted.')
        return redirect(url_for('member_dashboard'))

    return render_template('member_request_substitution.html', duty=duty)


# -----------------------------------------------------------------------------
# MAIN
# -----------------------------------------------------------------------------
if __name__ == '__main__':
    # Initialize DB if it doesn’t exist
    if not os.path.exists(DATABASE):
        init_db()
        db = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row

        # Create a sample church
        db.execute('INSERT INTO churches (name, scheduling_rules) VALUES (?, ?)',
                   ("Sample Church", "Round robin"))
        church_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]

        # Insert a default worship service
        db.execute('INSERT INTO worship_services (church_id, day, time, activities) VALUES (?, ?, ?, ?)',
                   (church_id, "Sunday", "10:00 AM", "Singing, Prayer, Preaching, Officiating"))

        # Admin user (hashed password).
        hashed_admin_pw = generate_password_hash("adminpass")
        db.execute(
            'INSERT INTO users (name, email, password, role, church_id) VALUES (?, ?, ?, ?, ?)',
            ("Admin User", "admin@example.com", hashed_admin_pw, "admin", church_id)
        )

        # Two sample members (hashed passwords).
        hashed_member_pw = generate_password_hash("memberpass")
        db.execute(
            'INSERT INTO users (name, email, password, role, church_id) VALUES (?, ?, ?, ?, ?)',
            ("Member One", "member1@example.com", hashed_member_pw, "member", church_id)
        )
        db.execute(
            'INSERT INTO users (name, email, password, role, church_id) VALUES (?, ?, ?, ?, ?)',
            ("Member Two", "member2@example.com", hashed_member_pw, "member", church_id)
        )

        db.commit()
        db.close()

    # Run in debug mode for development
    app.run(debug=True)
