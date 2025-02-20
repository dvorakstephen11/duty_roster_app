from flask import Blueprint, session, redirect, url_for, request, flash, render_template
import datetime
from ..database.db import get_db, query_db
from ..auth.routes import login_required

bp = Blueprint('member', __name__)

@bp.route('/dashboard')
@login_required
def dashboard():
    """Shows the logged-in member's upcoming assignments, limited by their user_id + church_id."""
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

@bp.route('/request_substitution/<int:duty_id>', methods=['GET', 'POST'])
@login_required
def request_substitution(duty_id):
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
        return redirect(url_for('member.dashboard'))

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
            return redirect(url_for('member.request_substitution', duty_id=duty_id))

        db = get_db()
        db.execute(
            '''INSERT INTO substitution_requests
               (duty_id, requester_id, requested_substitute_id, status, message)
               VALUES (?, ?, ?, ?, ?)''',
            (duty_id, user_id, substitute['id'], 'pending', message)
        )
        db.commit()
        flash('Substitution request submitted.')
        return redirect(url_for('member.dashboard'))

    return render_template('member_request_substitution.html', duty=duty) 