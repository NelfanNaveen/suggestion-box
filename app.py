from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.utils import secure_filename
import sqlite3
import os
import uuid
from datetime import datetime

app = Flask(__name__)
app.secret_key = "change-this-key"
DB = "database.db"
UPLOAD_FOLDER = os.path.join("static", "uploads")

CATEGORIES = ["Roads", "Water Supply", "Garbage", "Streetlights", "Drainage", "Parks", "Other"]
WARDS = ["Ward 1", "Ward 2", "Ward 3", "Ward 4", "Ward 5"]
STATUS_FLOW = ["Received", "Under Review", "In Progress", "Resolved"]


def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS suggestions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tracking_id TEXT UNIQUE,
            name TEXT,
            phone TEXT,
            ward TEXT,
            category TEXT,
            title TEXT,
            description TEXT,
            photo_path TEXT,
            status TEXT DEFAULT 'Received',
            admin_remark TEXT,
            upvotes INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS admins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password TEXT
        )
    """)
    conn.execute("INSERT OR IGNORE INTO admins (username, password) VALUES ('admin', 'admin123')")
    conn.commit()
    conn.close()


# ---------------- Citizen pages ----------------

@app.route("/")
def home():
    conn = get_db()
    stats = {
        "total": conn.execute("SELECT COUNT(*) FROM suggestions").fetchone()[0],
        "resolved": conn.execute("SELECT COUNT(*) FROM suggestions WHERE status='Resolved'").fetchone()[0],
        "progress": conn.execute("SELECT COUNT(*) FROM suggestions WHERE status IN ('Under Review','In Progress')").fetchone()[0],
    }
    conn.close()
    return render_template("index.html", stats=stats)


@app.route("/submit", methods=["GET", "POST"])
def submit():
    if request.method == "POST":
        name = request.form.get("name", "").strip() or "Anonymous"
        phone = request.form.get("phone", "").strip()
        ward = request.form.get("ward")
        category = request.form.get("category")
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()

        photo_path = None
        photo = request.files.get("photo")
        if photo and photo.filename:
            filename = uuid.uuid4().hex[:8] + "_" + secure_filename(photo.filename)
            photo.save(os.path.join(UPLOAD_FOLDER, filename))
            photo_path = "uploads/" + filename

        conn = get_db()
        cur = conn.execute(
            """INSERT INTO suggestions (name, phone, ward, category, title, description, photo_path)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (name, phone, ward, category, title, description, photo_path),
        )
        new_id = cur.lastrowid
        tracking_id = f"SUG-{datetime.now().year}-{new_id:04d}"
        conn.execute("UPDATE suggestions SET tracking_id = ? WHERE id = ?", (tracking_id, new_id))
        conn.commit()
        conn.close()
        return redirect(url_for("success", tracking_id=tracking_id))

    return render_template("submit.html", categories=CATEGORIES, wards=WARDS)


@app.route("/success/<tracking_id>")
def success(tracking_id):
    return render_template("success.html", tracking_id=tracking_id)


@app.route("/track")
def track():
    tid = request.args.get("id", "").strip().upper()
    suggestion = None
    not_found = False
    if tid:
        conn = get_db()
        suggestion = conn.execute("SELECT * FROM suggestions WHERE tracking_id = ?", (tid,)).fetchone()
        conn.close()
        not_found = suggestion is None
    return render_template("track.html", tid=tid, s=suggestion,
                           not_found=not_found, status_flow=STATUS_FLOW)


@app.route("/suggestions")
def suggestions():
    category = request.args.get("category", "")
    ward = request.args.get("ward", "")
    sort = request.args.get("sort", "latest")

    query = "SELECT * FROM suggestions WHERE 1=1"
    params = []
    if category:
        query += " AND category = ?"
        params.append(category)
    if ward:
        query += " AND ward = ?"
        params.append(ward)
    query += " ORDER BY upvotes DESC, id DESC" if sort == "popular" else " ORDER BY id DESC"

    conn = get_db()
    rows = conn.execute(query, params).fetchall()
    conn.close()
    voted = session.get("voted", [])
    return render_template("suggestions.html", rows=rows, categories=CATEGORIES, wards=WARDS,
                           sel_cat=category, sel_ward=ward, sort=sort, voted=voted)


@app.route("/upvote/<int:sid>", methods=["POST"])
def upvote(sid):
    voted = session.get("voted", [])
    if sid not in voted:
        conn = get_db()
        conn.execute("UPDATE suggestions SET upvotes = upvotes + 1 WHERE id = ?", (sid,))
        conn.commit()
        conn.close()
        voted.append(sid)
        session["voted"] = voted
    return redirect(request.referrer or url_for("suggestions"))


def seed_demo_data():
    conn = get_db()
    if conn.execute("SELECT COUNT(*) FROM suggestions").fetchone()[0] == 0:
        year = datetime.now().year
        samples = [
            ("Ravi Kumar", "Ward 1", "Streetlights", "Streetlights not working on Main Road",
             "Five streetlights between the bus stand and the school have not worked for two weeks. It is unsafe at night.", "In Progress", 24),
            ("Anonymous", "Ward 2", "Garbage", "Garbage not collected near market",
             "Garbage has been piling up near the vegetable market for 4 days and is causing a bad smell.", "Under Review", 18),
            ("Priya S", "Ward 3", "Roads", "Large pothole near Government Hospital",
             "A big pothole in front of the hospital gate is dangerous for ambulances and two-wheelers.", "Resolved", 31),
            ("Mohan R", "Ward 4", "Water Supply", "Irregular water supply in 5th Cross",
             "Water comes only once in three days and the pressure is very low.", "Received", 9),
            ("Anonymous", "Ward 5", "Parks", "Add benches and lights in children's park",
             "The park has no benches for elders and no lighting after 6 PM. Please add both.", "Received", 12),
        ]
        for i, (name, ward, cat, title, desc, status, up) in enumerate(samples, start=1):
            conn.execute(
                """INSERT INTO suggestions (tracking_id, name, ward, category, title, description, status, upvotes)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (f"SUG-{year}-{i:04d}", name, ward, cat, title, desc, status, up),
            )
        conn.execute("UPDATE suggestions SET admin_remark = ? WHERE status = 'Resolved'",
                     ("Pothole filled and road resurfaced by the Engineering Department.",))
        conn.commit()
    conn.close()


# runs on PC and on the server
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
init_db()
seed_demo_data()

if __name__ == "__main__":
    app.run(debug=True)