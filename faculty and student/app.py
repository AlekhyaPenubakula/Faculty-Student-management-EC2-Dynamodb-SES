from flask import Flask, render_template, request, redirect, url_for, session
import boto3
import uuid
from datetime import datetime

# === AWS Setup ===
dynamodb = boto3.resource('dynamodb', region_name='ap-south-1')
users_table = dynamodb.Table('Faculty-Student-Users')
courses_table = dynamodb.Table('Courses')
activities_table = dynamodb.Table('Activities')
sns = boto3.client('sns', region_name='ap-south-1')

app = Flask(__name__)
app.secret_key = 'cloudclass_secret'


# === Home ===
@app.route('/')
def index():
    return render_template('index.html')


# === Register ===
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        password = request.form['password']
        confirm_password = request.form['confirm_password']
        user_type = request.form['user_type']

        # Check if already exists
        response = users_table.get_item(Key={'email': email})
        if 'Item' in response:
            return "User already exists"
        if password != confirm_password:
            return "Passwords do not match"

        users_table.put_item(Item={
            'email': email,
            'name': name,
            'password': password,
            'role': user_type
        })
        return redirect(url_for('login'))
    return render_template('register.html')


# === Login ===
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        role = request.form['user_type']

        response = users_table.get_item(Key={'email': email})
        user = response.get('Item')

        if user and user['password'] == password and user['role'] == role:
            session['user'] = user
            return redirect(url_for('student_dashboard' if role == 'student' else 'faculty_dashboard'))

        return "Invalid credentials or role mismatch"
    return render_template('login.html')


# === Logout ===
@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('index'))


# === Student Dashboard ===
@app.route('/student/dashboard')
def student_dashboard():
    user = session.get('user')
    if not user or user['role'] != 'student':
        return redirect(url_for('login'))

    email = user['email']
    
    activities = activities_table.query(
        KeyConditionExpression=boto3.dynamodb.conditions.Key('user_email').eq(email)
    )['Items']

    courses = [item['course_name'] for item in activities if item['activity_type_id'].startswith('enroll#')]
    quizzes = [item for item in activities if item['activity_type_id'].startswith('quiz#')]
    grades = [item for item in activities if item['activity_type_id'].startswith('grade#')]
    notes = [item for item in activities if item['activity_type_id'].startswith('note#')]

    available_courses = [c['course_name'] for c in courses_table.scan().get('Items', [])]

    return render_template('student_dashboard.html', user=user,
                           courses=courses, quizzes=quizzes, evaluations=grades,
                           notifications=notes, available_courses=available_courses)


# === Faculty Dashboard ===
@app.route('/faculty/dashboard')
def faculty_dashboard():
    if 'user' in session and session['user']['role'] == 'faculty':
        return render_template('faculty_dashboard.html', user=session['user'])
    return redirect(url_for('login'))


# === Upload Course Content ===
@app.route('/upload_content', methods=['GET', 'POST'])
def upload_content():
    user = session.get('user')
    if not user or user['role'] != 'faculty':
        return redirect(url_for('login'))

    if request.method == 'POST':
        course = request.form['course'].strip()
        material = request.form['material'].strip()

        existing = courses_table.get_item(Key={'course_name': course}).get('Item')
        if existing:
            existing['material_links'].append(material)
            courses_table.put_item(Item=existing)
        else:
            courses_table.put_item(Item={
                'course_name': course,
                'created_by': user['email'],
                'material_links': [material]
            })

        return redirect(url_for('faculty_dashboard'))
    return render_template('upload_content.html')


# === Enroll in Course ===
@app.route('/payment/<course_name>', methods=['GET', 'POST'])
def payment(course_name):
    user = session.get('user')
    if not user or user['role'] != 'student':
        return redirect(url_for('login'))

    if request.method == 'POST':
        activities_table.put_item(Item={
            'user_email': user['email'],
            'activity_type_id': f'enroll#{course_name}',
            'course_name': course_name,
            'timestamp': str(datetime.utcnow())
        })
        activities_table.put_item(Item={
            'user_email': user['email'],
            'activity_type_id': f'note#{uuid.uuid4()}',
            'message': f"Enrolled in {course_name}",
            'timestamp': str(datetime.utcnow())
        })
        return render_template('payment.html', course_name=course_name, success=True)
    return render_template('payment.html', course_name=course_name)


# === Submit Project ===
@app.route('/submit_project/<course_name>', methods=['GET', 'POST'])
def submit_project(course_name):
    user = session.get('user')
    if not user or user['role'] != 'student':
        return redirect(url_for('login'))

    if request.method == 'POST':
        filename = request.form['filename']
        activities_table.put_item(Item={
            'user_email': user['email'],
            'activity_type_id': f'project#{course_name}',
            'course_name': course_name,
            'filename': filename,
            'timestamp': str(datetime.utcnow())
        })
        activities_table.put_item(Item={
            'user_email': user['email'],
            'activity_type_id': f'note#{uuid.uuid4()}',
            'message': f"Project submitted for {course_name}",
            'timestamp': str(datetime.utcnow())
        })
        return redirect(url_for('student_dashboard'))
    return render_template('project_submit.html', course_name=course_name)


# === Quiz Attempt ===
@app.route('/quiz/<course_name>', methods=['GET', 'POST'])
def quiz(course_name):
    user = session.get('user')
    if not user or user['role'] != 'student':
        return redirect(url_for('login'))

    if request.method == 'POST':
        score = int(request.form.get('score', 0))
        activities_table.put_item(Item={
            'user_email': user['email'],
            'activity_type_id': f'quiz#{course_name}',
            'course_name': course_name,
            'score': score,
            'total': 10,
            'timestamp': str(datetime.utcnow())
        })
        activities_table.put_item(Item={
            'user_email': user['email'],
            'activity_type_id': f'note#{uuid.uuid4()}',
            'message': f"Quiz submitted for {course_name} with score {score}/10",
            'timestamp': str(datetime.utcnow())
        })
        return redirect(url_for('student_dashboard'))
    return render_template('quiz.html', course_name=course_name)


# === Show Notifications ===
@app.route('/notifications')
def show_notifications():
    if 'user' not in session:
        return redirect(url_for('login'))

    email = session['user']['email']
    items = activities_table.query(
        KeyConditionExpression=boto3.dynamodb.conditions.Key('user_email').eq(email)
    )['Items']
    notes = [i for i in items if i['activity_type_id'].startswith('note#')]

    return render_template('notifications.html', notifications=notes, user=session['user'])


# === Evaluate Projects (Faculty) ===
@app.route('/evaluate', methods=['GET', 'POST'])
def evaluate():
    if 'user' not in session or session['user']['role'] != 'faculty':
        return redirect(url_for('login'))

    if request.method == 'POST':
        student = request.form['student']
        course = request.form['course']
        grade = request.form['grade']

        activities_table.put_item(Item={
            'user_email': student,
            'activity_type_id': f'grade#{course}',
            'course_name': course,
            'grade': grade,
            'timestamp': str(datetime.utcnow())
        })
        activities_table.put_item(Item={
            'user_email': student,
            'activity_type_id': f'note#{uuid.uuid4()}',
            'message': f"Grade received for {course}: {grade}",
            'timestamp': str(datetime.utcnow())
        })

        return redirect(url_for('faculty_dashboard'))

    return render_template('evaluate.html', submissions=[])  # can pull from 'project#' activities


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=80)

