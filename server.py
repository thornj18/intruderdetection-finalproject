from flask import Flask, request, jsonify, send_file, send_from_directory
from requests.exceptions import HTTPError
import onesignal as onesignal_sdk
from flask_sqlalchemy import SQLAlchemy
from operator import itemgetter
from flask_marshmallow import Marshmallow
from marshmallow import fields
from flask_uploads import UploadSet, configure_uploads, IMAGES
from picamera import PiCamera
import requests
import sys
import json
import urllib, httplib, base64, json
import time
import RPi.GPIO as GPIO
import os
import os.path
import uuid
import datetime
import time
import pytz
local_tz = pytz.timezone('Africa/Dar_es_Salaam')

isRecognizing = False
player_id = "392a521b-3d90-452f-b0cb-5145ae4d755a"		

onesignal_client = onesignal_sdk.Client(user_auth_key="ODgzZDhhY2YtZDBkYi00ODQ0LWI1NzQtMDI0ZDQ2YzRiYmI5",
                                        app={"app_auth_key": "MjljYzZjZjAtZmU2Mi00NzM3LWEyNTItMzljYzkwNmI0NzVk", "app_id": "1274c21e-1677-4291-9e17-e099d6b3045b"})

BaseDirectory = '/home/pi/opneface-server/files/photos/detected/'
app = Flask(__name__)
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'server.sqlite')
db = SQLAlchemy(app)
ma = Marshmallow(app)
url = 'https://westcentralus.api.cognitive.microsoft.com/face/v1.0'
KEY = '0f8d012f2f5e4a04b7af47ae077ab9c7'
group_id = 'users'
fileList = [] # list of filePaths that were passed through as images
faceIdList = [] # list for face id's generated using api - detect
confidenceList = [] # list of confidence values derived from api - identif
directory = "";



#*****Camera Setup*****#




GPIO.setmode(GPIO.BCM)
sleepTime = .1
buttonPin = 17
doorPin = 21
GPIO.setup(buttonPin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(doorPin, GPIO.OUT)


def lock():
    GPIO.setup(doorPin, GPIO.OUT)
    GPIO.output(doorPin, GPIO.HIGH)
    

def unlock():
    GPIO.output(doorPin, GPIO.LOW)
    GPIO.cleanup()
    time.sleep(5)
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(doorPin, GPIO.OUT)
    

def button_callback(channel):
    facial_recognition()

while(not isRecognizing):
    #try:
        GPIO.add_event_detect(buttonPin,GPIO.RISING,callback=button_callback) # Setup event on pin 10 rising edge
        isRecognizing = True
    #finally:
        #


def iter():
    for fileName in os.listdir(directory):
        if fileName.endswith('.jpg'):
            filePath = os.path.join(directory, fileName) # joins directory path with filename to create file's full path
            fileList.append(filePath)
            detect(filePath)

# detects faces in images from previously stated directory using azure post request
def detect(img_url):
    headers = {'Content-Type': 'application/octet-stream', 'Ocp-Apim-Subscription-Key': KEY}
    body = open(img_url,'rb')

    params = urllib.urlencode({'returnFaceId': 'true'})
    conn = httplib.HTTPSConnection('westcentralus.api.cognitive.microsoft.com')
    conn.request("POST", '/face/v1.0/detect?%s' % params, body, headers)
    response = conn.getresponse()
    photo_data = json.loads(response.read())

    if not photo_data: # if post is empty (meaning no face found)
        print('No face identified')
    else: # if face is found
        for face in photo_data: # for the faces identified in each photo
            faceIdList.append(str(face['faceId'])) # get faceId for use in identify

# Takes in list of faceIds and uses azure post request to match face to known faces
def identify(ids):
    if not faceIdList: # if list is empty, no faces found in photos
        result = [('n', .0), 'n'] # create result with 0 confidence
        return result # return result for use in main
    else: # else there is potential for a match
        headers = {'Content-Type': 'application/json', 'Ocp-Apim-Subscription-Key': KEY}
        params = urllib.urlencode({'personGroupId': group_id})
        body = "{'personGroupId':'"+group_id+"', 'faceIds':"+str(ids)+", 'confidenceThreshold': '.5'}"
        conn = httplib.HTTPSConnection('westcentralus.api.cognitive.microsoft.com')
        conn.request("POST", "/face/v1.0/identify?%s" % params, body, headers)
        response = conn.getresponse()

        data = json.loads(response.read()) # turns response into index-able dictionary
        print(data)
        for resp in data:
            candidates = resp['candidates']
            for candidate in candidates: # for each candidate in the response
                confidence = candidate['confidence'] # retrieve confidence
                personId = str(candidate['personId']) # and personId
                confidenceList.append((personId, confidence))
        conn.close()
        SortedconfidenceList = zip(confidenceList, fileList) # merge fileList and confidence list
        sortedConfidence = sorted(SortedconfidenceList, key=itemgetter(1)) # sort confidence list by confidence
        return sortedConfidence[-1] # returns tuple with highest confidence value (sorted from smallest to biggest)


# takes in person_id and retrieves known person's name with azure GET request
def getName(person_Id):
    user = db.session.query(User).filter(User.azure_id==person_Id).first()
    return user


def facial_recognition():
    camera = PiCamera() # initiate camera
    count = 0
    while True:
        count+=1
        directory = BaseDirectory+str(uuid.uuid4().hex)+'/'
        os.mkdir(directory) # make new directory for photos to be uploaded to
        print(count)
        print(directory)
        for x in range(0,3):
            date = datetime.datetime.now().strftime('%m_%d_%Y_%M_%S_') # change file name for every photo
            camera.capture(directory + date +'.jpg')
            time.sleep(1) # take photo every second
        camera.close()
        for fileName in os.listdir(directory):
            if fileName.endswith('.jpg'):
                filePath = os.path.join(directory, fileName) # joins directory path with filename to create file's full path
                fileList.append(filePath)
                detect(filePath)
        result = identify(faceIdList)
        if result[0][1] > .5: # if confidence is greater than .7 get name of person
            user = getName(result[0][0])
            if user.blacklisted == False:
                message = user.username+' is at the door'
                print(message)
                isRecognizing = False
                log_event(user, "Door opened!")
                notify(message, "User authenticated")
                unlock()
                break
            else:
                message = user.username+' is at the door'
                print(message)
                isRecognizing = False
                log_event(user, "Door remains closed!")
                notify(message, "Restricted entry, "+user.username+" is resctricted!")
            
                time.sleep(5)
                break
            
        else:
           isRecognizing = False
           notify("Unrecognized user detected, initiate live stream to see who it is", "Intruder detected")
           camera.close()
           GPIO.cleanup()
           break

def notify(message, header):
    new_notification = onesignal_sdk.Notification(contents={"en": message})
    new_notification.set_parameter("headings", {"en":header})

    # set filters
    new_notification.set_target_devices([player_id])

    # send notification, it will return a response
    onesignal_response = onesignal_client.send_notification(new_notification)
    print(onesignal_response.status_code)
    print(onesignal_response.json())
    
def log_event(user, status):
    event_id = str(uuid.uuid4().hex)
    event = Event(event_id=event_id, owner=user, status=status)
    db.session.add(event)
    db.session.commit()

@app.route("/lock_door", methods=["GET"])
def lock_door():
    lock()
    return jsonify({"status":"200"})

@app.route("/unlock_door", methods=["GET"])
def unlock_door():
    unlock()
    return jsonify({"status":"200"})

def train():
    params = urllib.urlencode({'personGroupId': group_id})
    headers = {'Ocp-Apim-Subscription-Key': KEY}

    conn = httplib.HTTPSConnection('westcentralus.api.cognitive.microsoft.com')
    conn.request("POST", "/face/v1.0/persongroups/"+group_id+"/train?%s" % params, "{body}", headers)
    response = conn.getresponse()
    #data = json.loads(response.read())
    print(response.read()) # if successful prints empty json body
    
    
@app.route("/survelliance", methods=["GET"])
def survelliance():
    return jsonify()
    
    
    

#Avatar model for the database
class Avatar(db.Model):
    avatar_id = db.Column(db.String(), primary_key=True)
    user_id = db.Column(db.String(), db.ForeignKey('user.user_id'))
    avatar_url = db.Column(db.String())

class AvatarSchema(ma.ModelSchema):
    class Meta:
        # Fields to expose
        model = Avatar
        

avatar_schema = AvatarSchema()
avatars_schema = AvatarSchema(many=True)

#User model for the database
class User(db.Model):
    user_id = db.Column(db.String(), primary_key=True)
    azure_id = db.Column(db.String())
    username = db.Column(db.String(80))
    email = db.Column(db.String(120))
    phone = db.Column(db.Integer, unique=True)
    address = db.Column(db.String())
    blacklisted = db.Column(db.Boolean)
    avatars = db.relationship('Avatar', backref='user', lazy=True)
    events = db.relationship('Event', backref='owner', lazy=True)


class Event(db.Model):
    event_id = db.Column(db.String(), primary_key=True)
    user_id = db.Column(db.String(), db.ForeignKey('user.user_id'))
    created = db.Column(db.DateTime, default=local_tz.localize(datetime.datetime.now()))
    status = db.Column(db.String())
    

class EventSchema(ma.ModelSchema):
    class Meta:
        # Fields to expose
        model = Event
    
event_schema = EventSchema()
events_schema = EventSchema(many=True)
        


class UserSchema(ma.ModelSchema):
    class Meta:
        # Fields to expose
        model = User
    avatars = fields.Nested(AvatarSchema, many=True, only=['avatar_id','avatar_url'])
    events = fields.Nested(EventSchema, many=True, only=['event_id','created', 'status'])
        


user_schema = UserSchema()
users_schema = UserSchema(many=True)



@app.route("/hello")
def hello():
    return "Hello World!"

@app.route("/user/create", methods=["POST"])
def create_user():
    user_id = str(uuid.uuid4().hex)
    username = request.json['username']
    email = request.json['email']
    phone = request.json['phone']
    email = request.json['email']
    address = request.json['address']
    blacklisted = False
    new_user = User(user_id=user_id,username=username, email=email, phone=phone, address=address, blacklisted=blacklisted)
    
    
    headers = {'Content-Type': 'application/json', 'Ocp-Apim-Subscription-Key': KEY}
    params = urllib.urlencode({'personGroupId': group_id})
    conn = httplib.HTTPSConnection('westcentralus.api.cognitive.microsoft.com')
    body = "{'name':'"+new_user.username+"'}"
    conn.request("POST", "/face/v1.0/persongroups/{"+group_id+"}/persons?%s" % params, body, headers)
    response = conn.getresponse()
    data = json.loads(response.read()) # turns response into index-able dictionary
    print(data)
    azure_id = data['personId']
    
    new_user.azure_id = azure_id
    db.session.add(new_user)
    db.session.commit()
    user = user_schema.dump(new_user)
    
    conn.close()
    
    return jsonify(user.data)

# endpoint to show all users
@app.route("/users", methods=["GET"])
def get_users():
    all_users = User.query.all()
    result = users_schema.dump(all_users)
    return jsonify(result.data)

@app.route("/events", methods=["GET"])
def get_events():
    all_events = Event.query.all()
    result = events_schema.dump(all_events)
    return jsonify(result.data)


@app.route("/event/<id>", methods=["GET"])
def get_user_events(id):
    events = db.session.query(Event).filter(Event.user_id==id)
    print(events)
    result = events_schema.dump(events)
    return jsonify(result.data)
    

# endpoint to show all avatars
@app.route("/avatar", methods=["GET"])
def get_avatars():
    all_avatars = Avatar.query.all()
    print(all_avatars)
    result = avatars_schema.dump(all_avatars)
    return jsonify(result.data)

# endpoint to get one user
@app.route("/user/<id>", methods=["GET"])
def get_user(id):
    user = db.session.query(User).filter(User.user_id==id).first()
    result = user_schema.dump(user)
    return jsonify(result)

# endpoint to get one user
@app.route("/user/blacklist/<id>", methods=["GET"])
def update_blacklist(id):
    user = db.session.query(User).filter(User.user_id==id).first()
    blacklisted = request.json['state']
    user.blacklisted = blacklisted
    result = user_schema.dump(user)
    db.session.commit()
    return jsonify(result)

# endpoint to delete user
@app.route("/user/delete/<id>", methods=["GET"])
def user_delete(id):
    user = User.query.get(id)
    db.session.delete(user)
    db.session.commit()

    return user_schema.jsonify(user)


# endpoint to get one user avatars
@app.route("/user/avatars/<id>", methods=["GET"])
def get_user_avatars(id):
    avatars = db.session.query(Avatar).filter(Avatar.user_id==id)
    result = avatars_schema.dump(avatars)
    return jsonify(result)

# endpoint to get one user avatars
@app.route("/photo/<avatar_id>", methods=["GET"])
def get_user_avatar(avatar_id):
    print(avatar_id)
    avatar = db.session.query(Avatar).get(avatar_id)
    avatar_url = avatar_schema.dump(avatar).data['avatar_url']
    print(os.path.dirname(avatar_url))
    return send_from_directory(basedir+'/'+os.path.dirname(avatar_url), avatar_url.split('/')[-1])


# endpoint to upload photos of the user
@app.route("/upload", methods=["POST"])
def upload():
    headers = {'Content-Type': 'application/octet-stream', 'Ocp-Apim-Subscription-Key':KEY}
    conn = httplib.HTTPSConnection('westcentralus.api.cognitive.microsoft.com')
    photos = UploadSet('photos',IMAGES)
    folderUri = 'files/photos/'+request.form['username']
    user_id = request.form['user_id']
    app.config['UPLOADED_PHOTOS_DEST'] = folderUri
    configure_uploads(app, photos)
    if 'photo' in request.files:
        filename = photos.save(request.files['photo'])
        photoUrl=folderUri+'/'+filename
        user = db.session.query(User).filter(User.user_id==user_id).first()
        
        params = urllib.urlencode({'personGroupId': group_id, 'personId': user.azure_id}) # item[1] is the personId created from addPeople()
        
        avatar_id = str(uuid.uuid4().hex)
        a = Avatar(avatar_id = avatar_id, avatar_url = photoUrl, user=user)
        #user.avatars.append(a)f
        db.session.add(a)
        #db.session.add(user)
        db.session.commit()
##        return jsonify({'photoUrl':photoUrl})
        filePath = os.path.join(folderUri, filename)
        body = open(filePath,'rb')
        conn.request("POST", "/face/v1.0/persongroups/{"+user.azure_id+"}/persons/"+user.azure_id+"/persistedFaces?%s" % params, body, headers)
        response = conn.getresponse()
        data = json.loads(response.read()) # successful run will print persistedFaceId
        print(data)
        train()
        return jsonify({'avatar':a.avatar_id})
    else:
        return ({'error':'Please upload a file'})

@app.route("/group/create", methods=["POST"])
def create_group():
    body = '{"name": "users"}'
    params = urllib.urlencode({'personGroupId': group_id})
    headers = {'Content-Type': 'application/json', 'Ocp-Apim-Subscription-Key': KEY}
    conn = httplib.HTTPSConnection('westcentralus.api.cognitive.microsoft.com')
    conn.request("PUT", "/face/v1.0/persongroups/{personGroupId}?%s" % params, body, headers)
    response = conn.getresponse()
    data = response.read()
    print(data)
    return jsonify(data)
    conn.close()



if __name__ == '__main__':
    app.run(host='0.0.0.0')
