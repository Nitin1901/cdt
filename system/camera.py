import cv2, os
from system.utils import detect_faces, detect_eyes, cut_eyebrows, blob_process
from system import app


BASE = os.path.join(app.root_path, 'static', 'models')

face_cascade = cv2.CascadeClassifier(os.path.join(BASE, 'haarcascade_frontalface_default.xml'))
eye_cascade = cv2.CascadeClassifier(os.path.join(BASE, 'haarcascade_eye.xml'))
detector_params = cv2.SimpleBlobDetector_Params()
detector_params.filterByArea = True
detector_params.maxArea = 1500
detector = cv2.SimpleBlobDetector_create(detector_params)


class VideoCamera(object):
    def __init__(self):
        self.video = cv2.VideoCapture(0)
    
    def __del__(self):
        self.video.release()
    
    def get_frame(self):
        _, frame = self.video.read()
        frame = cv2.resize(frame, (640, 480))
        (face_frame, (x, y, w, h), persons) = detect_faces(frame, face_cascade)
        if face_frame is not None:
            cv2.rectangle(frame, (x, y), (x+w, y+h), (0, 255, 0), 2)
            if face_frame is not None:
                eyes = detect_eyes(face_frame, eye_cascade)
                for eye in eyes:
                    if eye is not None:
                        threshold = 55
                        eye = cut_eyebrows(eye)
                        keypoints = blob_process(eye, threshold, detector)
                        eye = cv2.drawKeypoints(eye, keypoints, eye, (0, 0, 255), cv2.DRAW_MATCHES_FLAGS_DRAW_RICH_KEYPOINTS)

            ret, jpeg = cv2.imencode('.jpg', frame)
            return (jpeg.tobytes(), persons)

        else:
            return None, 0
