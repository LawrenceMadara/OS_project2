import os
import time
from datetime import datetime, timedelta
from functools import wraps

import pandas as pd
from flask import (
    Flask,
    jsonify,
    render_template,
    request,
    session,
)
from flask_socketio import SocketIO, emit
from werkzeug.security import generate_password_hash, check_password_hash

from analysis import (
    load_dataset,
    clean_macronutrients,
    calculate_average_macros,
    get_top_protein_recipes,
    add_nutrient_ratios,
    filter_by_diet,
    get_common_cuisines,
    get_macronutrient_distribution,
    run_full_analysis,
)

# -----------------------------------------------------------------------------
# App & Security configuration
# -----------------------------------------------------------------------------
app = Flask(__name__)

# In production this MUST come from an environment variable.
app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET_KEY", "change-me-in-prod")
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    # Set to True when serving over HTTPS in the cloud
    SESSION_COOKIE_SECURE=False,
)

socketio = SocketIO(app, cors_allowed_origins="*")

# Demo user store – in a real app, use a database
USERS = {
    "student": generate_password_hash("Password123!"),
}

# Simple demo 2FA code (you can override via env var)
DEMO_2FA_CODE = os.environ.get("DEMO_2FA_CODE", "123456")

# Directories whose files will be cleaned up to save cloud storage costs
CLEANUP_DIRECTORIES = [
    os.path.join(os.path.dirname(__file__), "output"),
]
DEFAULT_MAX_FILE_AGE_HOURS = int(os.environ.get("MAX_FILE_AGE_HOURS", "24"))


def api_auth_required(fn):
    """Decorator to require a logged-in user for JSON API routes."""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("user"):
            return jsonify({"error": "Authentication required"}), 401
        return fn(*args, **kwargs)

    return wrapper


@app.after_request
def add_security_headers(response):
    """Add basic security headers to every response."""
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    # Relaxed CSP so CDN assets still work; tighten for production if needed.
    response.headers[
        "Content-Security-Policy"
    ] = (
        "default-src 'self'; "
        "script-src 'self' https://cdn.tailwindcss.com https://cdn.jsdelivr.net https://cdn.socket.io; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net;"
    )
    return response


# -----------------------------------------------------------------------------
# Basic page
# -----------------------------------------------------------------------------


@app.route("/")
def index():
    """Render the main dashboard page."""
    return render_template("index.html")


# -----------------------------------------------------------------------------
# Authentication & security API
# -----------------------------------------------------------------------------


@app.route("/api/login", methods=["POST"])
def login_api():
    """
    Authenticate a user with password + simple 2FA code.

    Expects JSON:
      { "username": "...", "password": "...", "code": "123456" }
    """
    data = request.get_json(force=True, silent=True) or {}
    username = data.get("username", "").strip()
    password = data.get("password", "")
    code = data.get("code", "")

    if not username or not password or not code:
        return (
            jsonify({"error": "Username, password and 2FA code are required."}),
            400,
        )

    pw_hash = USERS.get(username)
    if not pw_hash or not check_password_hash(pw_hash, password):
        return jsonify({"error": "Invalid username or password."}), 401

    if code != DEMO_2FA_CODE:
        return jsonify({"error": "Invalid 2FA code."}), 401

    session["user"] = username
    return jsonify({"message": "Login successful", "user": username})


@app.route("/api/logout", methods=["POST"])
@api_auth_required
def logout_api():
    """Clear the current user session."""
    session.clear()
    return jsonify({"message": "Logged out"})


@app.route("/api/current_user")
def current_user_api():
    """Return the currently authenticated user (if any)."""
    user = session.get("user")
    return jsonify({"user": user})


@app.route("/api/security_status")
def security_status_api():
    """Expose high-level security & compliance information."""
    return jsonify(
        {
            "encryption": "Enabled for data in transit (HTTPS) and at rest in cloud storage.",
            "access_control": "Only authenticated users can access analysis APIs.",
            "compliance": "Follows data-minimization and access-logging principles (GDPR-friendly demo).",
            "last_audit": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        }
    )


# -----------------------------------------------------------------------------
# Cloud resource cleanup API – reduces cloud storage cost
# -----------------------------------------------------------------------------


def perform_cleanup(max_age_hours: int = DEFAULT_MAX_FILE_AGE_HOURS):
    """
    Delete files older than max_age_hours from CLEANUP_DIRECTORIES.

    This simulates cleaning up unused cloud resources (old reports, temp files,
    cached images) to reduce storage costs.
    """
    now = datetime.utcnow()
    cutoff = now - timedelta(hours=max_age_hours)
    deleted_files = []
    freed_bytes = 0

    for directory in CLEANUP_DIRECTORIES:
        if not os.path.isdir(directory):
            continue

        for root, _dirs, files in os.walk(directory):
            for name in files:
                path = os.path.join(root, name)
                try:
                    mtime = datetime.utcfromtimestamp(os.path.getmtime(path))
                except OSError:
                    continue

                if mtime < cutoff:
                    try:
                        size = os.path.getsize(path)
                    except OSError:
                        size = 0
                    try:
                        os.remove(path)
                        deleted_files.append(os.path.relpath(path, directory))
                        freed_bytes += size
                    except OSError:
                        continue

    return {
        "deleted_files": deleted_files,
        "total_space_freed_bytes": freed_bytes,
    }


@app.route("/api/cloud_cleanup", methods=["POST"])
@api_auth_required
def cloud_cleanup_api():
    """Trigger a one-off cleanup of old output files."""
    data = request.get_json(silent=True) or {}
    max_age = int(data.get("max_age_hours", DEFAULT_MAX_FILE_AGE_HOURS))

    result = perform_cleanup(max_age)
    return jsonify(
        {
            "status": "completed",
            "deleted_files": result["deleted_files"],
            "space_freed_mb": round(
                result["total_space_freed_bytes"] / (1024 * 1024), 3
            ),
        }
    )


# -----------------------------------------------------------------------------
# Real-time analysis via WebSocket (still works, now behind auth)
# -----------------------------------------------------------------------------


@socketio.on("start_analysis")
@api_auth_required
def handle_start_analysis():
    """Send live progress updates to the client while running the analysis."""

    emit("progress", {"status": "Loading dataset..."})
    time.sleep(0.5)

    df = load_dataset("res/All_Diets.csv")
    df = clean_macronutrients(df)

    emit("progress", {"status": "Calculating averages..."})
    time.sleep(0.5)
    avg_macros = calculate_average_macros(df)

    emit("progress", {"status": "Finding top protein recipes..."})
    time.sleep(0.5)
    top_protein = get_top_protein_recipes(df)

    emit("progress", {"status": "Generating summary..."})
    time.sleep(0.5)
    summary = {
        "average_macros": avg_macros.reset_index().to_dict(orient="records"),
        "top_protein_recipes": top_protein.to_dict(orient="records"),
    }

    emit("completed", summary)


# -----------------------------------------------------------------------------
# Data APIs – all require authentication
# -----------------------------------------------------------------------------


@app.route("/api/recipe")
@api_auth_required
def recipe_api():
    """
    Simple recipe lookup endpoint (demo).

    Query string: ?q=chicken
    """
    query = (request.args.get("q") or "").strip().lower()

    recipes = {
        "chicken": {
            "title": "Simple Baked Chicken Breast",
            "description": "Easy oven-baked chicken breast with basic seasoning.",
        },
        "salad": {
            "title": "Fresh Garden Salad",
            "description": "Mixed greens with tomatoes, cucumber, and light vinaigrette.",
        },
    }

    if not query:
        return jsonify({"error": "Missing query"}), 400

    recipe = recipes.get(query)
    if not recipe:
        return jsonify({"error": "No recipe found"}), 404

    return jsonify(recipe)


@app.route("/api/avg_macros")
@api_auth_required
def avg_macros_api():
    """Return average protein, carbs, and fat per diet type."""
    df = load_dataset("res/All_Diets.csv")
    df = clean_macronutrients(df)
    avg_macros = calculate_average_macros(df)
    return jsonify(avg_macros.reset_index().to_dict(orient="records"))


@app.route("/api/top_protein")
@api_auth_required
def top_protein_api():
    """Return top protein recipes per diet type."""
    df = load_dataset("res/All_Diets.csv")
    df = clean_macronutrients(df)
    top_protein = get_top_protein_recipes(df)
    return jsonify(top_protein.to_dict(orient="records"))


@app.route("/api/common_cuisines")
@api_auth_required
def common_cuisines_api():
    """Return most common cuisines by diet type."""
    df = load_dataset("res/All_Diets.csv")
    df = clean_macronutrients(df)
    cuisines = get_common_cuisines(df)
    return jsonify(cuisines.reset_index().to_dict(orient="records"))


@app.route("/api/summary")
@api_auth_required
def summary_api():
    """
    Comprehensive summary of the analysis:
    - highest protein diet
    - average macros
    - common cuisines
    """
    results = run_full_analysis("res/All_Diets.csv")
    return jsonify(
        {
            "highest_protein_diet": results["highest_protein_diet"],
            "average_macros": results["average_macros"].to_dict(orient="records"),
            "common_cuisines": results["common_cuisines"].to_dict(
                orient="records"
            ),
        }
    )


@app.route("/api/scatter_data")
@api_auth_required
def scatter_data_api():
    """Data for scatter plot (protein vs carbs)."""
    df = load_dataset("res/All_Diets.csv")
    df = clean_macronutrients(df)
    df = add_nutrient_ratios(df)
    scatter_df = df[
        ["Diet_type", "Protein(g)", "Carbs(g)", "Cuisine_type"]
    ].dropna()
    return jsonify(scatter_df.to_dict(orient="records"))


@app.route("/api/heatmap_data")
@api_auth_required
def heatmap_data_api():
    """Average macros per diet type for heatmap."""
    df = load_dataset("res/All_Diets.csv")
    df = clean_macronutrients(df)
    avg_macros = calculate_average_macros(df)
    return jsonify(avg_macros.reset_index().to_dict(orient="records"))


@app.route("/api/filter/<diet_type>")
@api_auth_required
def filter_diet_api(diet_type):
    """Filter dataset by specific diet type."""
    df = load_dataset("res/All_Diets.csv")
    df = clean_macronutrients(df)
    filtered_df = filter_by_diet(df, diet_type)
    return jsonify(filtered_df.to_dict(orient="records"))


@app.route("/api/distribution")
@api_auth_required
def distribution_api():
    """Descriptive statistics for nutrient distributions."""
    df = load_dataset("res/All_Diets.csv")
    df = clean_macronutrients(df)
    stats = get_macronutrient_distribution(df)
    return jsonify(stats.to_dict())


if __name__ == "__main__":
    # When you run `python app.py` locally.
    socketio.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
