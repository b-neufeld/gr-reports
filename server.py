from flask import Flask, send_from_directory, render_template_string
from pathlib import Path
import threading
import time
import subprocess

app = Flask(__name__)
COLLAGE_DIR = Path("collages")

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Goodreads Collages</title>
    <style>
        body {
            font-family: sans-serif;
            background: #111;
            color: #eee;
            text-align: center;
        }
        img {
            width: 200px;
            margin: 10px;
            border: 2px solid #444;
        }
        a {
            text-decoration: none;
            color: #ccc;
        }
    </style>
</head>
<body>
    <h1>📚 Goodreads Collages</h1>
    {% for filename in files %}
        <div>
            <a href="/collages/{{ filename }}" target="_blank">
                <img src="/collages/{{ filename }}" alt="{{ filename }}">
            </a>
        </div>
    {% endfor %}
</body>
</html>
"""

def run_daily_task():
    while True:
        print("Running app.py task...")
        subprocess.run(["python", "app.py"]) # run Goodreads collection & image gen script
        time.sleep(24 * 60 * 60)  # sleep 24 hours before refreshing collages

@app.route("/")
def index():
    files = sorted(
        [f.name for f in COLLAGE_DIR.glob("*.jpg")],
        reverse=True  # newest first
    )
    return render_template_string(HTML_TEMPLATE, files=files)

@app.route("/collages/<path:filename>")
def collage_file(filename):
    return send_from_directory(COLLAGE_DIR, filename)

if __name__ == "__main__":
    # Start the background thread
    threading.Thread(target=run_daily_task, daemon=True).start()
    # Start the Flask app
    app.run(host="0.0.0.0", port=5000)
