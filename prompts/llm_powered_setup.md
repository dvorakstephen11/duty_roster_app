I had to change the model from 2.0 to 1.5. Here's my current code:

```
import os, json, sqlite3, datetime, random
from flask import Flask, g, render_template, request, redirect, url_for, session, flash
import google.generativeai as genai


app = Flask(__name__)
app.secret_key = 'your_secret_key_here'
DATABASE = 'duty_roster.db'

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db

def query_db(query, args=(), one=False):
    cur = get_db().execute(query, args)
    rv = cur.fetchall()
    cur.close()
    return (rv[0] if rv else None) if one else rv


def generate_gemini_message(prompt: str, json_response_format: bool = False) -> str:
    api_key = "AIzaSyCggDz0oUw2pxynl2tFE5wCy9pr3PXMEMs"
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name="gemini-1.5-flash")
    # Prepend a system prompt that forces the model to output only valid JSON.
    system_prompt = "You are an assistant that outputs only valid JSON with no extra text or commentary."
    combined_prompt = f"{system_prompt}\n{prompt}"
    if json_response_format:
        response = model.generate_content(combined_prompt,
                                          generation_config={'response_mime_type': 'application/json'})
    else:
        response = model.generate_content(combined_prompt)
    # Log the raw response text so we can inspect it.
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
    print(f"Sending email to {to} | Subject: {subject}\n{body}\n")

from functools import wraps
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
            return redirect(url_for('admin_dashboard'))
        else:
            return redirect(url_for('member_dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        user = query_db('SELECT * FROM users WHERE email = ? AND password = ?', [email, password], one=True)
        if user:
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

@app.route('/admin/dashboard')
@admin_required
def admin_dashboard():
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
        worship_times = request.form['worship_times']
        worship_activities = request.form['worship_activities']
        scheduling_rules = request.form['scheduling_rules']
        if church_id:
            db.execute('UPDATE churches SET name = ?, worship_times = ?, worship_activities = ?, scheduling_rules = ? WHERE id = ?', 
                (name, worship_times, worship_activities, scheduling_rules, church_id))
        else:
            cur = db.execute('INSERT INTO churches (name, worship_times, worship_activities, scheduling_rules) VALUES (?, ?, ?, ?)',
                (name, worship_times, worship_activities, scheduling_rules))
            church_id = cur.lastrowid
            db.execute('UPDATE users SET church_id = ? WHERE id = ?', (church_id, session.get('user_id')))
            session['church_id'] = church_id
        db.commit()
        flash('Church setup updated')
        return redirect(url_for('admin_dashboard'))
    church = None
    if church_id:
        church = query_db('SELECT * FROM churches WHERE id = ?', [church_id], one=True)
    return render_template('admin_setup.html', church=church)

@app.route('/admin/generate_roster', methods=['GET', 'POST'])
@admin_required
def admin_generate_roster():
    if request.method == 'POST':
        month = int(request.form['month'])
        year = int(request.form['year'])
        church_id = session.get('church_id')
        church = query_db('SELECT * FROM churches WHERE id = ?', [church_id], one=True)
        activities = []
        if church and church['worship_activities']:
            activities = [act.strip() for act in church['worship_activities'].split(',')]
        else:
            activities = ['Singing', 'Prayer', 'Preaching', 'Officiating']
        members = query_db('SELECT * FROM users WHERE church_id = ? AND role = "member"', [church_id])
        if not members:
            flash('No members to assign duties.')
            return redirect(url_for('admin_generate_roster'))
        db = get_db()
        start_date = datetime.date(year, month, 1)
        end_date = datetime.date(year, month % 12 + 1, 1) if month != 12 else datetime.date(year+1, 1, 1)
        db.execute('DELETE FROM duty_roster WHERE church_id = ? AND duty_date >= ? AND duty_date < ?', (church_id, start_date.isoformat(), end_date.isoformat()))
        current_member_index = 0
        date_iter = start_date
        while date_iter < end_date:
            if date_iter.weekday() == 6:  # Sunday
                activity = random.choice(activities)
                member = members[current_member_index % len(members)]
                current_member_index += 1
                db.execute('INSERT INTO duty_roster (church_id, duty_date, activity, user_id) VALUES (?, ?, ?, ?)', 
                    (church_id, date_iter.isoformat(), activity, member['id']))
                send_email(member['email'], "Duty Roster Assignment", f"You are assigned to {activity} on {date_iter.isoformat()}.")
            date_iter += datetime.timedelta(days=1)
        db.commit()
        flash('Duty roster generated successfully.')
        return redirect(url_for('admin_dashboard'))
    return render_template('admin_generate_roster.html')

@app.route('/admin/substitutions', methods=['GET', 'POST'])
@admin_required
def admin_substitutions():
    if request.method == 'POST':
        req_id = request.form['request_id']
        action = request.form['action']
        db = get_db()
        if action == 'approve':
            sub_req = query_db('SELECT * FROM substitution_requests WHERE id = ?', [req_id], one=True)
            if sub_req:
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
    church_id = session.get('church_id')
    requests_list = query_db(
      '''SELECT sr.*, dr.duty_date, dr.activity, u1.name as requester_name, u2.name as substitute_name 
         FROM substitution_requests sr 
         JOIN duty_roster dr ON sr.duty_id = dr.id 
         JOIN users u1 ON sr.requester_id = u1.id 
         JOIN users u2 ON sr.requested_substitute_id = u2.id 
         WHERE dr.church_id = ?''', [church_id])
    return render_template('admin_substitutions.html', requests=requests_list)

@app.route('/member/dashboard')
@login_required
def member_dashboard():
    user_id = session.get('user_id')
    today = datetime.date.today().isoformat()
    assignments = query_db('SELECT * FROM duty_roster WHERE user_id = ? AND duty_date >= ? ORDER BY duty_date', [user_id, today])
    return render_template('member_dashboard.html', assignments=assignments)

@app.route('/member/request_substitution/<int:duty_id>', methods=['GET', 'POST'])
@login_required
def member_request_substitution(duty_id):
    user_id = session.get('user_id')
    duty = query_db('SELECT * FROM duty_roster WHERE id = ? AND user_id = ?', [duty_id, user_id], one=True)
    if not duty:
        flash('Invalid duty assignment.')
        return redirect(url_for('member_dashboard'))
    if request.method == 'POST':
        substitute_email = request.form['substitute_email']
        message = request.form['message']
        substitute = query_db('SELECT * FROM users WHERE email = ? AND church_id = ?', [substitute_email, session.get('church_id')], one=True)
        if not substitute:
            flash('Substitute not found.')
            return redirect(url_for('member_request_substitution', duty_id=duty_id))
        db = get_db()
        db.execute('INSERT INTO substitution_requests (duty_id, requester_id, requested_substitute_id, status, message) VALUES (?, ?, ?, ?, ?)', 
            (duty_id, user_id, substitute['id'], 'pending', message))
        db.commit()
        flash('Substitution request submitted.')
        return redirect(url_for('member_dashboard'))
    return render_template('member_request_substitution.html', duty=duty)


@app.route('/admin/roster')
@admin_required
def admin_roster():
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
            # Create a random email address; in a real app you’d ensure uniqueness
            email = f"{first.lower()}.{last.lower()}{random.randint(1,1000)}@example.com"
            password = "memberpass"
            db.execute('INSERT INTO users (name, email, password, role, church_id) VALUES (?, ?, ?, ?, ?)', 
                       (name, email, password, "member", church_id))
        db.commit()
        flash(f"Inserted {count} dummy members.")
        return redirect(url_for('admin_dashboard'))
    return render_template('generate_dummy_members.html')


@app.route('/admin/parse_worship_setup', methods=['POST'])
@admin_required
def parse_worship_setup():
    data = request.get_json()
    instruction = data.get('instruction', '')
    church_id = session.get('church_id')
    church = query_db('SELECT * FROM churches WHERE id = ?', [church_id], one=True)
    current_worship_times = church['worship_times'] if church else ""
    current_worship_activities = church['worship_activities'] if church else ""
    
    # Build a prompt with clear instructions.
    context_prompt = (
        f"Current worship times: {current_worship_times}. "
        f"Current worship activities: {current_worship_activities}. "
        f"Based on the following instructions, update the worship times and activities. "
        f"Instruction: {instruction} "
        f"Return a JSON object with exactly two keys: 'worship_times' and 'worship_activities' and nothing else."
    )
    
    try:
        response_text = generate_gemini_message(context_prompt, json_response_format=True)
        updated = json.loads(response_text)
    except Exception as e:
        print("Exception parsing Gemini response:", e)
        return json.dumps({"error": "Invalid JSON returned from Gemini API"}), 500, {'Content-Type': 'application/json'}

    db = get_db()
    db.execute('UPDATE churches SET worship_times = ?, worship_activities = ? WHERE id = ?',
               (updated["worship_times"], updated["worship_activities"], church_id))
    db.commit()
    return json.dumps(updated), 200, {'Content-Type': 'application/json'}





if __name__ == '__main__':
    if not os.path.exists(DATABASE):
        init_db()
        db = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
        db.execute('INSERT INTO churches (name, worship_times, worship_activities, scheduling_rules) VALUES (?, ?, ?, ?)',
                   ("Sample Church", "Sundays 10:00 AM", "Singing, Prayer, Preaching, Officiating", "Round robin"))
        church_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]
        db.execute('INSERT INTO users (name, email, password, role, church_id) VALUES (?, ?, ?, ?, ?)',
                   ("Admin User", "admin@example.com", "adminpass", "admin", church_id))
        db.execute('INSERT INTO users (name, email, password, role, church_id) VALUES (?, ?, ?, ?, ?)',
                   ("Member One", "member1@example.com", "memberpass", "member", church_id))
        db.execute('INSERT INTO users (name, email, password, role, church_id) VALUES (?, ?, ?, ?, ?)',
                   ("Member Two", "member2@example.com", "memberpass", "member", church_id))
        db.commit()
        db.close()
    app.run(debug=True)
    ```

    

And here's the error I'm currently getting:
```
Traceback (most recent call last):
  File "C:\Users\dvora\AppData\Local\Programs\Python\Python311\Lib\site-packages\flask\app.py", line 1478, in __call__
    return self.wsgi_app(environ, start_response)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\dvora\AppData\Local\Programs\Python\Python311\Lib\site-packages\flask\app.py", line 1458, in wsgi_app
    response = self.handle_exception(e)
               ^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\dvora\AppData\Local\Programs\Python\Python311\Lib\site-packages\flask\app.py", line 1455, in wsgi_app
    response = self.full_dispatch_request()
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\dvora\AppData\Local\Programs\Python\Python311\Lib\site-packages\flask\app.py", line 869, in full_dispatch_request
    rv = self.handle_user_exception(e)
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\dvora\AppData\Local\Programs\Python\Python311\Lib\site-packages\flask\app.py", line 867, in full_dispatch_request
    rv = self.dispatch_request()
         ^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\dvora\AppData\Local\Programs\Python\Python311\Lib\site-packages\flask\app.py", line 852, in dispatch_request
    return self.ensure_sync(self.view_functions[rule.endpoint])(**view_args)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\dvora\repo\duty_roster_app\duty_roster_app\app.py", line 64, in decorated_function
    return f(*args, **kwargs)
           ^^^^^^^^^^^^^^^^^^
  File "C:\Users\dvora\repo\duty_roster_app\duty_roster_app\app.py", line 309, in parse_worship_setup
    db.execute('UPDATE churches SET worship_times = ?, worship_activities = ? WHERE id = ?',
sqlite3.ProgrammingError: Error binding parameter 1: type 'list' is not supported
```