from flask import Flask, flash, session, redirect, render_template, request
import pyrebase
import os
from dotenv import load_dotenv
from json import load
from functools import wraps
import phonenumbers
from datetime import date

app = Flask(__name__)

with open("config.json") as file:
  config = load(file)

load_dotenv("dev.env")

firebaseApp = pyrebase.initialize_app(config)
auth = firebaseApp.auth()
db = firebaseApp.database()

app.config["TEMPLATES_AUTO_RELOAD"] = True
app.config["SESSION_PERMANENT"] =  False
app.config["SESSION_TYPE"] = "filesystem"
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY")

chapters = ["Wheeler"]

def login_required(f):
  @wraps(f)
  def decorated_function(*args, **kwargs):
    if session.get("user_id") is None:
        return redirect("/login")
    return f(*args, **kwargs)
  return decorated_function

def email_verification_required(f):
  @wraps(f)
  def decorated_function(*args, **kwargs):
    if not auth.get_account_info(session["user_id"])["users"][0]["emailVerified"]:
      return redirect("/email-verification")
    return f(*args, **kwargs)
  return decorated_function

def contractSigned():
  name = auth.get_account_info(session['user_id'])["users"][0]["displayName"]
  accType = lookup(session["user_id"])
  return db.child("users").child(accType).child(name).get().val()["contractSigned"]

def contract_signature_required(f):
  @wraps(f)
  def decorated_function(*args, **kwargs):
    if not contractSigned():
      return redirect("/contract")
    return f(*args, **kwargs)
  return decorated_function

def lookup(user_id):
  name = auth.get_account_info(user_id)["users"][0]["displayName"]
  tutors = db.child("users").child("tutors").get()
  students = db.child("users").child("students").get()
  if name in tutors.val():
    return "tutors"
  if name in students.val():
    return "students"

@app.route("/")
@login_required
@email_verification_required
@contract_signature_required
def index():
  name = auth.get_account_info(session["user_id"])["users"][0]["displayName"]
  return render_template("index.html", name=name)

@app.route("/email-verification", methods=["GET", "POST"])
@login_required
def email_verification():
  if request.method == "GET":
    info = auth.get_account_info(session["user_id"])["users"][0]
    email = info["email"]
    verified = info['emailVerified']
    if verified:
      return redirect("/")
    return render_template("verification-page.html", email=email)
  else:
    auth.send_email_verification(session["user_id"])
    return redirect("/email-verification")

@app.route("/contract", methods=["GET", "POST"])
@login_required
@email_verification_required
def contract():
  if request.method == "GET":
    if contractSigned():
      return redirect("/")
    if lookup(session.get("user_id")) == "students":
      return render_template("student-contract.html")
    return render_template("tutor-contract.html")
  else:
    eSig = request.form.get("eSig")
    pictureUse = request.form["pictureUse"] == "Yes"
    pictureSig = request.form.get("pictureSig")

    if not eSig or not pictureSig or not request.form["pictureUse"]:
      flash("Please fill out all items on the contract.")
      return redirect("/contract")

    data = {
      'contractSigned': True,
      'contractInfo': {
        "eSig": eSig,
        "pictureUse": pictureUse,
        "pictureSig": pictureSig,
        "date": str(date.today())
      }
    }

    name = auth.get_account_info(session["user_id"])["users"][0]["displayName"]
    accountType = lookup(session.get("user_id"))

    db.child("users").child(accountType).child(name).update(data)
    return redirect("/")

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
    return render_template("register-tutor.html", chapters=chapters)
  else:
    firstName = request.form.get("fname")
    lastName = request.form.get("lname")
    email = request.form.get("email")
    number = request.form.get("phone")
    chapter = request.form.get("chapter")
    password = request.form.get("password")
    confirmation = request.form.get("confirmation")

    if not firstName or not lastName or not email or not number or not chapter or not password or not confirmation:
      flash("Please provide all credentials.")
      return redirect("/register-tutor")
    if chapter not in chapters:
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
    session["user_id"] = user["idToken"]
    data = {
      'email': email,
      'phoneNumber': phonenumbers.format_number(phonenumbers.parse(number, "US"), phonenumbers.PhoneNumberFormat.NATIONAL),
      'accountType': "tutor",
      'chapter': chapter,
      'contractSigned': False,
    }
    db.child("users").child("tutors").child(name).set(data)
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
    password = request.form.get("password")
    confirmation = request.form.get("confirmation")

    if not firstName or not lastName or not parentFirstName or not parentLastName or not email or not number or not password or not confirmation:
      flash("Please provide all credentials.")
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
    session["user_id"] = user["idToken"]
    data = {
      'email': email,
      'parentName': parentFirstName + " " + parentLastName,
      'phoneNumber': phonenumbers.format_number(phonenumbers.parse(number, "US"), phonenumbers.PhoneNumberFormat.NATIONAL),
      'accountType': "student",
      'contractSigned': False,
    }
    db.child("users").child("students").child(name).set(data)
    return redirect("/email-verification")


"""
Chat App TODO:
1. html template displays messages and auto-updates (gets them from server-side)
2. POST gets messages from template form, stores in realtime database, goes back to GET request to display
3. Figure out how to link multiple users but limit which users to talk to.
"""