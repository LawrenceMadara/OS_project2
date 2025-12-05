import os
import time
import random
import string
from flask import Flask, jsonify, render_template, redirect, url_for, session, request
from flask_socketio import SocketIO, emit
from authlib.integrations.flask_client import OAuth
from dotenv import load_dotenv
from analysis import run_full_analysis
from flask_mail import Mail, Message

# Load environment variables
load_dotenv()

# -------------------------------------------------------------------
# Helper
# -------------------------------------------------------------------
def generate_6_char_code(length=6):
    chars = string.ascii_uppercase + string.digits  # A-Z and 0-9
    return ''.join(random.choices(chars, k=length))

# -------------------------------------------------------------------
# Flask setup
# -------------------------------------------------------------------
app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET_KEY", "dev-secret")
socketio = SocketIO(app, cors_allowed_origins="*", manage_session=False)

# Flask-Mail setup
app.config.update(
    MAIL_SERVER=os.environ.get("MAIL_SERVER"),
    MAIL_PORT=int(os.environ.get("MAIL_PORT", 587)),
    MAIL_USE_TLS=os.environ.get("MAIL_USE_TLS", "True") == "True",
    MAIL_USERNAME=os.environ.get("MAIL_USERNAME"),
    MAIL_PASSWORD=os.environ.get("MAIL_PASSWORD"),
    MAIL_DEFAULT_SENDER=os.environ.get("MAIL_DEFAULT_SENDER"),
)
mail = Mail(app)

# -------------------------------------------------------------------
# OAuth setup
# -------------------------------------------------------------------
app.config.update(
    GOOGLE_CLIENT_ID=os.environ.get("GOOGLE_CLIENT_ID"),
    GOOGLE_CLIENT_SECRET=os.environ.get("GOOGLE_CLIENT_SECRET"),
    GITHUB_CLIENT_ID=os.environ.get("GITHUB_CLIENT_ID"),
    GITHUB_CLIENT_SECRET=os.environ.get("GITHUB_CLIENT_SECRET"),
)
oauth = OAuth(app)

# Google
oauth.register(
    name="google",
    client_id=app.config["GOOGLE_CLIENT_ID"],
    client_secret=app.config["GOOGLE_CLIENT_SECRET"],
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)

# GitHub
oauth.register(
    name="github",
    client_id=app.config["GITHUB_CLIENT_ID"],
    client_secret=app.config["GITHUB_CLIENT_SECRET"],
    access_token_url="https://github.com/login/oauth/access_token",
    authorize_url="https://github.com/login/oauth/authorize",
    api_base_url="https://api.github.com/",
    client_kwargs={"scope": "read:user user:email"},
)

# -------------------------------------------------------------------
# Routes
# -------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")

SUPPORTED_PROVIDERS = ("google", "github")

@app.route("/login/<provider>")
def login(provider):
    """Redirects the user to the provider's OAuth site."""
    if provider not in SUPPORTED_PROVIDERS:
        return "Unknown provider", 404
    redirect_uri = url_for("auth_callback", provider=provider, _external=True)
    return oauth.create_client(provider).authorize_redirect(redirect_uri)

@app.route("/auth/callback/<provider>")
def auth_callback(provider):
    """Handles OAuth callback, stores session, and sends 2FA email."""
    if provider not in SUPPORTED_PROVIDERS:
        return "Unknown provider", 404

    client = oauth.create_client(provider)
    token = client.authorize_access_token()

    # Save user info
    if provider == "google":
        userinfo = client.userinfo()
        session["user"] = {
            "provider": "Google",
            "id": userinfo.get("sub"),
            "name": userinfo.get("name"),
            "email": userinfo.get("email"),
            "picture": userinfo.get("picture"),
        }
    else:  # GitHub
        gh_user = client.get("user").json()
        email = gh_user.get("email")
        if not email:
            emails = client.get("user/emails").json()
            primary = next((e["email"] for e in emails if e.get("primary")), None)
            email = primary
        session["user"] = {
            "provider": "GitHub",
            "id": gh_user.get("id"),
            "name": gh_user.get("name") or gh_user.get("login"),
            "email": email,
            "picture": gh_user.get("avatar_url"),
        }

    # Automatically generate and send 2FA
    user = session["user"]
    try:
        code = generate_6_char_code()
        session["2fa_code"] = code
        session["2fa_expiry"] = time.time() + 300  # 5 minutes

        msg = Message(
            "Your 2FA Code",
            recipients=[user["email"]],
        )
        msg.body = f"Hello {user['name']},\n\nYour 2FA code is: {code}\nIt expires in 5 minutes."
        mail.send(msg)
        session["2fa_sent"] = True
        print("2FA email sent to:", user["email"])
    except Exception as e:
        print("Failed to send 2FA email:", e)
        session["2fa_sent"] = False

    return redirect(url_for("index"))

@app.route("/2fa/verify", methods=["POST"])
def verify_2fa():
    user = session.get("user")
    if not user:
        return jsonify({"error": "Not logged in"}), 401

    data = request.get_json()
    code = data.get("code", "").strip().upper()

    if session.get("2fa_code") == code and time.time() < session.get("2fa_expiry", 0):
        session["2fa_verified"] = True
        session.pop("2fa_code", None)
        session.pop("2fa_expiry", None)
        return jsonify({"status": "2FA verified"})

    return jsonify({"error": "Invalid or expired 2FA code"}), 400

@app.route("/2fa/status")
def two_fa_status():
    """Returns whether a 2FA email was sent, then clears the flag."""
    status = session.pop("2fa_sent", False)
    return jsonify({"2fa_sent": status})

@app.route("/auth/status")
def auth_status():
    user = session.get("user")
    if not user:
        return jsonify({"authenticated": False})
    return jsonify({"authenticated": True, **user})

@app.route("/cleanup", methods=["POST"])
def cleanup_resources():
    user = session.get("user")
    if not user or not session.get("2fa_verified"):
        return jsonify({"error": "Unauthorized"}), 401

    # Simulate cleaning up cloud resources
    print("Simulating cloud resource cleanup...")
    resources = ["VM instances", "Storage buckets", "Databases", "Load balancers"]
    for r in resources:
        print(f"Deleting {r}...")
        time.sleep(0.5)  # simulate time it takes to delete

    print("All simulated cloud resources deleted.")
    return jsonify({"status": "Simulated cloud resources cleaned up successfully!"})


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))

# -------------------------------------------------------------------
# Socket.IO: Live Analysis
# -------------------------------------------------------------------
@socketio.on("start_analysis")
def handle_start_analysis():
    emit("progress", {"status": "Running full analysis..."})
    time.sleep(1)

    summary = run_full_analysis("res/All_Diets.csv")
    emit(
        "complete",
        {
            "message": "Analysis finished!",
            "summary": {
                "highest_protein_diet": summary["highest_protein_diet"],
                "average_macros": summary["average_macros"].to_dict(orient="records"),
                "common_cuisines": summary["common_cuisines"].to_dict(orient="records"),
                "top_protein_recipes": summary["top_protein_recipes"].to_dict(orient="records"),
            },
        },
    )

# -------------------------------------------------------------------
# API endpoints
# -------------------------------------------------------------------
@app.route("/api/avg_macros")
def api_avg_macros():
    summary = run_full_analysis("res/All_Diets.csv")
    avg_macros = summary["average_macros"]
    return jsonify(avg_macros.to_dict(orient="records"))

@app.route("/api/top_protein")
def api_top_protein():
    summary = run_full_analysis("res/All_Diets.csv")
    return jsonify(summary["top_protein_recipes"].to_dict(orient="records"))

# -------------------------------------------------------------------
# Recipe Lookup
# -------------------------------------------------------------------
RECIPES = {
    "chicken": {
        "title": "Simple Baked Chicken Breast",
        "description": "Easy oven-baked chicken.",
        "ingredients": ["2 chicken breasts", "1 tbsp olive oil"],
        "steps": ["Preheat oven", "Bake chicken"],
    },
    "oats": {
        "title": "Basic Oatmeal Breakfast Bowl",
        "description": "Warm oats with fruit.",
        "ingredients": ["1/2 cup oats", "1 cup water"],
        "steps": ["Boil oats", "Serve with toppings"],
    },
    "salad": {
        "title": "Simple Mixed Green Salad",
        "description": "Quick salad with dressing.",
        "ingredients": ["2 cups greens", "1 tbsp olive oil"],
        "steps": ["Mix ingredients", "Serve immediately"],
    },
}

@app.route("/api/recipe")
def get_recipe():
    query = request.args.get("q", "").strip().lower()
    if not query:
        return jsonify({"found": False, "message": "Please type a food name."})
    for keyword, recipe in RECIPES.items():
        if keyword in query:
            return jsonify({"found": True, "recipe": recipe})
    return jsonify({"found": False, "message": "No recipe found for that food."})

@app.route("/favicon.ico")
def favicon():
    return app.send_static_file("favicon.ico")

# -------------------------------------------------------------------
# Start app
# -------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    socketio.run(app, host="0.0.0.0", port=port)
