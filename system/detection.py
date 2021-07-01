import cv2, dlib, winsound, os
from datetime import datetime, timedelta
import numpy as np
from system.gaze_tracking import GazeTracking
from system import app
from flask import flash, redirect, url_for


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
                    print('Found copying! Disqualified!')
                    with app.app_context():
                        print(app)
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
