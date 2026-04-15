from os import environ

from asgiref.wsgi import WsgiToAsgi
from flask import Flask, abort, render_template, request

from .logconf import setup_logging
from .printer import print_name
from .sanitize import sanitize_label_text

setup_logging()

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = int(environ.get("NAMETAG_MAX_REQUEST_BYTES", "4096"))


@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        name = request.form.get("name", "")
        second_line = request.form.get("second_line", "")

        try:
            name, second_line = sanitize_label_text(name, second_line)
        except ValueError as exc:
            abort(400, description=str(exc))

        print_name(name, second_line)

        return render_template("printing.html")

    return render_template("index.html")


# Create ASGI app for compatibility with Uvicorn
asgi_app = WsgiToAsgi(app)

if __name__ == "__main__":
    debug_enabled = environ.get("FLASK_DEBUG", "").lower() in {"1", "true", "yes"}
    app.run(debug=debug_enabled)
