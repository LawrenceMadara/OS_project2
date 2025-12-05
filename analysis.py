import pandas as pd
from datetime import datetime

def log_step(message):
    """Log a timestamped message to console."""
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}")

def load_dataset(filepath):
    """Load the CSV dataset."""
    log_step("Loading dataset")
    try:
        df = pd.read_csv(filepath)
    except FileNotFoundError:
        log_step(f"Error: File '{filepath}' not found")
        raise
    return df

def clean_macronutrients(df):
    """Fill missing values in Protein, Carbs, and Fat columns with their means."""
    log_step("Cleaning macronutrient columns (handling missing data)")
    for col in ['Protein(g)', 'Carbs(g)', 'Fat(g)']:
        if col in df.columns:
            mean_val = df[col].mean()
            df[col] = df[col].fillna(mean_val)
            log_step(f"Filled missing values in '{col}' with mean: {mean_val:.2f}")
        else:
            log_step(f"Warning: Column '{col}' not found in dataset")
    return df

def add_nutrient_ratios(df):
    """Add Protein-to-Carbs and Carbs-to-Fat ratio columns safely."""
    log_step("Adding nutrient ratio columns")
    df['Protein_to_Carbs_ratio'] = df.apply(
        lambda row: row['Protein(g)'] / row['Carbs(g)'] if row['Carbs(g)'] else 0, axis=1
    )
    df['Carbs_to_Fat_ratio'] = df.apply(
        lambda row: row['Carbs(g)'] / row['Fat(g)'] if row['Fat(g)'] else 0, axis=1
    )
    return df

def calculate_average_macros(df):
    """Calculate average Protein, Carbs, and Fat per diet type."""
    log_step("Calculating average macronutrient content per diet type")
    required_cols = ['Protein(g)', 'Carbs(g)', 'Fat(g)']
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        log_step(f"Warning: Missing columns for averaging: {missing_cols}")
    return df.groupby('Diet_type')[required_cols].mean()

def get_top_protein_recipes(df, top_n=5):
    """Get top N protein-rich recipes per diet type."""
    log_step(f"Identifying top {top_n} protein-rich recipes per diet type")
    if 'Protein(g)' not in df.columns:
        log_step("Error: 'Protein(g)' column missing, cannot compute top protein recipes")
        return pd.DataFrame()
    return df.sort_values('Protein(g)', ascending=False).groupby('Diet_type').head(top_n)

def get_highest_protein_diet(avg_macros):
    """Find which diet type has the highest average protein."""
    log_step("Finding diet with highest average protein content")
    if 'Protein(g)' not in avg_macros.columns:
        log_step("Warning: 'Protein(g)' column missing in avg_macros")
        return None
    return avg_macros['Protein(g)'].idxmax()

def get_common_cuisines(df):
    """Identify the most common cuisine per diet type."""
    log_step("Identifying most common cuisine per diet type")
    if 'Cuisine_type' not in df.columns:
        log_step("Warning: 'Cuisine_type' column missing; returning empty result")
        return pd.DataFrame(columns=['Diet_type', 'Cuisine_type'])
    
    return df.groupby('Diet_type')['Cuisine_type'].agg(
        lambda x: x.mode().iloc[0] if not x.mode().empty else 'Unknown'
    ).reset_index()

def filter_by_diet(df, diet_type):
    """Filter dataset by specific diet type."""
    log_step(f"Filtering data for diet type: {diet_type}")
    if diet_type.lower() == 'all':
        return df
    if 'Diet_type' not in df.columns:
        log_step("Warning: 'Diet_type' column missing, cannot filter")
        return pd.DataFrame()
    return df[df['Diet_type'].str.lower() == diet_type.lower()]

def get_macronutrient_distribution(df):
    """Get distribution statistics for macronutrients."""
    log_step("Calculating macronutrient distribution statistics")
    cols = ['Protein(g)', 'Carbs(g)', 'Fat(g)']
    available_cols = [c for c in cols if c in df.columns]
    if not available_cols:
        log_step("Warning: No macronutrient columns available for distribution stats")
        return pd.DataFrame()
    return df[available_cols].describe()

def run_full_analysis(filepath):
    """
    Run full analysis pipeline and return key results as a dictionary.
    Useful for API endpoints or data processing.
    """
    log_step("Starting full analysis pipeline")
    
    df = load_dataset(filepath)
    df = clean_macronutrients(df)
    df = add_nutrient_ratios(df)

    avg_macros = calculate_average_macros(df)
    top_protein = get_top_protein_recipes(df)
    highest_protein_diet = get_highest_protein_diet(avg_macros)
    common_cuisines = get_common_cuisines(df)

    results = {
        "average_macros": avg_macros.reset_index(),
        "top_protein_recipes": top_protein[['Diet_type', 'Recipe_name', 'Protein(g)', 'Cuisine_type']] if not top_protein.empty else pd.DataFrame(),
        "highest_protein_diet": highest_protein_diet,
        "common_cuisines": common_cuisines
    }
    
    log_step("Analysis pipeline completed successfully")
    return results
