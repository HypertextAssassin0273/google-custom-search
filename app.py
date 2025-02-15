from flask import Flask, request, jsonify, render_template
from dotenv import load_dotenv
import os, requests

app = Flask(__name__)

load_dotenv()
API_KEY = os.getenv("API_KEY")  # your_api_key
SEARCH_ENGINE_ID = os.getenv("SEARCH_ENGINE_ID")  # your_search_engine_id

def google_search(query, start=1):
    url = "https://www.googleapis.com/customsearch/v1"
    params = {
        "key": API_KEY,
        "cx": SEARCH_ENGINE_ID,
        "q": query,
        "start": start  # For pagination
    }
    
    response = requests.get(url, params=params)
    results = response.json()
    
    return results.get("items", []), results.get("queries", {}).get("nextPage", [{}])[0].get("start", None)

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/search")
def search():
    query = request.args.get("q", "")
    start = request.args.get("start", 1, type=int)

    if not query:
        return jsonify({"error": "No search query provided"}), 400
    
    results, next_start = google_search(query, start)
    return jsonify({"results": results, "next_start": next_start})

if __name__ == "__main__":
    app.run(debug=True)
