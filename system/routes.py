import os, secrets, threading, multiprocessing
from datetime import datetime, timedelta
from flask import (render_template, 
                    url_for, 
                    flash, 
                    redirect, 
                    request, 
                    abort, 
                    send_file)
from flask_login import (login_user, 
                        current_user, 
                        logout_user, 
                        login_required)
from werkzeug.utils import secure_filename
from system import (app, 
                    db, 
                    bcrypt)
from system.forms import (RegistrationForm, 
                            LoginForm, 
                            UpdateAccountForm, 
                            CreateExamForm, 
                            JoinExamForm, 
                            SubmitExamForm, 
                            RequestResetForm, 
                            ResetPasswordForm)
from system.models import (User, 
                            Exam, 
                            UserExam)
from system.detection import detect_cheating
from system.utils import (send_reset_email, 
                            save_picture, 
                            allowed_file, 
                            get_questions, 
                            image_to_encoding, 
                            verify_face,
                            get_result,
                            store_responses,
                            parse_answers)


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


@app.route("/<int:user_id>/update", methods=['GET', 'POST'])
@login_required
def update_face(user_id):
    user = User.query.get_or_404(user_id)
    if user_id != user.id:
        abort(403)
    if request.method == 'POST':
        try:
            encoding_file = image_to_encoding(request.form['face_img'], user.username)
            user.face_access = True
            user.encoding_file = encoding_file
            db.session.add(user)
            db.session.commit()
            flash(f'Face data updated successfully.', 'success')
        except:
            flash('Face not recognized.', 'danger')
        return redirect(url_for('account'))


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
                        duration=form.duration.data,
                        exam_code=form.exam_code.data,
                        questions=filename,
                        user_id=current_user.id
                    )
                    db.session.add(exam)
                    db.session.commit()
                    flash('Exam created successfully', 'success')
                    os.mkdir(os.path.join(app.root_path, 'static', 'logs', str(exam.id)))
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
            try:
                os.mkdir(os.path.join(app.root_path, 'static', 'logs', str(exam.id)))
            except:
                pass
            row = UserExam.query.filter_by(user_id=current_user.id, exam_id=exam_id).first()
            if not row:
                if exam.exam_code == form.exam_code.data:
                    # if exam.start_time > datetime.now():
                    #     flash('Exam did not start yet', 'danger')
                    # elif exam.start_time + timedelta(minutes=exam.duration) < datetime.now():
                    #     flash('Exam completed', 'danger')
                    # else:
                    if current_user and verify_face(current_user.encoding_file, request.form['face_img']):
                        return redirect(url_for('attempt_exam', exam_id=exam.id))
                    else:
                        flash('Joining Unsuccessful. Face not recognized.', 'danger')
                else:
                    flash('Exam code incorrect', 'danger')
            else:
                flash('Exam already attempted', 'danger')
                return redirect(url_for('home'))
        return render_template('join_exam.html', title='Join Exam', form=form)
    else:
        return redirect(url_for('correction', exam_id=exam_id))


@app.route("/attempt_exam/<int:exam_id>", methods=['GET', 'POST'])
@login_required
def attempt_exam(exam_id):
    exam = Exam.query.filter_by(id=exam_id).first()
    form = SubmitExamForm()
    test = get_questions(exam.questions)
    responses = []
    x = threading.Thread(target=detect_cheating, args=[current_user.id, exam], daemon=True)
    x.start()
    if request.method == 'POST':
        row = UserExam.query.filter_by(user_id=current_user.id, exam_id=exam_id).first()
        if row:
            flash('Exam already attempted', 'danger')
            return redirect(url_for('home'))
        else:
            if x.is_alive():
                for question in test:
                    responses.append(request.form.get(str(question[6])))
                path = store_responses(str(current_user.id)+str(exam.id), responses)
                score = get_result(responses, test, exam.marks)
                row = UserExam(user_id=current_user.id, exam_id=exam_id, attempted=True, attempted_file=path, marks=score)
                db.session.add(row)
                db.session.commit()
                flash(f'Exam submitted!', 'success')
                return redirect(url_for('home'))
            else:
                flash(f'Exam was submitted late!', 'danger')
                return redirect(url_for('home'))
    else:
        return render_template('exam.html', title=f'{exam.topic} Exam', test=test, form=form)


@app.route("/result")
@login_required
def result():
    if not current_user.user_access:
        exams = UserExam.query\
                .join(Exam, Exam.id == UserExam.exam_id)\
                .add_columns(UserExam.exam_id, Exam.topic, UserExam.marks, Exam.start_time, Exam.duration, UserExam.corrected)\
                .filter(UserExam.user_id == current_user.id)\
                .all()
        return render_template('result.html', exams=exams)
    else:
        return abort(403)


@app.route("/correction/<int:exam_id>", methods=['GET', 'POST'])
@login_required
def correction(exam_id):
    if current_user.user_access:
        user_attempts = UserExam.query.filter(UserExam.exam_id == exam_id, UserExam.attempted == True, UserExam.corrected == False).all()
        topic = Exam.query.filter_by(id=exam_id).first()
        return render_template('correction.html', title='Correction', user_attempts=user_attempts, topic=topic)
    else:
        abort(403)


@app.route("/correct/<int:exam_id>", methods=['GET', 'POST'])
@login_required
def correct(exam_id):
    details = UserExam.query.filter_by(id=exam_id).first()
    exam = Exam.query.filter_by(id=details.exam_id).first()
    questions = get_questions(exam.questions)
    answers = parse_answers(details.attempted_file)
    form = SubmitExamForm()
    score = 0
    if request.method == 'POST':
        for i in range(len(answers)):
            score += int(request.form.get(str(questions[i][6])))
        print(score)
        details.marks = score
        details.corrected = True
        db.session.add(details)
        db.session.commit()
        flash('Marks updated!', 'success')
        return redirect(url_for('correction', exam_id=exam.id))
    path = os.path.join(app.root_path, 'static', 'logs', str(details.exam_id), str(details.user_id))
    images = []
    for img in os.listdir(path):
        images.append(os.path.join('..', 'static', 'logs', str(details.exam_id), str(details.user_id), img))
    print(images)
    return render_template('correct.html', details=details, n=len(answers), max_marks=exam.marks//len(answers), questions=questions, answers=answers, form=form, images=images)


"""
def gen(camera):
    while True:
        frame, persons = camera.get_frame()
        if persons > 1:
            print(f'{persons} people detected.')
            # with app.app_context():
            #     flash('2 people detected.')
        # else:
        #     print('1 person detected.')
        if frame is not None:
            yield(b'--frame\r\n'
                b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n\r\n')


@app.route('/video_feed')
def video_feed():
    return Response(gen(VideoCamera()), mimetype='multipart/x-mixed-replace; boundary=frame')
"""


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