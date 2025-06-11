from flask import Flask, send_from_directory, render_template_string
from pathlib import Path

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
    app.run(host="0.0.0.0", port=5000)
