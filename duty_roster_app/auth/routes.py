from functools import wraps
from flask import Blueprint, session, redirect, url_for, request, flash, render_template
from werkzeug.security import check_password_hash
from ..database.db import query_db

bp = Blueprint('auth', __name__)

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session or session.get('role') != 'admin':
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function

@bp.route('/login', methods=['GET', 'POST'])
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
            return redirect(url_for('auth.index'))

        flash('Invalid credentials')
    return render_template('login.html')

@bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth.login'))

@bp.route('/')
def index():
    if 'user_id' in session:
        if session.get('role') == 'admin':
            return redirect(url_for('admin.setup'))
        else:
            return redirect(url_for('member.dashboard'))
    return redirect(url_for('auth.login')) 