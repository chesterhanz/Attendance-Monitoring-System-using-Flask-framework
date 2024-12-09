from flask import Flask, render_template, request, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from flask import session
from flask_migrate import Migrate
import matplotlib.pyplot as plt
import io
import base64
from matplotlib.ticker import MaxNLocator
import matplotlib
from sqlalchemy import Column, Integer, String, Date, Enum, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
import enum

matplotlib.use('Agg')

app = Flask(__name__)

app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql+mysqlconnector://root:root@localhost/attendance_db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'your_secret_key_here'

db = SQLAlchemy(app)

class Session(enum.Enum):
    morning = "Morning"
    afternoon = "Afternoon"

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=False)
    role = db.Column(db.String(50), nullable=False)  # admin, student, instructor

    def set_password(self, password):
        self.password = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password, password)

class Attendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False)
    session = db.Column(db.String(50), nullable=False)  # Morning or Afternoon
    status = db.Column(db.String(20), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    user = db.relationship('User', backref='attendances')

    __table_args__ = (db.UniqueConstraint('user_id', 'date', 'session', name='_user_date_session_uc'),)  # Ensure unique session per day for each user


login_manager = LoginManager()
login_manager.init_app(app)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

login_manager.login_view = 'login'

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/attendance', methods=['GET', 'POST'])
@login_required
def attendance():
    if request.method == 'POST':
        status = request.form['status']
        session = request.form['session']
        today = datetime.now().date()


        existing_record = Attendance.query.filter_by(user_id=current_user.id, date=today, session=session).first()

        if existing_record:
            return "You have already submitted attendance for this session today.", 400

        new_attendance = Attendance(date=today, session=session, status=status, user_id=current_user.id)
        db.session.add(new_attendance)
        db.session.commit()

    attendances = Attendance.query.filter_by(user_id=current_user.id).order_by(Attendance.date.desc()).all()
    return render_template('attendance.html', attendances=attendances)

@app.route('/reports')
@login_required
def report():
    if current_user.username == 'admin':
        attendances = Attendance.query.all()
    else:
        attendances = Attendance.query.filter_by(user_id=current_user.id).all()
    return render_template('reports.html', attendances=attendances)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for('dashboard') if user.username == 'admin' else url_for('attendance'))
        return "Invalid username or password", 401
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.before_request
def ensure_admin_exists():
    # Check if the admin exists before handling any request
    admin = User.query.filter_by(username='admin').first()
    if not admin:
        hashed_password = generate_password_hash('admin1234')
        admin_user = User(username='admin', password=hashed_password, role='admin')
        db.session.add(admin_user)
        db.session.commit()
        print("Admin user created with username 'admin' and password 'admin1234'")

@app.route('/delete_attendance/<int:record_id>', methods=['POST'])
@login_required
def delete_attendance(record_id):
    record = Attendance.query.get_or_404(record_id)
    
    if record.user_id == current_user.id or current_user.role == 'admin':
        db.session.delete(record)
        db.session.commit()
        return redirect(url_for('report'))
    else:
        return "You are not authorized to delete this record.", 403

@app.route('/edit_attendance/<int:record_id>', methods=['GET', 'POST'])
@login_required
def edit_attendance(record_id):
    record = Attendance.query.get_or_404(record_id)
    
    if record.user_id != current_user.id and current_user.role != 'admin':
        return "You are not authorized to edit this record.", 403

    if request.method == 'POST':
        new_status = request.form['status']
        record.status = new_status
        db.session.commit()
        return redirect(url_for('report'))

    return render_template('edit_attendance.html', record=record)

@app.route('/dashboard')
@login_required
def dashboard():
    if current_user.username != 'admin':
        return "Access denied. Only the admin can access this page.", 403

    # Fetch all users with 'student' or 'instructor' roles
    users = User.query.filter(User.role.in_(['student', 'instructor'])).all()

    # Fetch the attendance records for these users
    attendance_data = {}
    for user in users:
        # Fetch the attendance records for each user
        attendance_data[user.username] = Attendance.query.filter_by(user_id=user.id).all()

    return render_template('dashboard.html', users=users, attendance_data=attendance_data)


@app.route('/analytics')
@login_required
def analytics():
    if current_user.role != 'admin':
        return "Access denied. You are not an admin"

    attendances = Attendance.query.all()

    statuses = [attendance.status for attendance in attendances]
    present_count = statuses.count('Present')
    absent_count = statuses.count('Absent')
    
    # Pie chart data
    labels = ['Present', 'Absent']
    sizes = [present_count, absent_count]
    colors = ['#4CAF50', '#FF6347']
    explode = (0.1, 0) 

    fig, ax = plt.subplots()
    ax.pie(sizes, explode=explode, labels=labels, colors=colors, autopct='%1.1f%%', shadow=True, startangle=140)
    ax.axis('equal')

    img = io.BytesIO()
    plt.savefig(img, format='png')
    img.seek(0)
    img_b64 = base64.b64encode(img.getvalue()).decode('utf-8')

    return render_template('analytics.html', plot_url=img_b64)

@app.route('/register', methods=['GET', 'POST'])
@login_required
def register():
    if current_user.username != 'admin':
        return "Access denied. Only the admin can register new users.", 403

    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        role = request.form['role']

        if role not in ['student', 'instructor']:
            return "Invalid role. Only 'student' and 'instructor' roles are allowed.", 400

        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            return "Username already exists. Please choose another.", 400

        new_user = User(username=username, role=role)
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()
        return redirect(url_for('dashboard'))

    return render_template('register.html')

if __name__ == '__main__':
    app.run(debug=True, port=8080)
