from flask import Flask, url_for
import cv2
import logging
    
class WebCam:
    '''webcam class has ip and camera number attributes so the cameras can exist
    across multiple files'''
    def __init__(self, ip=None, camera_number=None):
        self.ip = ip
        self.camera_number = camera_number
        self.capture = None

    def get_frame(self, capture):
        while True:
            hasFrame, frame = capture.read()
            if (self.camera_number == 0):
                frame = self.crop_frame(frame)
            if not hasFrame:
                raise Exception("Camera frame not obtained")

            _, jpeg = cv2.imencode('.jpg', frame)
            
            return jpeg.tobytes()

    def crop_frame(self, frame):
        # Get the dimensions of the frame
        try:
            height, width, _ = frame.shape
            # Crop the right half of the frame
            cropped_frame = frame[:, width // 2:]
            
            return cropped_frame
        except AttributeError as e:
            print('None frame')
            return None
        
def Camera():
    zedcam_blueprint = Blueprint('camera_1', __name__)
    anchor_blueprint = Blueprint('camera_2', __name__)
    REQUEST_API = Blueprint('request_api', __name__)
    
    # Creating the custom logger
    logging.basicConfig(
        filename='logs/main.log',      # Name of the log file
        filemode='a',            # Append mode (use 'w' for overwrite each time)
        format='%(asctime)s - %(levelname)s - %(message)s',  # Log message format
        datefmt='%Y-%m-%d %H:%M:%S',  # Timestamp format
        level=logging.INFO       # Minimum log level to record
    )

    app = Flask(__name__)
    app.register_blueprint(camera_1)
    app.register_blueprint(camera_2)
    app.register_blueprint(routes.get_blueprint())

    #Opening cameras through flask regardless of parameters or configuration
    @app.route('/video_0')
    def video_0():
        video_url = url_for('camera_1.video_0')
        
        # Make a request to the video_0 endpoint
        response = app.test_client().get(video_url)
        
        # Return the response to the client
        return response.data

    @app.route('/video_1')
    def video_1():
        video_url = url_for('camera_2.video_1')
        
        # Make a request to the video_0 endpoint
        response = app.test_client().get(video_url)
        
        # Return the response to the client
        return response.data
    @REQUEST_API.route('/stream')
    def monitoring():
        try:
            webcam = WebCam()
            return Response(gen(webcam), mimetype='multipart/x-mixed-replace; boundary=frame')
        except Exception as err:
            return Response(f'Error {err}')
        
    @zedcam_blueprint.route('/video_0')
    def video_0():
        try:
            # Replace with your IP camera URL
            zedcam = WebCam(camera_number=0)
            return Response(routes.gen(zedcam), mimetype='multipart/x-mixed-replace; boundary=frame')
        except Exception as err:
            return Response(f'Error {err}')


    @anchor_blueprint.route('/video_1')
    def video_1():
        try:
            anchor_camera = WebCam(camera_number=2)
            return Response(routes.gen(anchor_camera), mimetype='multipart/x-mixed-replace; boundary=frame')
        except Exception as err:
            return Response(f'Error {err}')    

def get_blueprint():
    """Return the blueprint for the main app module"""
    return REQUEST_API


def gen(webcam):
    capture = cv2.VideoCapture(webcam.camera_number)
    if not capture:
        raise Exception("Error accessing the WebCam")

    while True:
        frame = webcam.get_frame(capture)
        yield (
            b'--frame\r\n'
            b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n\r\n'
        )


