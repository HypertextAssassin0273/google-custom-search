from flask import Flask, request, jsonify, render_template
from dotenv import load_dotenv
import os, requests

app = Flask(__name__)

load_dotenv()
API_KEY = os.getenv("API_KEY")
SEARCH_ENGINE_ID = os.getenv("SEARCH_ENGINE_ID")

def google_search(query, start=1):
    """Fetch search results from Google Custom Search API."""
    url = "https://www.googleapis.com/customsearch/v1"
    params = {
        "key": API_KEY,
        "cx": SEARCH_ENGINE_ID,
        "q": query,
        "start": start,
        # "exactTerms": query,  # Forces exact match
        # "filter": 1           # Removes duplicate results
    }
    
    response = requests.get(url, params=params)
    results = response.json()
    # app.logger.info(f"[DEBUG]: response={results}\n----------\n")

    # Extract search results
    items = extract_results(results)
    app.logger.info(f"[DEBUG]: items={items}\n----------\n")

    # Determine next page index
    next_start = get_next_start(results)
    # app.logger.info(f"[DEBUG]: next_start={next_start}\n----------\n")

    return items, next_start

def extract_results(response_json):
    """Extracts search results from API response."""
    results = []
    for item in response_json.get("items", []):
        results.append({
            "title": item.get("title"),
            "link": item.get("link"),
            "snippet": item.get("snippet")
        })
    return results

def get_next_start(response_json):
    """Extracts the next page start index from API response."""
    queries = response_json.get("queries", {})
    
    next_page_info = queries.get("nextPage", [])

    if next_page_info:
        return next_page_info[0].get("startIndex")
    
    return None  # No more pages available

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/search", methods=["GET"])
def search():
    """Handles search requests."""
    query = request.args.get("q", "")
    start = request.args.get("start", 1, type=int)

    if not query:
        return jsonify({"error": "No search query provided"}), 400
    
    results, next_start = google_search(query, start)
    return jsonify({"results": results, "next_start": next_start})

if __name__ == "__main__":
    app.run(debug=True)
