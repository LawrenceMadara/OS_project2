from flask import Flask, jsonify, render_template
import pandas as pd
from analysis import (
    load_dataset, clean_macronutrients, calculate_average_macros,
    get_top_protein_recipes, add_nutrient_ratios, filter_by_diet,
    get_common_cuisines, get_macronutrient_distribution, run_full_analysis
)

app = Flask(__name__)

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

if __name__ == '__main__':
    app.run(debug=True)