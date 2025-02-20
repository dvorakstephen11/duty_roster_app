import os
from flask import Flask
from flask_wtf.csrf import CSRFProtect
from dotenv import load_dotenv

# Use your database package initialization
from duty_roster_app.database import db

# Import blueprints
from duty_roster_app.auth.routes import bp as auth_bp
from duty_roster_app.admin.routes import bp as admin_bp
from duty_roster_app.member.routes import bp as member_bp

def create_app():
    load_dotenv()  # Loads environment variables from .env

    app = Flask(__name__)
    # Use secret key from .env or fall back
    app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'fallback_secret_key')

    # Enable CSRF protection
    # csrf = CSRFProtect(app)

    # Initialize DB from your database/db.py
    db.init_app(app)

    # Register the blueprints
    # auth_bp might or might not use a prefix (depends on your preference).
    # Here we assume no prefix for auth, /auth, or the approach used in your code.
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(member_bp, url_prefix='/member')

    return app

def init_sample_data(app):
    """
    If you want to conditionally initialize the DB with sample data,
    you can replicate that logic here, calling db.init_db() etc.
    """
    import os
    if not os.path.exists(db.DATABASE):
        with app.app_context():
            db.init_db()
            database = db.get_db()

            # Create a sample church
            database.execute(
                'INSERT INTO churches (name, scheduling_rules) VALUES (?, ?)',
                ("Sample Church", "Round robin")
            )
            church_id = database.execute('SELECT last_insert_rowid()').fetchone()[0]

            # Insert a default worship service
            database.execute(
                'INSERT INTO worship_services (church_id, day, time, activities) VALUES (?, ?, ?, ?)',
                (church_id, "Sunday", "10:00 AM", "Singing, Prayer, Preaching, Officiating")
            )

            # Admin user
            from werkzeug.security import generate_password_hash
            hashed_admin_pw = generate_password_hash("adminpass")
            database.execute(
                'INSERT INTO users (name, email, password, role, church_id) VALUES (?, ?, ?, ?, ?)',
                ("Admin User", "admin@example.com", hashed_admin_pw, "admin", church_id)
            )

            # Generate 40 sample members with realistic male names
            import random
            first_names = ["James", "John", "Robert", "Michael", "William", "David", "Richard", "Joseph", "Thomas", "Charles",
                         "Christopher", "Daniel", "Matthew", "Anthony", "Donald", "Mark", "Paul", "Steven", "Andrew", "Kenneth",
                         "Joshua", "Kevin", "Brian", "George", "Timothy", "Ronald", "Edward", "Jason", "Jeffrey", "Ryan",
                         "Jacob", "Gary", "Nicholas", "Eric", "Jonathan", "Stephen", "Larry", "Justin", "Scott", "Brandon"]
            last_names = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez", "Martinez",
                         "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin",
                         "Lee", "Perez", "Thompson", "White", "Harris", "Sanchez", "Clark", "Ramirez", "Lewis", "Robinson",
                         "Walker", "Young", "Allen", "King", "Wright", "Scott", "Torres", "Nguyen", "Hill", "Flores"]

            hashed_member_pw = generate_password_hash("memberpass")
            for i in range(40):
                first_name = first_names[i]
                last_name = random.choice(last_names)
                name = f"{first_name} {last_name}"
                email = f"{first_name.lower()}.{last_name.lower()}@example.com"
                database.execute(
                    'INSERT INTO users (name, email, password, role, church_id) VALUES (?, ?, ?, ?, ?)',
                    (name, email, hashed_member_pw, "member", church_id)
                )

            database.commit()

if __name__ == '__main__':
    app = create_app()
    # init_sample_data(app)  # Uncomment if you want auto-initialization
    app.run(debug=True)
