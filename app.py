from flask import Flask, request, jsonify, render_template
from dotenv import load_dotenv
import os, requests

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
        "sort": sort_by, # "" -> byRelevance, "date" -> byDate
        # "exactTerms": query, # Forces exact match
        # "filter": 1, # Removes duplicate results
    }

    # Fetch search results
    json_response = requests.get(url, params).json() 
    # app.logger.info(f"\n\n[DEBUG]: response={json_response}\n----------\n")

    # Extract search results
    results = extract_results(json_response)
    app.logger.info(f"\n\n[DEBUG]: results={results}\n----------\n")

    # Get next page index
    next_start = get_next_start(json_response)
    # app.logger.info(f"\n\n[DEBUG]: next_start={next_start}\n----------\n")

    # Get total results count and search time
    total_results, search_time = extract_from_search_info(json_response)
    # app.logger.info(f"\n\n[DEBUG]: total_results={total_results}, search_time={search_time}\n----------\n")

    return results, next_start, total_results, search_time


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
        # app.logger.info(f"\n\n[DEBUG]: item keys={item.keys()}\n----------\n")
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
        "next_start": next_start if next_start and next_start <= 100 else None,  # Disable Next if >100
        "total_results": total_results,
        "search_time": search_time
    })


if __name__ == "__main__":
    app.run(debug=True)
