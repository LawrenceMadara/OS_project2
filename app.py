import os
import time
import pandas as pd

from flask import (
    Flask,
    jsonify,
    render_template,
    redirect,
    url_for,
    session,
    request,
)
from flask_socketio import SocketIO, emit
from authlib.integrations.flask_client import OAuth

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

# -------------------------------------------------------------------
# Flask / Socket.IO setup
# -------------------------------------------------------------------
app = Flask(__name__)

# Secret key (use env var in production)
app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET_KEY", "dev-secret")

socketio = SocketIO(app, cors_allowed_origins="*", manage_session=False)

# -------------------------------------------------------------------
# OAuth setup for Google & GitHub
# -------------------------------------------------------------------
app.config["GOOGLE_CLIENT_ID"] = os.environ.get("GOOGLE_CLIENT_ID")
app.config["GOOGLE_CLIENT_SECRET"] = os.environ.get("GOOGLE_CLIENT_SECRET")
app.config["GITHUB_CLIENT_ID"] = os.environ.get("GITHUB_CLIENT_ID")
app.config["GITHUB_CLIENT_SECRET"] = os.environ.get("GITHUB_CLIENT_SECRET")

oauth = OAuth(app)

oauth.register(
    name="google",
    client_id=app.config["GOOGLE_CLIENT_ID"],
    client_secret=app.config["GOOGLE_CLIENT_SECRET"],
    access_token_url="https://oauth2.googleapis.com/token",
    authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
    api_base_url="https://www.googleapis.com/oauth2/v2/",
    client_kwargs={"scope": "openid email profile"},
)

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
# Basic routes
# -------------------------------------------------------------------
@app.route("/")
def index():
    """Main dashboard page."""
    return render_template("index.html")


# ---------------------- Authentication Routes ----------------------


@app.route("/login/<provider>")
def login(provider):
    """Start OAuth login with Google or GitHub."""
    if provider not in ("google", "github"):
        return "Unknown provider", 404

    redirect_uri = url_for("auth_callback", provider=provider, _external=True)
    if provider == "google":
        return oauth.google.authorize_redirect(redirect_uri)
    else:
        return oauth.github.authorize_redirect(redirect_uri)


@app.route("/auth/callback/<provider>")
def auth_callback(provider):
    """Handle OAuth callback and store user in session."""
    if provider not in ("google", "github"):
        return "Unknown provider", 404

    if provider == "google":
        token = oauth.google.authorize_access_token()
        userinfo = oauth.google.get("userinfo").json()
        session["user"] = {
            "provider": "Google",
            "id": userinfo.get("id"),
            "name": userinfo.get("name"),
            "email": userinfo.get("email"),
            "picture": userinfo.get("picture"),
        }
    else:
        token = oauth.github.authorize_access_token()
        gh_user = oauth.github.get("user").json()
        session["user"] = {
            "provider": "GitHub",
            "id": gh_user.get("id"),
            "name": gh_user.get("name") or gh_user.get("login"),
            "email": gh_user.get("email"),
            "picture": gh_user.get("avatar_url"),
        }

    return redirect(url_for("index"))


@app.route("/auth/status")
def auth_status():
    """Return JSON with current authentication status for the frontend."""
    user = session.get("user")
    if not user:
        return jsonify({"authenticated": False})
    return jsonify(
        {
            "authenticated": True,
            "provider": user.get("provider"),
            "name": user.get("name"),
            "email": user.get("email"),
        }
    )


@app.route("/logout")
def logout():
    """Clear the session and return to the dashboard."""
    session.clear()
    return redirect(url_for("index"))


# -------------------------------------------------------------------
# Real-Time Nutritional Analysis (Socket.IO)
# -------------------------------------------------------------------
@socketio.on("start_analysis")
def handle_start_analysis():
    """Send live updates during analysis."""
    emit("progress", {"status": "Loading dataset..."})
    time.sleep(1)

    df = load_dataset("res/All_Diets.csv")
    df = clean_macronutrients(df)
    emit("progress", {"status": "Calculating averages..."})
    time.sleep(1)

    avg_macros = calculate_average_macros(df)
    emit("progress", {"status": "Finding top protein recipes..."})
    time.sleep(1)

    top_protein = get_top_protein_recipes(df)
    emit("progress", {"status": "Generating summary..."})
    time.sleep(1)

    summary = run_full_analysis("res/All_Diets.csv")

    emit(
        "complete",
        {
            "message": "Analysis finished!",
            "summary": {
                "highest_protein_diet": summary["highest_protein_diet"],
                "average_macros": summary["average_macros"].to_dict(
                    orient="records"
                ),
                "common_cuisines": summary["common_cuisines"].to_dict(
                    orient="records"
                ),
            },
        },
    )


# -------------------------------------------------------------------
# Simple Recipe Search API
# -------------------------------------------------------------------
RECIPES = {
    "chicken": {
        "title": "Simple Baked Chicken Breast",
        "description": "Easy oven-baked chicken breast with basic seasoning.",
        "ingredients": [
            "2 chicken breasts",
            "1 tbsp olive oil",
            "1 tsp salt",
            "1/2 tsp black pepper",
            "1 tsp garlic powder",
            "1 tsp paprika",
        ],
        "steps": [
            "Preheat oven to 400°F (200°C).",
            "Pat the chicken dry and rub with olive oil.",
            "Season both sides with salt, pepper, garlic powder, and paprika.",
            "Bake for 20–25 minutes or until internal temperature reaches 165°F (74°C).",
            "Rest for 5 minutes, then slice and serve.",
        ],
    },
    "oats": {
        "title": "Basic Oatmeal Breakfast Bowl",
        "description": "Warm oats with fruit and nuts.",
        "ingredients": [
            "1/2 cup rolled oats",
            "1 cup water or milk",
            "Pinch of salt",
            "1 tbsp honey or maple syrup",
            "1/2 banana, sliced",
            "Handful of berries or nuts",
        ],
        "steps": [
            "Add oats, liquid, and salt to a small pot.",
            "Bring to a boil, then reduce to low and simmer 5–7 minutes, stirring.",
            "Pour into a bowl and top with banana, berries, and nuts.",
            "Drizzle with honey or maple syrup.",
        ],
    },
    "salad": {
        "title": "Simple Mixed Green Salad",
        "description": "Quick salad with basic dressing.",
        "ingredients": [
            "2 cups mixed greens",
            "5 cherry tomatoes, halved",
            "1/4 cucumber, sliced",
            "1 tbsp olive oil",
            "1 tsp lemon juice or vinegar",
            "Salt and pepper",
        ],
        "steps": [
            "Add greens, tomatoes, and cucumber to a bowl.",
            "In a small bowl, whisk olive oil, lemon/vinegar, salt and pepper.",
            "Pour dressing over the salad and toss gently.",
            "Serve immediately.",
        ],
    },
}


@app.route("/api/recipe")
def get_recipe():
    """Return a simple recipe based on a food keyword in the search."""
    query = request.args.get("q", "").strip().lower()
    if not query:
        return jsonify({"found": False, "message": "Please type a food name."})

    # basic keyword match
    for keyword, recipe in RECIPES.items():
        if keyword in query:
            return jsonify({"found": True, "recipe": recipe})

    return jsonify({"found": False, "message": "No recipe found for that food."})


# -------------------------------------------------------------------
# Start app
# -------------------------------------------------------------------
if __name__ == "__main__":
    # In Azure you usually run via gunicorn, but this works locally
    socketio.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
