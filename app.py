from flask import Flask, request, jsonify, render_template
from dotenv import load_dotenv
import os, requests
# import json # [TEMP]

app = Flask(__name__)

load_dotenv()
API_KEY = os.getenv("API_KEY")
SEARCH_ENGINE_ID = os.getenv("SEARCH_ENGINE_ID")


def google_search(query, start, sort_by):
    """Fetch search results from Google Custom Search API."""
    url = "https://www.googleapis.com/customsearch/v1"
    params = {
        "key": API_KEY,
        "cx": SEARCH_ENGINE_ID,
        "q": query,
        "start": start,
        "sort": sort_by,       # [INFO]: "" -> byRelevance, "date" -> byDate
        # "exactTerms": query, # [INFO]: forces exact match
        # "filter": 1,         # [INFO]: removes duplicate results
    }
    try:
        # Fetch search results (from Google JSON API)
        json_response = requests.get(url, params).json()

        # [TEMP]: Pretty print JSON response
        # json_dump = json.dumps(json_response, indent=2)
        # app.logger.info(f"\n\n[DEBUG]: response={json_dump}\n----------\n")

        # Check for Google API specific errors
        if 'error' in json_response:
            log_error_message(json_response)
            return default_types()

        # Extract search results
        results = extract_results(json_response)
        app.logger.info(f"\n\n[DEBUG]: results={results}\n----------\n")

        # Get next page index, total results count and search time
        next_start = get_next_start(json_response)
        total_results, search_time = extract_from_search_info(json_response)

        return results, next_start, total_results, search_time
    
    except requests.exceptions.RequestException as e:
        app.logger.error(f"\n\n[ERROR]: Request -> {e}\n----------\n")
        return default_types()


def default_types():
    """Returns default values for search results."""
    return [], None, 0, 0

def log_error_message(json_response):
    """Logs error message from Google API response."""
    error = json_response['error']
    app.logger.error(f"\n\n[ERROR]: GoogleAPI ({error['code']}) -> {error['message']}\n----------\n")

def extract_results(json_response):
    """Extracts search results from API response."""
    results = []
    for item in json_response.get("items", []):
        results.append({
            "title": item.get("htmlTitle"),
            "link": item.get("link"),
            "display_link": item.get("displayLink"),
            "snippet": item.get("htmlSnippet")
        })
    return results

def get_next_start(json_response):
    """Extracts the next page start index from API response."""
    next_page_info = json_response.get("queries", {}).get("nextPage", [{}])[0]
    return next_page_info.get("startIndex", None)

def extract_from_search_info(json_response):
    """Extracts required search information from API response."""
    search_info = json_response.get("searchInformation", {})
    return search_info.get("totalResults", 0), round(search_info.get("searchTime", 0), 2)


@app.route("/")
def home():
    """Renders the home page."""
    return render_template("index.html")

@app.route("/search")
def search():
    """Handles search requests."""
    query = request.args.get("q", "")
    start = request.args.get("start", 1, type=int)
    sort_by = request.args.get("sort_by", "")
    # app.logger.info(f"\n\n[DEBUG]: query={query}, start={start}, sort_by={sort_by}\n----------\n")

    if not query:
        return jsonify({"error": "No search query provided"}), 400
    
    results, next_start, total_results, search_time = google_search(query, start, sort_by)
    
    return jsonify({
        "results": results,
        "next_start": next_start if next_start <= 100 else None,  # [INFO]: to disable next button if >100
        "total_results": total_results,
        "search_time": search_time
    })


if __name__ == "__main__":
    app.run(debug=True)
