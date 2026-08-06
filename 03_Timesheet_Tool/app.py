import io
import os
import requests
from flask import Flask, render_template, request, jsonify, send_file
from timesheet import check_env, fetch_tickets, export_to_excel, export_year_to_excel, get_current_user, JIRA_BASE_URL

app = Flask(__name__)


def get_auth(data):
    return (data["email"], data["apiToken"])


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/connect", methods=["POST"])
def connect():
    data = request.get_json()
    auth = get_auth(data)
    try:
        user = get_current_user(JIRA_BASE_URL, auth)
        return jsonify({
            "ok": True,
            "name": user.get("displayName"),
            "email": user.get("emailAddress"),
        })
    except requests.HTTPError as e:
        return jsonify({"ok": False, "error": f"Invalid credentials ({e.response.status_code})"}), 200


@app.route("/api/generate", methods=["POST"])
def generate():
    data  = request.get_json()
    auth  = get_auth(data)
    month = int(data["month"])
    year  = int(data["year"])
    rows, errors = fetch_tickets(month, year, JIRA_BASE_URL, auth)
    return jsonify({"rows": rows, "errors": errors, "jiraBaseUrl": JIRA_BASE_URL})


@app.route("/api/export", methods=["POST"])
def export():
    data  = request.get_json()
    month = int(data["month"])
    year  = int(data["year"])
    rows  = data["rows"]
    buf, filename = export_to_excel(rows, month, year)
    return send_file(buf, as_attachment=True, download_name=filename,
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.route("/api/generate-year", methods=["POST"])
def generate_year():
    data = request.get_json()
    auth = get_auth(data)
    year = int(data["year"])
    month_data = {}
    all_errors = []
    for month in range(1, 13):
        try:
            rows, errors = fetch_tickets(month, year, JIRA_BASE_URL, auth)
            if rows:
                month_data[month] = rows
            all_errors.extend(errors)
        except Exception as e:
            all_errors.append(f"Month {month}: {e}")
    return jsonify({"monthData": month_data, "errors": all_errors, "year": year, "jiraBaseUrl": JIRA_BASE_URL})


@app.route("/api/export-year", methods=["POST"])
def export_year():
    data       = request.get_json()
    year       = int(data["year"])
    month_data = {int(k): v for k, v in data["monthData"].items()}
    buf, filename = export_year_to_excel(month_data, year)
    return send_file(buf, as_attachment=True, download_name=filename,
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


if __name__ == "__main__":
    check_env()
    app.run(debug=True, port=5000)
