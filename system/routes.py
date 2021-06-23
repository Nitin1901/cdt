import os
import csv
import secrets
from datetime import datetime, timedelta
from PIL import Image
from flask import render_template, url_for, flash, redirect, request, abort, send_file, Response
from werkzeug.utils import secure_filename
from flask_mail import Message
from system import app, db, bcrypt, mail
from system.camera import VideoCamera
from system.forms import RegistrationForm, LoginForm, UpdateAccountForm, CreateExamForm, JoinExamForm, SubmitExamForm, RequestResetForm, ResetPasswordForm
from system.models import User, Exam, UserExam
from flask_login import login_user, current_user, logout_user, login_required


ALLOWED_EXTENSIONS = {'csv'}


@app.route("/")
@app.route("/home")
@login_required
def home():
    exams = Exam.query.filter(Exam.start_time>datetime.now()).order_by(Exam.start_time)
    return render_template('home.html', exams=exams)


@app.route("/about")
def about():
    return render_template('about.html', title='About')


@app.route("/register", methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('home'))
    form = RegistrationForm()
    if form.validate_on_submit():
        hashed_password = bcrypt.generate_password_hash(form.password.data).decode('utf-8')
        user = User(username=form.username.data, email=form.email.data, password=hashed_password)
        db.session.add(user)
        db.session.commit()
        flash('Your account has been created! You are now able to log in', 'success')
        return redirect(url_for('login'))
    return render_template('register.html', title='Register', form=form)


@app.route("/login", methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('home'))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user and bcrypt.check_password_hash(user.password, form.password.data):
            login_user(user, remember=form.remember.data)
            next_page = request.args.get('next')
            return redirect(next_page) if next_page else redirect(url_for('home'))
        else:
            flash('Login Unsuccessful. Please check username and password', 'danger')
    return render_template('login.html', title='Login', form=form)


@app.route("/logout")
def logout():
    logout_user()
    return redirect(url_for('home'))


def save_picture(form_picture):
    random_hex = secrets.token_hex(8)
    _, f_ext = os.path.splitext(form_picture.filename)
    picture_fn = random_hex + f_ext
    picture_path = os.path.join(app.root_path, 'static/profile_pics', picture_fn)

    output_size = (125, 125)
    i = Image.open(form_picture)
    i.thumbnail(output_size)
    i.save(picture_path)

    return picture_fn


@app.route("/account", methods=['GET', 'POST'])
@login_required
def account():
    form = UpdateAccountForm()
    if form.validate_on_submit():
        if form.picture.data:
            picture_file = save_picture(form.picture.data)
            current_user.image_file = picture_file
        current_user.email = form.email.data
        db.session.commit()
        flash('Your account has been updated!', 'success')
        return redirect(url_for('account'))
    elif request.method == 'GET':
        form.email.data = current_user.email
    image_file = url_for('static', filename='profile_pics/' + current_user.image_file)
    return render_template('account.html', title='Account',
                           image_file=image_file, form=form)


def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@app.route("/create_exam", methods=['GET', 'POST'])
@login_required
def create_exam():
    if current_user.user_access:
        form = CreateExamForm()
        if form.validate_on_submit():
            file = request.files['questions']
            filename = secure_filename(file.filename)
            random_hex = secrets.token_hex(8)
            _, f_ext = os.path.splitext(filename)
            filename = random_hex + f_ext
            if form.start.data < datetime.now():
                flash('Cannot create exam in the past', 'danger')
            else:
                if allowed_file(filename):
                    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                    exam = Exam(
                        topic=form.topic.data,
                        start_time=form.start.data,
                        marks=form.marks.data,
                        negative=form.negative.data,
                        duration=form.duration.data,
                        exam_code=form.exam_code.data,
                        questions=filename,
                        user_id=current_user.id
                    )
                    db.session.add(exam)
                    db.session.commit()
                    flash('Exam created successfully', 'success')
                    return redirect(url_for('home'))
                else:
                    flash('Invalid file', 'danger')
        return render_template('create_exam.html', title='Create Exam', form=form)
    else:
        return abort(403)


@app.route("/previous_exam")
@login_required
def previous_exam():
    if current_user.user_access:
        exams = Exam.query.order_by(Exam.start_time)
        return render_template('previous_exam.html', exams=exams)
    else:
        return abort(403)


@app.route("/join_exam/<int:exam_id>", methods=['GET', 'POST'])
@login_required
def join_exam(exam_id):
    if not current_user.user_access:
        form = JoinExamForm()
        if form.validate_on_submit():
            exam = Exam.query.filter_by(id=exam_id).first()
            row = UserExam.query.filter_by(user_id=current_user.id, exam_id=exam_id).first()
            if not row:
                if exam.exam_code == form.exam_code.data:
                    # if exam.start_time > datetime.now():
                    #     flash('Exam did not start yet', 'danger')
                    # elif exam.start_time + timedelta(minutes=exam.duration) < datetime.now():
                    #     flash('Exam completed', 'danger')
                    # else:
                    return redirect(url_for('attempt_exam', exam_id=exam.id))
                else:
                    flash('Exam code incorrect', 'danger')
            else:
                flash('Exam already attempted', 'danger')
                return redirect(url_for('home'))
        return render_template('join_exam.html', title='Join Exam', form=form)
    else:
        abort(403)


@app.route("/attempt_exam/<int:exam_id>", methods=['GET', 'POST'])
@login_required
def attempt_exam(exam_id):
    exam = Exam.query.filter_by(id=exam_id).first()
    form = SubmitExamForm()
    test = get_questions(exam.questions)
    responses = []
    if request.method == 'POST':
        row = UserExam.query.filter_by(user_id=current_user.id, exam_id=exam_id).first()
        if row.attempted:
            flash('Exam already attempted', 'danger')
            return redirect(url_for('home'))
        for question in test:
            responses.append(request.form.get(str(question[6])))
        score = get_result(responses, test, exam.marks, exam.negative)
        row = UserExam(user_id=current_user.id, exam_id=exam_id, attempted=True, marks=score)
        db.session.add(row)
        db.session.commit()
        flash(f'Exam submitted! Your score is {score}', 'success')
        return redirect(url_for('home'))
    else:
        return render_template('exam.html', title=f'{exam.topic} Exam', test=test, form=form)


def get_questions(filename):
    filename = os.path.join(app.root_path, 'static/questions', filename)
    with open(filename, newline='') as f:
        reader = csv.reader(f)
        data = list(reader)
    for idx, row in enumerate(data):
        data[idx].append(idx)
    return data[1:]


def get_result(responses, test, marks, negative):
    count = 0
    per_question = marks/len(responses)
    for i in range(len(responses)):
        if responses[i]:
            if responses[i] == test[i][-2]:
                count += per_question
            else:
                count -= negative*per_question/100
    return count


@app.route("/result")
@login_required
def result():
    if not current_user.user_access:
        exams = UserExam.query\
                .join(Exam, Exam.id == UserExam.exam_id)\
                .add_columns(UserExam.exam_id, Exam.topic, UserExam.marks, Exam.start_time, Exam.duration)\
                .filter(UserExam.user_id == current_user.id)\
                .all()
        return render_template('result.html', exams=exams)
    else:
        return abort(403)


def gen(camera):
    while True:
        frame = camera.get_frame()
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n\r\n')

@app.route('/video_feed')
def video_feed():
    return Response(gen(VideoCamera()),
                    mimetype='multipart/x-mixed-replace; boundary=frame')


def send_reset_email(user):
    token = user.get_reset_token()
    msg = Message('Password Reset Request',
                  sender='noreply@demo.com',
                  recipients=[user.email])
    msg.body = f'''To reset your password, visit the following link:
{url_for('reset_token', token=token, _external=True)}
If you did not make this request then simply ignore this email and no changes will be made.
'''
    mail.send(msg)


@app.route("/reset_password", methods=['GET', 'POST'])
def reset_request():
    if current_user.is_authenticated:
        return redirect(url_for('home'))
    form = RequestResetForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        send_reset_email(user)
        flash('An email has been sent with instructions to reset your password.', 'info')
        return redirect(url_for('login'))
    return render_template('reset_request.html', title='Reset Password', form=form)


@app.route("/reset_password/<token>", methods=['GET', 'POST'])
def reset_token(token):
    if current_user.is_authenticated:
        return redirect(url_for('home'))
    user = User.verify_reset_token(token)
    if user is None:
        flash('That is an invalid or expired token', 'warning')
        return redirect(url_for('reset_request'))
    form = ResetPasswordForm()
    if form.validate_on_submit():
        hashed_password = bcrypt.generate_password_hash(form.password.data).decode('utf-8')
        user.password = hashed_password
        db.session.commit()
        flash('Your password has been updated! You are now able to log in', 'success')
        return redirect(url_for('login'))
    return render_template('reset_token.html', title='Reset Password', form=form)


@app.route("/download")
def download():
    return send_file('static/questions/sample.csv', mimetype='text/csv', attachment_filename='sample.csv', as_attachment=True)

