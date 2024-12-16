# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "pandas",
#   "seaborn",
#   "matplotlib",
#   "requests",
#   "scikit-learn",
#   "chardet",
#   "plotly"
# ]
# ///

import os
import sys
import json
import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt
import plotly.express as px
import requests
import logging
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import silhouette_score
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

# Configure logging
logging.basicConfig(
    filename='autolysis.log',
    filemode='a',
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

def get_api_details():
    """
    Retrieves the AI Proxy token and sets the API endpoint URL.
    """
    api_proxy_token = os.getenv("AIPROXY_TOKEN")
    if not api_proxy_token:
        logging.error("AIPROXY_TOKEN environment variable not set.")
        print("Error: AIPROXY_TOKEN environment variable not set.")
        sys.exit(1)

    api_proxy_url = "https://aiproxy.sanand.workers.dev/openai/v1/chat/completions"
    return api_proxy_token, api_proxy_url

def detect_encoding(file_path):
    """
    Detects the encoding of a file using chardet.
    """
    try:
        import chardet
    except ImportError:
        logging.info("chardet library not found. Installing...")
        os.system("pip install chardet")
        import chardet

    with open(file_path, 'rb') as f:
        result = chardet.detect(f.read())
    return result['encoding']

def determine_cluster_count(df):
    """
    Determines the optimal number of clusters using the silhouette score.
    """
    numeric_data = df.select_dtypes(include=['number'])
    if numeric_data.empty:
        return 1  # Default to 1 cluster if no numeric data

    max_clusters = min(10, len(numeric_data) // 10)  # Prevent too many clusters
    if max_clusters < 2:
        return 1

    best_score = -1
    best_k = 2
    for k in range(2, max_clusters + 1):
        kmeans = KMeans(n_clusters=k, random_state=42)
        clusters = kmeans.fit_predict(numeric_data)
        try:
            score = silhouette_score(numeric_data, clusters)
            if score > best_score:
                best_score = score
                best_k = k
        except:
            continue
    return best_k

def analyze_dataset(file_path):
    """
    Loads the dataset with appropriate encoding and performs basic and advanced analysis.
    Returns the DataFrame and a dictionary containing analysis details.
    """
    # Detect encoding
    encoding = detect_encoding(file_path)
    try:
        df = pd.read_csv(file_path, encoding=encoding)
        logging.info(f"Successfully loaded {file_path} with encoding {encoding}")
        print(f"Successfully loaded {file_path} with encoding {encoding}")
    except Exception as e:
        logging.error(f"Error loading {file_path}: {e}")
        print(f"Error loading {file_path}: {e}")
        sys.exit(1)

    # Basic Analysis
    try:
        summary_stats = df.describe(include='all').to_dict()
        logging.info(f"Generated summary statistics for {file_path}")
    except Exception as e:
        logging.warning(f"Unable to generate summary statistics for {file_path}. {e}")
        print(f"Warning: Unable to generate summary statistics for {file_path}. {e}")
        summary_stats = {}

    missing_values = df.isnull().sum().to_dict()
    dtypes = df.dtypes.apply(str).to_dict()
    columns = list(df.columns)

    analysis = {
        "columns": columns,
        "dtypes": dtypes,
        "missing_values": missing_values,
        "summary_stats": summary_stats
    }

    # Handle Missing Values
    # Impute numeric columns with median
    numeric_cols = df.select_dtypes(include=['number']).columns
    for col in numeric_cols:
        median = df[col].median()
        df[col] = df[col].fillna(median)

    # Impute categorical columns with mode
    categorical_cols = df.select_dtypes(include=['object', 'category']).columns
    for col in categorical_cols:
        mode = df[col].mode()[0] if not df[col].mode().empty else 'Unknown'
        df[col] = df[col].fillna(mode)

    # Advanced Analysis: Outlier Detection
    outliers = {}
    for col in numeric_cols:
        Q1 = df[col].quantile(0.25)
        Q3 = df[col].quantile(0.75)
        IQR = Q3 - Q1
        lower_bound = Q1 - 1.5 * IQR
        upper_bound = Q3 + 1.5 * IQR
        outlier_count = df[(df[col] < lower_bound) | (df[col] > upper_bound)].shape[0]
        outliers[col] = outlier_count

    analysis["outliers"] = outliers

    # Feature Importance (e.g., using correlation)
    feature_importance = {}
    if len(numeric_cols) > 1:
        corr_matrix = df[numeric_cols].corr()
        for col in numeric_cols:
            correlations = corr_matrix[col].drop(labels=[col]).abs().sort_values(ascending=False)
            if not correlations.empty:
                feature_importance[col] = correlations.index[0]
            else:
                feature_importance[col] = None
    analysis["feature_importance"] = feature_importance

    # Clustering
    if len(numeric_cols) >= 2:
        optimal_k = determine_cluster_count(df)
        if optimal_k > 1:
            scaler = StandardScaler()
            scaled_data = scaler.fit_transform(df[numeric_cols])
            kmeans = KMeans(n_clusters=optimal_k, random_state=42)
            clusters = kmeans.fit_predict(scaled_data)
            df['Cluster'] = clusters
            cluster_counts = df['Cluster'].value_counts().to_dict()
            analysis["clusters"] = cluster_counts
            logging.info(f"Performed K-Means clustering with k={optimal_k} on {file_path}")
        else:
            analysis["clusters"] = "Clustering not performed due to insufficient data or low optimal k."
            logging.warning(f"Clustering not performed for {file_path}")
    else:
        analysis["clusters"] = "Not enough numeric columns for clustering."
        logging.warning(f"Not enough numeric columns for clustering in {file_path}")

    return df, analysis

def create_session_with_retries():
    """
    Creates a requests session with retry logic.
    """
    session = requests.Session()
    retries = Retry(total=5, backoff_factor=1, status_forcelist=[502, 503, 504])
    adapter = HTTPAdapter(max_retries=retries)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    return session

def generate_visualizations(df, output_dir):
    """
    Generates visualizations based on the DataFrame and saves them as PNG files.
    Returns a list of generated PNG filenames.
    """
    png_files = []

    # 1. Correlation Heatmap (if applicable)
    numeric_columns = df.select_dtypes(include='number').columns
    if len(numeric_columns) > 1:
        corr = df[numeric_columns].corr()
        plt.figure(figsize=(12, 10))
        sns.heatmap(corr, annot=True, cmap="coolwarm", fmt=".2f")
        plt.title("Correlation Heatmap")
        heatmap_path = os.path.join(output_dir, "correlation_heatmap.png")
        plt.savefig(heatmap_path, dpi=100)
        plt.close()
        png_files.append("correlation_heatmap.png")
        logging.info(f"Saved correlation_heatmap.png in {output_dir}")
        print(f"Saved correlation_heatmap.png in {output_dir}")

    # 2. Distribution Plot of the First Numeric Column
    if len(numeric_columns) > 0:
        first_numeric = numeric_columns[0]
        plt.figure(figsize=(10, 6))
        sns.histplot(df[first_numeric], kde=True, bins=30, color='skyblue')
        plt.title(f"Distribution of {first_numeric}")
        plt.xlabel(first_numeric)
        plt.ylabel("Frequency")
        dist_path = os.path.join(output_dir, f"{first_numeric}_distribution.png")
        plt.savefig(dist_path, dpi=100)
        plt.close()
        png_files.append(f"{first_numeric}_distribution.png")
        logging.info(f"Saved {first_numeric}_distribution.png in {output_dir}")
        print(f"Saved {first_numeric}_distribution.png in {output_dir}")

    # 3. Categorical Count Plot (if applicable)
    categorical_columns = df.select_dtypes(include=['object', 'category']).columns
    if len(categorical_columns) > 0:
        first_categorical = categorical_columns[0]
        plt.figure(figsize=(12, 8))
        sns.countplot(
            data=df,
            y=first_categorical,
            order=df[first_categorical].value_counts().index[:10],
            palette="viridis",
            hue=first_categorical,
            dodge=False
        )
        plt.title(f"Top 10 {first_categorical} Categories")
        plt.xlabel("Count")
        plt.ylabel(first_categorical)
        plt.legend([], [], frameon=False)  # Hide legend to fix FutureWarning
        count_path = os.path.join(output_dir, f"{first_categorical}_count.png")
        plt.savefig(count_path, dpi=100)
        plt.close()
        png_files.append(f"{first_categorical}_count.png")
        logging.info(f"Saved {first_categorical}_count.png in {output_dir}")
        print(f"Saved {first_categorical}_count.png in {output_dir}")

    # 4. Box Plot for Outlier Detection
    if len(numeric_columns) > 0:
        first_numeric = numeric_columns[0]
        plt.figure(figsize=(10, 6))
        sns.boxplot(x=df[first_numeric], color='lightgreen')
        plt.title(f"Box Plot of {first_numeric}")
        plt.xlabel(first_numeric)
        box_path = os.path.join(output_dir, f"{first_numeric}_boxplot.png")
        plt.savefig(box_path, dpi=100)
        plt.close()
        png_files.append(f"{first_numeric}_boxplot.png")
        logging.info(f"Saved {first_numeric}_boxplot.png in {output_dir}")
        print(f"Saved {first_numeric}_boxplot.png in {output_dir}")

    # 5. Scatter Plot for Clustering (if applicable)
    if 'Cluster' in df.columns and len(numeric_columns) >= 2:
        plt.figure(figsize=(10, 6))
        sns.scatterplot(
            data=df,
            x=numeric_columns[0],
            y=numeric_columns[1],
            hue='Cluster',
            palette='Set1'
        )
        plt.title(f"Scatter Plot of {numeric_columns[0]} vs {numeric_columns[1]} with Clusters")
        scatter_path = os.path.join(output_dir, f"{numeric_columns[0]}_vs_{numeric_columns[1]}_clusters.png")
        plt.savefig(scatter_path, dpi=100)
        plt.close()
        png_files.append(f"{numeric_columns[0]}_vs_{numeric_columns[1]}_clusters.png")
        logging.info(f"Saved {numeric_columns[0]}_vs_{numeric_columns[1]}_clusters.png in {output_dir}")
        print(f"Saved {numeric_columns[0]}_vs_{numeric_columns[1]}_clusters.png in {output_dir}")

    return png_files

def generate_interactive_visualizations(df, output_dir):
    """
    Generates interactive visualizations using Plotly and saves them as HTML files.
    Returns a list of generated HTML filenames.
    """
    interactive_files = []

    numeric_columns = df.select_dtypes(include='number').columns
    categorical_columns = df.select_dtypes(include=['object', 'category']).columns

    if len(numeric_columns) >= 2:
        fig = px.scatter(
            df,
            x=numeric_columns[0],
            y=numeric_columns[1],
            color='Cluster' if 'Cluster' in df.columns else None,
            title=f"Interactive Scatter Plot of {numeric_columns[0]} vs {numeric_columns[1]}",
            hover_data=numeric_columns.tolist()
        )
        interactive_plot_path = os.path.join(output_dir, f"{numeric_columns[0]}_vs_{numeric_columns[1]}_interactive.html")
        fig.write_html(interactive_plot_path)
        interactive_files.append(f"{numeric_columns[0]}_vs_{numeric_columns[1]}_interactive.html")
        logging.info(f"Saved {numeric_columns[0]}_vs_{numeric_columns[1]}_interactive.html in {output_dir}")
        print(f"Saved {numeric_columns[0]}_vs_{numeric_columns[1]}_interactive.html in {output_dir}")

    # Additional interactive visualizations can be added here

    return interactive_files

def analyze_visualizations(png_files, api_proxy_token, api_proxy_url):
    """
    Uses the OpenAI Vision API to analyze the generated visualizations.
    Returns a dictionary with insights from the images.
    """
    # Placeholder for vision analysis
    vision_insights = {}

    # Example: If Vision API is available, analyze each PNG
    # for img in png_files:
    #     if img.endswith('.png'):
    #         img_path = os.path.join(output_dir, img)
    #         with open(img_path, 'rb') as image_file:
    #             image_data = image_file.read()
    #         # Send image_data to Vision API and get insights
    #         # vision_insights[img] = vision_response
    #         pass

    # Currently, since GPT-4o-Mini may not support vision, we leave this as a placeholder
    return vision_insights

def narrate_story_dynamic(analysis, png_files, interactive_files, api_proxy_token, api_proxy_url):
    """
    Generates a dynamic narrative in Markdown format using the LLM based on the analysis.
    Returns the narrative as a string.
    """
    session = create_session_with_retries()

    # Determine if the dataset has specific characteristics
    has_clusters = isinstance(analysis['clusters'], dict)
    has_outliers = any(count > 0 for count in analysis['outliers'].values())

    # Create a detailed summary to send to the LLM
    analysis_summary = (
        f"**Columns:** {analysis['columns']}\n"
        f"**Data Types:** {analysis['dtypes']}\n"
        f"**Missing Values:** {analysis['missing_values']}\n"
        f"**Summary Statistics:** {json.dumps(analysis['summary_stats'], indent=2)}\n"
        f"**Outliers Detected:** {json.dumps(analysis['outliers'], indent=2)}\n"
        f"**Feature Importance:** {json.dumps(analysis['feature_importance'], indent=2)}\n"
        f"**Clustering Results:** {json.dumps(analysis['clusters'], indent=2)}\n"
    )

    # Dynamic Prompt based on dataset characteristics
    prompt = (
        "You are an expert data scientist with extensive experience in data analysis and visualization. "
        "Based on the comprehensive analysis provided below, generate a detailed narrative in Markdown format that includes the following sections:\n\n"
        "1. **Dataset Overview:** A thorough description of the dataset, including its source, purpose, and structure.\n"
        "2. **Data Cleaning and Preprocessing:** Outline the steps taken to handle missing values, outliers, and any data transformations applied.\n"
    )

    if has_outliers:
        prompt += "3. **Outlier Analysis:** Discuss the outliers detected and their potential impact on the data.\n"
    else:
        prompt += "3. **Data Quality:** Confirm that the dataset is clean with no significant outliers detected.\n"

    prompt += (
        "4. **Exploratory Data Analysis (EDA):** Present key insights, trends, and patterns discovered during the analysis.\n"
        "5. **Visualizations:** For each generated chart, provide an in-depth explanation of what it represents and the insights it offers.\n"
    )

    if has_clusters:
        prompt += "6. **Clustering and Segmentation:** Discuss the results of any clustering algorithms used, including the characteristics of each cluster.\n"
    else:
        prompt += "6. **Additional Insights:** Provide any other significant findings from the analysis.\n"

    prompt += (
        "7. **Implications and Recommendations:** Based on the findings, suggest actionable recommendations or potential implications for stakeholders.\n"
        "8. **Future Work:** Propose three additional analyses or visualizations that could further enhance the understanding of the dataset.\n"
        "9. **Vision Agentic Enhancements:** Recommend ways to incorporate advanced visual (image-based) analysis techniques or interactive visualizations to provide deeper insights.\n\n"
        f"**Comprehensive Analysis:**\n{analysis_summary}"
    )

    # Prepare the payload for the AI Proxy
    payload = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": "You are a helpful data scientist narrating the story of a dataset."},
            {"role": "user", "content": prompt}
        ],
        "max_tokens": 2500,  # Increased tokens for a more detailed response
        "temperature": 0.7
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_proxy_token}"
    }

    try:
        response = session.post(api_proxy_url, headers=headers, json=payload)
        if response.status_code == 200:
            result = response.json()
            story = result['choices'][0]['message']['content']
            logging.info("Successfully generated dynamic narrative with LLM.")
            print("Successfully generated dynamic narrative with LLM.")
        else:
            logging.error(f"Error: {response.status_code}, {response.text}")
            print(f"Error: {response.status_code}, {response.text}")
            story = f"Error generating narrative: {response.status_code}, {response.text}"
    except Exception as e:
        logging.error(f"Error generating narrative: {e}")
        print(f"Error generating narrative: {e}")
        story = f"Error generating narrative: {e}"

    # Append image references to the narrative
    if png_files and "error" not in story.lower():
        story += "\n\n## Visualizations\n"
        for img in png_files:
            if img.endswith('.html'):
                story += f"[Interactive Visualization]({img})\n"
            else:
                story += f"![{img}]({img})\n"

    # Include interactive visualizations in the narrative
    if interactive_files:
        story += "\n\n## Interactive Visualizations\n"
        for html in interactive_files:
            story += f"[{html}]({html})\n"

    return story

def narrate_story_vision_agentic(analysis, png_files, interactive_files, api_proxy_token, api_proxy_url):
    """
    Generates a narrative including vision agentic enhancements.
    """
    # Generate the dynamic narrative
    story = narrate_story_dynamic(analysis, png_files, interactive_files, api_proxy_token, api_proxy_url)

    # Analyze visualizations using vision models (placeholder)
    vision_insights = analyze_visualizations(png_files, api_proxy_token, api_proxy_url)

    # Append vision insights to the narrative
    if vision_insights:
        story += "\n\n## Vision Insights\n"
        for img, insights in vision_insights.items():
            story += f"### {img}\n{insights}\n"

    return story

def analyze_and_generate_output(file_path, api_proxy_token, api_proxy_url):
    """
    Processes a single CSV file: analyzes data, generates visualizations, narrates the story.
    Saves outputs in a dedicated directory.
    """
    base_name = os.path.splitext(os.path.basename(file_path))[0]
    output_dir = os.path.join(".", base_name)
    os.makedirs(output_dir, exist_ok=True)
    logging.info(f"Created directory: {output_dir}")
    print(f"Created directory: {output_dir}")

    df, analysis = analyze_dataset(file_path)
    png_files = generate_visualizations(df, output_dir)
    interactive_files = generate_interactive_visualizations(df, output_dir)
    story = narrate_story_vision_agentic(analysis, png_files, interactive_files, api_proxy_token, api_proxy_url)

    # Write story to README.md
    readme_path = os.path.join(output_dir, "README.md")
    try:
        with open(readme_path, "w", encoding='utf-8') as f:
            f.write(story)
        logging.info(f"Saved README.md in {output_dir}")
        print(f"Saved README.md in {output_dir}")
    except Exception as e:
        logging.error(f"Error writing README.md in {output_dir}: {e}")
        print(f"Error writing README.md in {output_dir}: {e}")

    return output_dir

def main():
    """
    Main function to process all provided CSV files.
    """
    if len(sys.argv) != 2:
        print("Usage: uv run autolysis.py dataset.csv")
        sys.exit(1)

    file_path = sys.argv[1]
    api_proxy_token, api_proxy_url = get_api_details()

    if os.path.exists(file_path):
        print(f"Processing file: {file_path}")
        logging.info(f"Processing file: {file_path}")
        output_dir = analyze_and_generate_output(file_path, api_proxy_token, api_proxy_url)
        print(f"Analysis completed. Results saved in directory: {output_dir}")
        logging.info(f"Analysis completed. Results saved in directory: {output_dir}")
    else:
        logging.error(f"File {file_path} not found!")
        print(f"File {file_path} not found!")

if __name__ == "__main__":
    main()