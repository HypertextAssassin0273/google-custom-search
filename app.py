import os, requests, re, json, concurrent.futures
from flask import Flask, request, jsonify, render_template
from playwright.sync_api import sync_playwright
from functools import lru_cache
from dotenv import load_dotenv

app = Flask(__name__)

load_dotenv()
API_KEY = os.getenv("API_KEY")
SEARCH_ENGINE_ID = os.getenv("SEARCH_ENGINE_ID")

MAX_RESULTS, MAX_QUERIES = 10, 10  # [NOTE]: limiting queries for testing purposes
MAX_LIMIT = MAX_RESULTS * MAX_QUERIES 


@lru_cache(maxsize=128) # cache search results
def google_search(query, start, sort_by):
    """Fetch search results from Google Custom Search API."""
    url = "https://www.googleapis.com/customsearch/v1"
    params = {
        "key": API_KEY,
        "cx": SEARCH_ENGINE_ID,
        "q": query,
        "start": start,
        "sort": sort_by,        # "" -> byRelevance, "date" -> byDate
        # "filter": 1,          # removes duplicate results
        # "exactTerms": query,  # forces exact match
    }
    try:
        # Fetch search results (from Google JSON API)
        json_response = requests.get(url, params).json()
        # app.logger.info(f"\n\n[DEBUG]: response={json_response}\n----------\n")

        # Pretty print JSON response (for debugging)
        json_dump = json.dumps(json_response, indent=2)
        app.logger.info(f"\n\n[DEBUG]: response={json_dump}")
        app.logger.info("\n----------\n")

        # Check for Google API specific errors
        if 'error' in json_response:
            log_error_message(json_response)
            return default_types()

        # Extract search results
        results = extract_results(json_response)
        # app.logger.info(f"\n\n[DEBUG]: results={results}\n----------\n")

        # Get next page index, total results count and search time
        next_start = get_next_start(json_response)
        total_results, search_time = extract_from_search_info(json_response)

        return results, next_start, total_results, search_time
    
    except requests.exceptions.RequestException as e:
        app.logger.error(f"\n\n[ERROR]: Request -> {e}\n----------\n")
        return default_types()


def default_types():
    """Returns default values for search results."""
    return [], 0, 0, 0


def log_error_message(json_response):
    """Logs error message from Google API response."""
    error = json_response['error']
    app.logger.error(f"\n\n[ERROR]: GoogleAPI({error['code']}) -> {error['message']}\n----------\n")


def extract_results(json_response):
    """Extracts search results from API response."""
    results = []
    for item in json_response.get("items", []):
        results.append({
            "title": item.get("htmlTitle"),
            "link": item.get("link"),
            "display_link": item.get("displayLink"),
            "snippet": item.get("htmlSnippet"),
            "breadcrumb_trail": extract_breadcrumb_trail(item)
        })
    return results


def get_next_start(json_response):
    """Extracts the next page start index from API response."""
    next_page_info = json_response.get("queries", {}).get("nextPage", [{}])[0]
    return next_page_info.get("startIndex", 0)


def extract_from_search_info(json_response):
    """Extracts required search information from API response."""
    search_info = json_response.get("searchInformation", {})
    return int(search_info.get("totalResults", "0")), round(search_info.get("searchTime", 0), 2)


def extract_breadcrumb_trail(item):
    """Extracts breadcrumb trail from search result."""
    listitem = item.get("pagemap", {}).get("listitem", [])
    # app.logger.info(f"\n\n[DEBUG]: listitem={listitem}\n----------\n")

    if listitem:
        trail = [li.get("name") for li in listitem[:-1]]  # excludes last item (current page)
        trail.insert(0, item.get("displayLink"))          # insert domain as first item
        return " > ".join(trail)
    
    else: # Construct trail from URL as fallback
        url_part = re.sub(r'https?://', '', item.get("link"))         # remove protocol
        trail = re.sub(r'(.*?)(\?|\.php|\.html).*', r'\1', url_part)  # remove query params & file extension
        # app.logger.info(f"\n\n[DEBUG]: url={url_part}, trail={trail}\n----------\n")
        return refine_breadcrumb_trail(trail.split("/"))


def refine_breadcrumb_trail(segments):
    """Refines breadcrumb trail segments."""
    def __format(segment, value="..."): return value if len(segment) > 30 else segment
    formatted_segments = [__format(segment) for segment in segments[:-1]]

    if segments:
        # formatted_segments.append(segments[-1])         # don't modify last segment
        formatted_segments.append(__format(segments[-1],  # truncate last segment
                                           segments[-1][:30] + "..."))
    return " > ".join(formatted_segments)


# def fetch_all_results_in_serial(query, sort_by):  # [NOTE]: for testing purposes as fallback
#     """Fetch search results sequentially using pagination."""
#     all_results = []
#     total_results, total_search_time = 0, 0
#     next_start = 1
    
#     while next_start and len(all_results) < MAX_LIMIT:
#         results, next_start, total_results, search_time = google_search(query, next_start, sort_by)
#         # app.logger.info(f"\n\n[DEBUG]: start={next_start}, results_count={len(results)}\n----------\n")
        
#         # Add results to our collection
#         all_results.extend(results)
#         total_search_time += search_time
    
#     return all_results, total_results, round(total_search_time, 2)


def fetch_all_results(query, sort_by):  # [NOTE]: needs more testing
    """Fetch search results dynamically using parallel requests in threads."""
    # First, make a single request to get initial results and total count
    results, next_start, total_results, search_time = google_search(query, 1, sort_by)
    results_map = {1: results}  # store first page results
    total_search_time = search_time
    
    # Calculate remaining pages to fetch
    remaining_pages = min(MAX_QUERIES - 1, (total_results - 1) // MAX_RESULTS)
    # app.logger.info(f"\n\n[DEBUG]: remaining_pages={remaining_pages}\n----------\n")
    
    # Fetch remaining pages in parallel
    if remaining_pages and next_start:
        with concurrent.futures.ThreadPoolExecutor() as executor:
            remaining_indices = [next_start + i * MAX_RESULTS for i in range(remaining_pages)]
            futures = { 
                executor.submit(google_search, query, start, sort_by): start 
                for start in remaining_indices
            }
            for future in concurrent.futures.as_completed(futures):
                start = futures[future]  # get the corresponding start index
                try:
                    results, _, _, page_search_time = future.result()
                    results_map[start] = results  # store results under their start index
                    total_search_time += page_search_time
                
                except Exception as e:
                    app.logger.error(f"\n\n[ERROR]: future.result() -> {e}\n----------\n")
    
    # Combine all results in order (based on start index)
    all_results = []
    for start in sorted(results_map.keys()):
        all_results.extend(results_map[start])
    
    return all_results, total_results, round(total_search_time, 2)


@lru_cache(maxsize=128)  # cache proxy responses
def fetch_proxy_content(url):
    """Fetch and return page content using a proxy server to avoid CORS issues."""
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_extra_http_headers({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5"
            })
            page.goto(url)
            page.wait_for_timeout(30000)  # wait 10s for JS to execute
            html = page.content()
            browser.close()
            
            # Fix relative links by injecting <base> tag in <head> section of HTML
            domain = re.match(r"https?://[^/]+", url).group(0)  # extract base domain
            html = re.sub(r"(<head[^>]*>)", rf"\1<base href='{domain}/'>", html, count=1)
            return html, 200

    except Exception as e:
        app.logger.error(f"[ERROR]: PlaywrightException -> {e}")
        return f"Error fetching page: {e}", 500


@app.route("/")
def home():
    """Renders the home page."""
    return render_template("index.html")


@app.route("/search")
def search():
    """Handles search requests."""
    query = request.args.get("q", "")
    sort_by = request.args.get("sort_by", "")
    # app.logger.info(f"\n\n[DEBUG]: query={query}, sort_by={sort_by}\n----------\n")

    if not query:
        return jsonify({"error": "No search query provided"}), 400
    
    results, total_results, search_time = fetch_all_results(query, sort_by)
    
    return jsonify({
        "results": results,
        "total_results": total_results,
        "search_time": search_time
    })


@app.route("/proxy")
def proxy():
    """Handles proxy requests."""
    url = request.args.get("url")
    if not url:
        return "Error: No URL provided", 400
    
    return fetch_proxy_content(url)


if __name__ == "__main__":
    app.run(debug=True)
