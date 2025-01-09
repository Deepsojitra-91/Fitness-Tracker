from flask import Flask, render_template, request, redirect, url_for, send_file
from pymongo import MongoClient
from bson.objectid import ObjectId
import matplotlib.pyplot as plt
import io
import base64
from datetime import datetime, timedelta
import pandas as pd
from flask_apscheduler import APScheduler
from flask import session
from flask_session import Session
import pytz

app = Flask(__name__)
scheduler = APScheduler()


def daily_reminder_task():
    with app.app_context():
        check_reminders()


scheduler.add_job(id='daily_reminder', func=daily_reminder_task, trigger='interval', days=1)
scheduler.start()

client = MongoClient("mongodb://localhost:27017/")
db = client["fitness_tracker"]
exercise_logs = db["exercise_logs"]
fitness_goals = db["fitness_goals"]


@app.route("/")
def index():
    exercises = list(exercise_logs.find())
    goals = fitness_goals.find_one()
    return render_template("index.html", exercises=exercises, goals=goals)


@app.route("/add", methods=["GET", "POST"])
def add_exercise():
    if request.method == "POST":
        exercise = {
            "name": request.form["name"],
            "reps": request.form["reps"],
            "sets": request.form["sets"],
            "weight": request.form["weight"]
        }
        exercise_logs.insert_one(exercise)
        return redirect(url_for("index"))
    return render_template("add_exercise.html")


@app.route("/edit/<exercise_id>", methods=["GET", "POST"])
def edit_exercise(exercise_id):
    exercise = exercise_logs.find_one({"_id": ObjectId(exercise_id)})
    if request.method == "POST":
        updated_data = {
            "name": request.form["name"],
            "reps": request.form["reps"],
            "sets": request.form["sets"],
            "weight": request.form["weight"]
        }
        exercise_logs.update_one({"_id": ObjectId(exercise_id)}, {"$set": updated_data})
        return redirect(url_for("index"))
    return render_template("edit_exercise.html", exercise=exercise)


@app.route("/delete/<exercise_id>", methods=["POST"])
def delete_exercise(exercise_id):
    exercise_logs.delete_one({"_id": ObjectId(exercise_id)})
    return redirect(url_for("index"))


@app.route("/goals", methods=["GET", "POST"])
def set_goals():
    goals = fitness_goals.find_one()
    if request.method == "POST":
        goal_data = {
            "target_weight": float(request.form["target_weight"]),
            "target_reps": int(request.form["target_reps"])
        }
        if goals:
            fitness_goals.update_one({}, {"$set": goal_data})
        else:
            fitness_goals.insert_one(goal_data)
        return redirect(url_for("index"))
    return render_template("set_goals.html", goals=goals)


@app.route('/add_fitness_goals', methods=['GET', 'POST'])
def add_fitness_goals():
    if request.method == 'POST':
        cardio_targets = {
            "target_distance": float(request.form.get("target_distance", 0)),
            "target_time": int(request.form.get("target_time", 0)),
            "target_calories_burned": int(request.form.get("target_calories_burned", 0))
        }

        strength_targets = {
            "target_weight_exercise": float(request.form.get("target_weight_exercise", 0)),
            "target_reps_per_week": int(request.form.get("target_reps_per_week", 0)),
            "target_sets_per_exercise": int(request.form.get("target_sets_per_exercise", 0))
        }

        fitness_goals.insert_one({
            "user_id": "user1",
            "cardio_targets": cardio_targets,
            "strength_targets": strength_targets,
            "date_created": datetime.now()
        })

        return redirect(url_for('view_fitness_goals'))

    return render_template('add_fitness_goals.html')


@app.route('/view_fitness_goals')
def view_fitness_goals():
    goals = list(fitness_goals.find({"user_id": "user1"}).sort("date_created", -1))
    return render_template('view_fitness_goals.html', goals=goals)


@app.route('/delete_fitness_goal/<goal_id>', methods=['POST'])
def delete_fitness_goal(goal_id):
    fitness_goals.delete_one({"_id": ObjectId(goal_id)})
    return redirect(url_for('view_fitness_goals'))


@app.route('/check_reminders', methods=['GET'])
def check_reminders():
    current_time = datetime.now(pytz.utc)
    last_check_time = session.get("last_reminder_check")

    if last_check_time:
        last_check_time = datetime.fromisoformat(last_check_time)
        time_difference = current_time - last_check_time
        if time_difference < timedelta(hours=6):
            return redirect(url_for("show_notifications"))

    session["last_reminder_check"] = current_time.isoformat()

    goals = fitness_goals.find({"user_id": "user1"})
    reminders = []

    for goal in goals:
        cardio = goal.get("cardio_targets", {})
        strength = goal.get("strength_targets", {})

        if cardio:
            if cardio.get("target_distance", 0) > 0:
                reminders.append({"message": f"Unmet cardio target: Run {cardio['target_distance']} km.", "time": current_time})
            if cardio.get("target_time", 0) > 0:
                reminders.append({"message": f"Unmet cardio target: Complete within {cardio['target_time']} minutes.", "time": current_time})

        if strength:
            if strength.get("target_reps_per_week", 0) > 0:
                reminders.append({"message": f"Unmet strength target: {strength['target_reps_per_week']} reps.", "time": current_time})

    session["reminders"] = [{"message": r["message"], "time": r["time"].isoformat()} for r in reminders]

    return redirect(url_for("show_notifications"))


@app.route('/show_notifications', methods=['GET'])
def show_notifications():
    reminders = session.get("reminders", [])

    for reminder in reminders:
        reminder["time"] = datetime.fromisoformat(reminder["time"])
    return render_template('notifications.html', reminders=reminders)


@app.route('/export_goals', methods=['GET'])
def export_goals():
    goals = fitness_goals.find({"user_id": "user1"})
    data = []

    for goal in goals:
        cardio = goal.get("cardio_targets", {})
        strength = goal.get("strength_targets", {})
        data.append({
            "Date Created": goal.get("date_created", "").strftime("%Y-%m-%d"),
            "Target Distance (km)": cardio.get("target_distance", 0),
            "Target Time (mins)": cardio.get("target_time", 0),
            "Target Calories Burned": cardio.get("target_calories_burned", 0),
            "Target Weight (kg)": strength.get("target_weight_exercise", 0),
            "Target Reps Per Week": strength.get("target_reps_per_week", 0),
            "Target Sets Per Exercise": strength.get("target_sets_per_exercise", 0),
        })

    df = pd.DataFrame(data)
    file_path = "fitness_goals.xlsx"
    df.to_excel(file_path, index=False)
    return send_file(file_path, as_attachment=True)


if __name__ == "__main__":
    app.run(debug=True)
