import os
import csv
import secrets
import threading
from datetime import datetime, timedelta
from PIL import Image
import base64
from io import BytesIO
import numpy as np
import cv2
import face_recognition
from flask import render_template, url_for, flash, redirect, request, abort, send_file, Response
from werkzeug.utils import secure_filename
from flask_mail import Message
from system import app, db, bcrypt, mail
from system.camera import VideoCamera
from system.forms import RegistrationForm, LoginForm, UpdateAccountForm, CreateExamForm, JoinExamForm, SubmitExamForm, RequestResetForm, ResetPasswordForm
from system.models import User, Exam, UserExam
from system.detection import detect_cheating
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
        abort(403)


@app.route("/attempt_exam/<int:exam_id>", methods=['GET', 'POST'])
@login_required
def attempt_exam(exam_id):
    exam = Exam.query.filter_by(id=exam_id).first()
    form = SubmitExamForm()
    test = get_questions(exam.questions)
    responses = []
    x = threading.Thread(target=detect_cheating, args=[current_user.username, exam.duration], daemon=True)
    x.start()
    if request.method == 'POST':
        row = UserExam.query.filter_by(user_id=current_user.id, exam_id=exam_id).first()
        if row:
            flash('Exam already attempted', 'danger')
            return redirect(url_for('home'))
        else:
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


def image_to_encoding(image, username):
    file_path = username + '.npy'
    encoding_path = os.path.join(app.root_path, 'static/encodings', file_path)

    sbuf = BytesIO()
    sbuf.write(base64.b64decode(image[22:]))
    img = Image.open(sbuf)

    img = cv2.cvtColor(np.array(img), cv2.COLOR_BGR2RGB)
    img_enc = face_recognition.face_encodings(img)[0]
    if img_enc.size == 0:
        return False
    np.save(encoding_path, img_enc)

    return file_path


def verify_face(encodings, image):
    encoding_path = os.path.join(app.root_path, 'static/encodings', current_user.encoding_file)
    face_encodings_for_id = np.load(encoding_path, allow_pickle=True)

    sbuf = BytesIO()
    sbuf.write(base64.b64decode(image[22:]))
    img = Image.open(sbuf)

    img = cv2.resize(np.array(img), (0, 0), fx=0.6, fy=0.6)

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

    face_detector = cv2.CascadeClassifier(os.path.join(app.root_path, 'static/models', 'haarcascade_frontalface_alt2.xml'))
     
    faces = face_detector.detectMultiScale(
        gray,
        scaleFactor=1.2,
        minNeighbors=5,
        minSize=(50, 50),
        flags=cv2.CASCADE_SCALE_IMAGE
    )

    result = [None]*len(faces)

    for idx, (x,y,w,h) in enumerate(faces):
        encoding = face_recognition.face_encodings(rgb, [(y, x+w, y+h, x)])[0]
        if encoding.size == 0:
            print("No face detected...")
            return False
        result[idx] = face_recognition.compare_faces([face_encodings_for_id], encoding, 0.3)[0]

    if any(result):
        return True
    return False


"""
def detect_cheating(name, duration):

    BASE = os.path.join(app.root_path, 'static', 'models')

    start = datetime.now()

    classNames= []
    classFile = os.path.join(BASE, 'coco.names')
    with open(classFile, 'rt') as f:
        classNames = f.read().rstrip('\n').split('\n')

    configPath = os.path.join(BASE, 'ssd_mobilenet_v3_large_coco_2020_01_14.pbtxt')
    weightsPath = os.path.join(BASE, 'frozen_inference_graph.pb')
    warnings = 5
    count = 0
    threshold = 10
    gaze = GazeTracking()
    detector = dlib.get_frontal_face_detector()

    net = cv2.dnn_DetectionModel(weightsPath, configPath)
    net.setInputSize(320,320)
    net.setInputScale(1.0/ 127.5)
    net.setInputMean((127.5, 127.5, 127.5))
    net.setInputSwapRB(True)

    webcam = cv2.VideoCapture(0, cv2.CAP_DSHOW)

    while True:

        if start + timedelta(minutes=duration) == datetime.now():
            flash('Time is up', 'danger')
            return redirect(url_for('home'))

        _, frame = webcam.read()

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = detector(gray)

        classIds, confs, bbox = net.detect(frame, confThreshold=0.5)
        bbox = list(bbox)
        confs = list(np.array(confs).reshape(1,-1)[0])
        confs = list(map(float,confs))

        indices = cv2.dnn.NMSBoxes(bbox, confs, 0.5, 0.2)
        for i in indices:
            i = i[0]
            box = bbox[i]
            x,y,w,h = box[0],box[1],box[2],box[3]
            cv2.rectangle(frame, (x,y), (x+w,h+y), color=(0, 255, 0), thickness=2)
            category = classNames[classIds[i][0]-1].upper()
            cv2.putText(frame, category, (box[0]+10,box[1]+30), cv2.FONT_HERSHEY_COMPLEX,1,(0,255,0),2)
            if category in ['CELL PHONE', 'LAPTOP']:
                count += 1
                winsound.Beep(2500, 100)
                cv2.putText(frame, category, (box[0]+10,box[1]+30), cv2.FONT_HERSHEY_COMPLEX,1,(0,0,255),2)
                if count%warnings == 0:
                    path = os.path.join(app.root_path, 'static', 'logs', f'{name}_{count//warnings}.png')
                    cv2.imwrite(path, frame)
                    print('Saved frame to file system')
                if count == threshold:
                    with app.test_request_context():
                        flash('Found copying! Disqualified!', 'danger')
                        print('Found copying! Disqualified!')
                        return redirect(url_for('home'))

        i = 0
        for face in faces:
            x, y = face.left(), face.top()
            x1, y1 = face.right(), face.bottom()
            cv2.rectangle(frame, (x, y), (x1, y1), (0, 255, 0), 2)
            i += 1
            cv2.putText(frame, 'FACE '+str(i), (x-10, y-10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

            gaze.refresh(frame)

            frame = gaze.annotated_frame()
            text = ""

            if gaze.is_blinking():
                text = "Blinking"
            elif gaze.is_right():
                text = "Looking right"
            elif gaze.is_left():
                text = "Looking left"
            elif gaze.is_center():
                text = "Looking center"

            #cv2.putText(frame, text, (90, 60), cv2.FONT_HERSHEY_DUPLEX, 1.2, (147, 58, 31), 2)

            left_pupil = gaze.pupil_left_coords()
            right_pupil = gaze.pupil_right_coords()
            cv2.putText(frame, "Left pupil:  " + str(left_pupil), (50, 50), cv2.FONT_HERSHEY_DUPLEX, 0.5, (147, 58, 31), 1)
            cv2.putText(frame, "Right pupil: " + str(right_pupil), (50, 100), cv2.FONT_HERSHEY_DUPLEX, 0.5, (147, 58, 31), 1)

        cv2.imshow("Live", frame)

        if cv2.waitKey(1) == 27:
            break

    cv2.destroyAllWindows()
    webcam.release()

    return redirect(url_for('home'))
"""