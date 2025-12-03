
from flask import Flask, jsonify, render_template, redirect, url_for, session # type: ignore
import pandas as pd # type: ignore
from authlib.integrations.flask_client import OAuth
from flask_login import LoginManager, login_user, logout_user, login_required, UserMixin
from azure.identity import DefaultAzureCredential
from azure.mgmt.resource import ResourceManagementClient
from analysis import (
    load_dataset, clean_macronutrients, calculate_average_macros,
    get_top_protein_recipes, add_nutrient_ratios, filter_by_diet,
    get_common_cuisines, get_macronutrient_distribution, run_full_analysis
)

app = Flask(__name__)
SUBSCRIPTION_ID = "YOUR_AZURE_SUBSCRIPTION"
RESOURCE_GROUP = "YOUR_RESOURCE_GROUP"

app.secret_key = "YOUR_SECRET_KEY"

oauth = OAuth(app)

# Google OAuth
google = oauth.register(
    name='google',
    client_id="GOOGLE_CLIENT_ID",
    client_secret="GOOGLE_CLIENT_SECRET",
    access_token_url="https://oauth2.googleapis.com/token",
    authorize_url="https://accounts.google.com/o/oauth2/auth",
    client_kwargs={"scope": "openid profile email"},
)

# GitHub OAuth
github = oauth.register(
    name='github',
    client_id="GITHUB_CLIENT_ID",
    client_secret="GITHUB_CLIENT_SECRET",
    access_token_url="https://github.com/login/oauth/access_token",
    authorize_url="https://github.com/login/oauth/authorize",
    client_kwargs={"scope": "user:email"}
)

login_manager = LoginManager(app)

class User(UserMixin):
    def __init__(self, id_, email):
        self.id = id_
        self.email = email

users = {}

@app.route("/login/google")
def login_google():
    redirect_uri = url_for("auth_google", _external=True)
    return google.authorize_redirect(redirect_uri)

@app.route("/auth/google")
def auth_google():
    token = google.authorize_access_token()
    userinfo = google.parse_id_token(token)
    
    user = User(userinfo["sub"], userinfo["email"])
    users[user.id] = user
    login_user(user)

    return redirect("/")

@app.route("/login/github")
def login_github():
    redirect_uri = url_for("auth_github", _external=True)
    return github.authorize_redirect(redirect_uri)

@app.route("/auth/github")
def auth_github():
    token = github.authorize_access_token()
    userinfo = github.get("user").json()

    user = User(str(userinfo["id"]), userinfo["email"])
    users[user.id] = user
    login_user(user)

    return redirect("/")


@app.before_request
def enforce_https():
    if request.headers.get("X-Forwarded-Proto", "http") != "https":
        url = request.url.replace("http://", "https://", 1)
        return redirect(url, 301)

@app.after_request
def set_secure_headers(response):
    response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains; preload"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' https://cdn.jsdelivr.net https://cdn.jsdelivr.net/npm/chart.js; "
        "style-src 'self' https://cdn.jsdelivr.net/npm/tailwindcss@2.0.0/dist/ 'unsafe-inline'; "
        "img-src 'self' data:; "
        "connect-src 'self';"
    )
    return response


@app.route('/')
def index():
    """Render the main dashboard page."""
    return render_template('index.html')  

@app.route('/api/avg_macros')
def avg_macros_api():
    """
    API endpoint to get average macronutrients per diet type.
    Returns JSON array with Diet_type, Protein(g), Carbs(g), Fat(g).
    """
    df = load_dataset("res/All_Diets.csv")
    df = clean_macronutrients(df)
    avg_macros = calculate_average_macros(df)
    return jsonify(avg_macros.reset_index().to_dict(orient='records'))

@app.route('/api/top_protein')
def top_protein_api():
    """
    API endpoint to get top 5 protein-rich recipes per diet type.
    Returns JSON array with recipe details including protein content.
    """
    df = load_dataset("res/All_Diets.csv")
    df = clean_macronutrients(df)
    top_protein = get_top_protein_recipes(df)
    return jsonify(top_protein[['Diet_type', 'Recipe_name', 'Protein(g)', 'Cuisine_type']].to_dict(orient='records'))

@app.route('/api/common_cuisines')
def common_cuisines_api():
    """
    API endpoint to get the most common cuisine type per diet.
    Returns JSON array with Diet_type and Cuisine_type.
    """
    df = load_dataset("res/All_Diets.csv")
    df = clean_macronutrients(df)
    cuisines = get_common_cuisines(df)
    return jsonify(cuisines.reset_index().to_dict(orient='records'))

@app.route('/api/summary')
def summary_api():
    """
    API endpoint to get a comprehensive summary of the analysis.
    Returns highest protein diet, average macros, and common cuisines.
    """
    results = run_full_analysis("res/All_Diets.csv")
    return jsonify({
        "highest_protein_diet": results["highest_protein_diet"],
        "average_macros": results["average_macros"].to_dict(orient='records'),
        "common_cuisines": results["common_cuisines"].to_dict(orient='records')
    })

@app.route('/api/scatter_data')
def scatter_data_api():
    """
    API endpoint to get data for scatter plot visualization.
    Returns protein vs carbs data with diet type and cuisine information.
    """
    df = load_dataset("res/All_Diets.csv")
    df = clean_macronutrients(df)
    df = add_nutrient_ratios(df)

    scatter_df = df[['Diet_type', 'Protein(g)', 'Carbs(g)', 'Cuisine_type']].dropna()
    return jsonify(scatter_df.to_dict(orient='records'))

@app.route('/api/heatmap_data')
def heatmap_data_api():
    """
    API endpoint to get macronutrient data for heatmap visualization.
    Returns average macros per diet type in matrix format.
    """
    df = load_dataset("res/All_Diets.csv")
    df = clean_macronutrients(df)
    avg_macros = calculate_average_macros(df)
    return jsonify(avg_macros.reset_index().to_dict(orient='records'))

@app.route('/api/filter/<diet_type>')
def filter_diet_api(diet_type):
    """
    API endpoint to filter data by specific diet type.
    Returns filtered dataset with all columns.
    """
    df = load_dataset("res/All_Diets.csv")
    df = clean_macronutrients(df)
    filtered_df = filter_by_diet(df, diet_type)
    return jsonify(filtered_df.to_dict(orient='records'))

@app.route('/api/distribution')
def distribution_api():
    """
    API endpoint to get statistical distribution of macronutrients.
    Returns descriptive statistics (mean, std, min, max, quartiles).
    """
    df = load_dataset("res/All_Diets.csv")
    df = clean_macronutrients(df)
    stats = get_macronutrient_distribution(df)
    return jsonify(stats.to_dict())

@app.route("/cleanup", methods=["POST"])
def cleanup_resources():
    credential = DefaultAzureCredential()
    client = ResourceManagementClient(credential, SUBSCRIPTION_ID)

    delete_op = client.resource_groups.begin_delete(RESOURCE_GROUP)
    delete_op.wait()

    return {"status": "cleanup_complete"}

if __name__ == '__main__':
    app.run(debug=True)
