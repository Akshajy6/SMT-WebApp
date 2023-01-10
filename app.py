from flask import Flask, flash, session, redirect, render_template, request
import pyrebase
import os
from dotenv import load_dotenv
from json import load
from functools import wraps, lru_cache
import phonenumbers
import datetime
import uuid
from werkzeug.utils import secure_filename

app = Flask(__name__)

with open("config.json") as file:
  config = load(file)

load_dotenv("dev.env")

firebaseApp = pyrebase.initialize_app(config)
auth = firebaseApp.auth()
db = firebaseApp.database()
storage = firebaseApp.storage()

app.config["TEMPLATES_AUTO_RELOAD"] = True
app.config["SESSION_PERMANENT"] =  False
app.config["SESSION_TYPE"] = "filesystem"
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY")
app.config["UPLOAD_FOLDER"] = r"static\uploads"

CHAPTERS = ["Wheeler"]

@lru_cache
def login_required(f):
  @wraps(f)
  def decorated_function(*args, **kwargs):
    if session.get("user_id") is None:
        return redirect("/login")
    return f(*args, **kwargs)
  return decorated_function

@lru_cache
def lookup(user_id):
  try:
    info = auth.get_account_info(user_id)["users"][0]
  except:
    flash("An unexpected error has occurred. Please log back in and try again. If this issue persists, please contact the SMT Team.")
    return redirect("/logout")
  name = info["displayName"]
  email = info["email"]
  emailVerified = info["emailVerified"]
  tutors = db.child("users").child("tutors").get()
  students = db.child("users").child("students").get()
  admin = False
  if tutors.val():
    if name in tutors.val():
      type = "tutors"
      assignment = db.child("users").child(type).child(name).get().val().get("assignedStudent")
      admin = db.child("users").child("tutors").child(name).get().val()["admin"]
  if students.val():
    if name in students.val():
      type = "students"
      assignment = db.child("users").child(type).child(name).get().val().get("assignedTutor")
  contractSigned = db.child("users").child(type).child(name).get().val()["contractSigned"]
  return {'name': name, 'email': email, 'type': type, 'admin': admin, 'emailVerified': emailVerified, 'contractSigned': contractSigned, 'assignment': assignment}

@lru_cache
def email_verification_required(f):
  @wraps(f)
  def decorated_function(*args, **kwargs):
    try:
      if not auth.get_account_info(session["user_id"])["users"][0]["emailVerified"]:
        return redirect("/email-verification")
    except:
      return redirect("/logout")
    return f(*args, **kwargs)
  return decorated_function

@lru_cache
def contract_signature_required(f):
  @wraps(f)
  def decorated_function(*args, **kwargs):
    info = lookup(session["user_id"])
    name = info["name"]
    type = info["type"]
    if not db.child("users").child(type).child(name).get().val()["contractSigned"]:
      return redirect("/contract")
    return f(*args, **kwargs)
  return decorated_function

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ['png', 'jpg', 'jpeg']

def getMessages(sender, receiver):
  groups = db.child("messages").get()
  messageList = []
  if groups.val():
    for group in groups:
      if sender in group.key() and receiver in group.key():
        messages = db.child("messages").child(group.key()).get()
        for message in messages:
          messageList.append({"message": message.val()["message"], "sender": message.val()["senderName"], "time": message.val()["timeSent"]})
    messageList.sort(key=lambda item:item['time'])
    return messageList
  return False
    
@app.route("/", methods=["GET", "POST"])
@login_required
@email_verification_required
@contract_signature_required
def dashboard():
  info = lookup(session["user_id"])
  if info["admin"]:
    return redirect("/admin")
  name = info["name"]
  type = info["type"]
  assignment = info["assignment"]
  tutors = db.child("users").child("tutors").get()
  admins = []
  if tutors.val():
    for tutor in tutors:
      try:
        if tutor.val()["admin"]:
          admins.append(tutor.key())
      except:
        continue
  if session.get("justSentMessage") and session.get("messageReceiver"):
    receiver = session["messageReceiver"]
    messageList = []
    if not getMessages(name, receiver):
      messagesPresent = False
    else:
      messageList = getMessages(name, receiver)
      messagesPresent = True
    session["justSentMessage"] = False
    session["messageReceiver"] = ""  
    return render_template("dashboard.html", name=name, type=type, receiver=receiver, assignment=assignment, admins=admins, messagesPresent=messagesPresent, messageList=messageList)
  if request.method == "POST":
    receiver = request.form.get("user")
    if not receiver:
      flash("Please specify which user.")
      return redirect("/")
    messageList = []
    if not getMessages(name, receiver):
      messagesPresent = False
    else:
      messageList = getMessages(name, receiver)
      messagesPresent = True
    return render_template("dashboard.html", name=name, type=type, receiver=receiver, assignment=assignment, admins=admins, messagesPresent=messagesPresent, messageList=messageList)
  return render_template("dashboard.html", name=name, type=type, assignment=assignment, admins=admins)

@app.route("/send", methods=["POST"])
@login_required
@email_verification_required
@contract_signature_required
def send():
  receiver = request.form.get("receiver")
  message = request.form.get("message")
  name = lookup(session["user_id"])["name"]
  if not receiver:
    flash("Please provide the receiver of your message")
  elif not message:
    flash("Please provide the message to send.")
  message = {
    "senderName": name,
    "receiverName": receiver,
    "message": message,
    "timeSent": str(datetime.datetime.fromtimestamp(datetime.datetime.now().timestamp()).replace(microsecond=0))
  }
  db.child("messages").child(name + " - " +  receiver).push(message)
  session["justSentMessage"] = True
  session["messageReceiver"] = receiver
  return redirect("/")

@app.route("/admin", methods=["GET", "POST"])
@login_required
@email_verification_required
@contract_signature_required
def admin_dashboard():
  info = lookup(session["user_id"])
  if not info["admin"]:
    return redirect("/")
  name = info["name"]
  type = info["type"]
  tutors = db.child("users").child("tutors").get()
  students = db.child("users").child("students").get()
  users = []
  if tutors.val():
    for tutor in tutors:
      users.append(tutor.key())
  if students.val():
    for student in students:
      users.append(student.key())
  users.remove(name)
  users.sort()
  if session.get("justSentMessage") and session.get("messageReceiver"):
    receiver = session["messageReceiver"]
    messageList = []
    if not getMessages(name, receiver):
      messagesPresent = False
    else:
      messageList = getMessages(name, receiver)
      messagesPresent = True
    return render_template("admin-dashboard.html", name=name, type=type, receiver=receiver, chatList=users, messagesPresent=messagesPresent, messageList=messageList)
  if request.method == "POST":
    receiver = request.form.get("user")
    if not receiver:
      flash("Please specify which user.")
      return redirect("/admin")
    messageList = []
    if not getMessages(name, receiver):
      messagesPresent = False
    else:
      messageList = getMessages(name, receiver)
      messagesPresent = True
    return render_template("admin-dashboard.html", name=name, type=type, receiver=receiver, chatList=users, messagesPresent=messagesPresent, messageList=messageList)
  return render_template("admin-dashboard.html", name=name, type=type, chatList=users)

@app.route("/record-session", methods=["GET", "POST"])
@login_required
@email_verification_required
@contract_signature_required
def record_session():
  if lookup(session["user_id"])["type"] != "tutors":
    return redirect("/")
  if request.method == "GET":
    return render_template("record-session.html")
  start = request.form.get("start")
  end = request.form.get("end")
  sfname = request.form.get("sfname")
  slname = request.form.get("slname")
  subject = request.form.get("subject")
  topic = request.form.get("topic")
  screenshot = request.files["screenshot"]
  if not start or not end or not sfname or not slname or not subject:
    flash("Please provide all of the above information.")
    return redirect("/record-session")
  if not allowed_file(screenshot.filename):
    flash("File type not allowed.")
    return redirect("/record-session")
  tutorName = lookup(session["user_id"])["name"]
  studentName = sfname + " " + slname
  date = str(datetime.datetime.today().strftime('%Y-%m-%d'))
  sessionData = {
    'date': date,
    'startTime': start,
    'endTime': end,
    'studentName': studentName,
    'tutorName': tutorName,
    'subject': subject,
    'topic': topic,
  }
  db.child("sessions").child(tutorName + " - " +  studentName).child(date).set(sessionData)
  file_name = secure_filename(screenshot.filename)
  path = os.path.join(app.config['UPLOAD_FOLDER'], file_name)
  screenshot.save(path)
  storage.child("screenshots").child(tutorName + " - " +  studentName).child(date).put(path)
  os.remove(path)
  return redirect("/")

@app.route("/change-assignments", methods=["GET", "POST"])
@login_required
@email_verification_required
@contract_signature_required
def change_assignment():
  if not lookup(session["user_id"])["admin"]:
    return redirect("/")
  if request.method == "GET":
    tutors = db.child("users").child("tutors").get()
    students = db.child("users").child("students").get()
    tutorList = []
    studentList = []
    if tutors.val():
      for tutor in tutors:
        tutorList.append(tutor.key())
    if students.val():
      for student in students:
        studentList.append(student.key())
    tutorList.sort()
    studentList.sort()
    return render_template("reassignment.html", tutors=tutorList, students=studentList)
  tutor = request.form.get("tutor")
  student = request.form.get("student")
  if not tutor or not student:
    flash("Please specify which tutor and student you wish to re-assign.")
    return redirect("/change-assignments")
  db.child("users").child("students").child(student).update({"assignedTutor": tutor})
  db.child("users").child("tutors").child(tutor).update({"assignedStudent": student})
  flash("Assignments updated. Student " + student + " has been assigned to tutor " + tutor + ".")
  return redirect("/change-assignments")

@app.route("/tutor-selection", methods=["GET", "POST"])
@login_required
@email_verification_required
@contract_signature_required
def tutor_selection():
  if request.method == "GET":
    info = lookup(session["user_id"])    
    if info["type"] != "students" or info["assignment"]:
      return redirect("/")
    tutors = db.child("users").child("tutors").get()
    profiles = []
    if tutors.val():
      for tutor in tutors:
        try:
          assignment = tutor.val()['assignment']
          continue
        except:
          profiles.append({"name": tutor.key(), "profile": tutor.val()["profile"]})
    return render_template("tutor-selection.html", profiles=profiles)
  else:
    tutor = request.form.get("tutor")
    if not tutor:
      flash("Please select a tutor.")
      return redirect("/tutor-selection")
    student = lookup(session["user_id"])["name"]
    db.child("users").child("students").child(student).update({"assignedTutor": tutor})
    db.child("users").child("tutors").child(tutor).update({"assignedStudent": student})
    return redirect("/")
    
@app.route("/email-verification", methods=["GET", "POST"])
@login_required
def email_verification():
  if request.method == "GET":
    info = lookup(session["user_id"])
    email = info["email"]
    verified = auth.get_account_info(session["user_id"])["users"][0]["emailVerified"]
    type = info["type"]
    if verified:
      if type == "tutors":
        return redirect("/")
      if type == "students":
        return redirect("/tutor-selection")
    return render_template("verification-page.html", email=email)
  else:
    auth.send_email_verification(session["user_id"])
    return redirect("/email-verification")

@app.route("/contract", methods=["GET", "POST"])
@login_required
@email_verification_required
def contract():
  if request.method == "GET":
    info = lookup(session["user_id"])
    type = info["type"]
    name = info["name"]
    contractSigned = db.child("users").child(type).child(name).get().val()["contractSigned"]
    if type != "students":
      if contractSigned:
        return redirect("/")
      return render_template("tutor-contract.html")
    if not contractSigned:
      return render_template("student-contract.html")
    if not info["assignment"]:
      return redirect("/tutor-selection")
    return redirect("/")
  else:
    eSig = request.form.get("eSig")
    pictureUse = request.form.get("pictureUse") == "Yes"
    pictureSig = request.form.get("pictureSig")
    if not eSig or not pictureSig:
      flash("Please fill out all items on the contract.")
      return redirect("/contract")
    data = {
      'contractSigned': True,
      'contractInfo': {
        "eSig": eSig,
        "pictureUse": pictureUse,
        "pictureSig": pictureSig,
        "date": str(datetime.datetime.today().strftime('%Y-%m-%d'))
      }
    }
    info = lookup(session["user_id"])
    name = info["name"]
    accountType = info["type"]
    db.child("users").child(accountType).child(name).update(data)
    return redirect("/contract")

@app.route("/login", methods=["GET", "POST"])
def login():
  session.clear()
  if request.method == "GET":
    return render_template("login.html")
  else:
    email = request.form.get("email")
    password = request.form.get("password")
    if not email or not password:
      flash("Please provide an email/password.")
    else:
      try:
        user = auth.sign_in_with_email_and_password(email, password)
        session["user_id"] = user["idToken"]
      except:
        flash("Incorrect email or password. Please try again.")
    return redirect("/")

@app.route("/logout")
def logout(): 
  session.clear()
  return redirect("/")

@app.route("/register", methods=["GET", "POST"])
def register():
  session.clear()
  if request.method == "GET":
    return render_template("register.html")
  else:
    if request.form["registrationType"] == "Register as a Student":
      return redirect("/register-student")
    elif request.form["registrationType"] == "Register as a Tutor":
      return redirect("/register-tutor")
    else:
      return redirect("/register")

@app.route("/register-tutor", methods=["GET", "POST"])
def register_tutor():
  if request.method == "GET":
    return render_template("register-tutor.html", chapters=CHAPTERS)
  else:
    firstName = request.form.get("fname")
    lastName = request.form.get("lname")
    email = request.form.get("email")
    number = request.form.get("phone")
    chapter = request.form.get("chapter")
    profile = request.form.get("profile")
    password = request.form.get("password")
    confirmation = request.form.get("confirmation")
    if not firstName or not lastName or not email or not number or not chapter or not profile or not password or not confirmation:
      flash("Please provide all required information.")
      return redirect("/register-tutor")
    if chapter not in CHAPTERS:
      flash("Invalid chapter.")
      return redirect("/register-tutor")
    if len(password) < 8:
      flash("Password must be at least 8 characters in length.")
      return redirect("/register-tutor")
    if password != confirmation:
      flash("Password and password confirmation must match.")
      return redirect("/register-tutor")
    try:
      user = auth.create_user_with_email_and_password(email, password)
    except:
      flash("User with that email already exists.")
      return redirect("/register-tutor")
    name = firstName + " " + lastName
    auth.update_profile(user["idToken"], display_name=name)
    auth.send_email_verification(user["idToken"])
    data = {
      'uuid': user["localId"],
      'admin': False,
      'email': email,
      'phoneNumber': phonenumbers.format_number(phonenumbers.parse(number, "US"), phonenumbers.PhoneNumberFormat.NATIONAL),
      'accountType': "tutor",
      'chapter': chapter,
      'contractSigned': False,
      'profile': profile,
      'assignedStudent': {

      }
    }
    db.child("users").child("tutors").child(name).set(data)
    session["user_id"] = user["idToken"]
    return redirect("/email-verification")

@app.route("/register-student", methods=["GET", "POST"])
def register_student():
  if request.method == "GET":
    return render_template("register-student.html")
  else:
    firstName = request.form.get("fname")
    lastName = request.form.get("lname")
    parentFirstName = request.form.get("pfname")
    parentLastName = request.form.get("plname")
    email = request.form.get("email")
    number = request.form.get("phone")
    zipcode = request.form.get("zipcode")
    gender = request.form.get("gender")
    grade = request.form.get("grade")
    ethnicity = request.form.get("ethnicity")
    subject = request.form.get("subject")
    salary = request.form.get("salary")
    circumstance = request.form.getlist("circumstance")
    password = request.form.get("password")
    confirmation = request.form.get("confirmation")
    if not firstName or not lastName or not parentFirstName or not parentLastName or not email or not number or not zipcode or not gender or not grade or not ethnicity or not subject or not salary or not password or not confirmation:
      flash("Please provide all of the above information.")
      return redirect("/register-student")
    if len(password) < 8:
      flash("Password must be at least 8 characters in length.")
      return redirect("/register-student")
    if password != confirmation:
      flash("Password and password confirmation must match.")
      return redirect("/register-student")
    try:
      user = auth.create_user_with_email_and_password(email, password)
    except:
      flash("User with that email already exists.")
      return redirect("/register-student")
    name = firstName + " " + lastName
    auth.update_profile(user["idToken"], display_name=name)
    auth.send_email_verification(user["idToken"])
    data = {
      'id': user["localId"],
      'email': email,
      'parentName': parentFirstName + " " + parentLastName,
      'phoneNumber': phonenumbers.format_number(phonenumbers.parse(number, "US"), phonenumbers.PhoneNumberFormat.NATIONAL),
      'accountType': "student",
      'contractSigned': False,
      'subject': subject,
    }
    demographicData = {
      'ZIPCode': zipcode,
      'gender': gender,
      'grade': grade,
      'ethnicity': ethnicity,
      'salary': salary,
      'familyCircumstance': circumstance,
    }
    db.child("users").child("students").child(name).set(data)
    db.child("users").child("students").child(name).child("demographicInfo").set(demographicData)
    session["user_id"] = user["idToken"]
    return redirect("/email-verification")

"""
TODO:
IMPROVEMENTS (NOT URGENT)
- remove original assignments from db after reassigning
- replace multiple db updates with one multi-location update (hopefully faster)
- use 'each', 'shallow', and complex query methods to make looping through db better/faster

2. Incorporate with GoDaddy? Design?
3. How to track Zoom video session to verify hours?
4. Security 
Set different read/write rules for each route.(allow if authenticated?) Ensure https and other protocols, completely secure everything before deploying it on production server and shifting over to domain.
"""