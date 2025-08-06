from flask import Flask, request, session, redirect, url_for, jsonify, render_template
import requests, concurrent.futures, pandas as pd, atexit, logging
from flask_limiter.util import get_remote_address
from flask_limiter import Limiter
from watchdog.events import FileSystemEventHandler
from watchdog.observers.polling import PollingObserver
from threading import Thread, Event
from datetime import timedelta
from dotenv import dotenv_values
from functools import wraps
from time import sleep
from os import path
from re import sub, match
# from json import dumps


MAX_RESULTS = 10  # maximum results per page

# Set directory for data files
DATA_DIR = path.join(path.dirname(path.abspath(__file__)), 'data', '')  # ensure trailing slash for consistency

# Ensure the data directory exists
if not path.exists(DATA_DIR):
    raise FileNotFoundError(f"Data directory '{DATA_DIR}' does not exist.")

# Initialize Flask app
app = Flask(__name__)

# App configuration
app.config.update(
    SESSION_COOKIE_SECURE=True,     # work only with HTTPS [production only]
    SESSION_COOKIE_HTTPONLY=True,   # prevent JavaScript access to session cookie
    SESSION_COOKIE_SAMESITE='Lax',  # prevent CSRF attacks, 'Lax' is default for modern browsers
    PERMANENT_SESSION_LIFETIME=timedelta(minutes=60)  # set session timeout to 1 hour
)

# Refresh the session
@app.before_request
def refresh_session_timeout():
    session.modified = True  # resets the session timeout on each request/activity

# Handle rate limit exceeded error
@app.errorhandler(429)
def ratelimit_handler(e):
    return "Too many login attempts. Try again later.", 429

# Handle 404 errors
@app.errorhandler(404)
def handle_404(e):
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    return render_template("404.html"), 404

# Configure logging
logging.basicConfig(level=logging.INFO)
app.logger.setLevel(logging.INFO)

# Load credentials
CREDENTIALS = dotenv_values(DATA_DIR + "credentials.env")
app.secret_key = CREDENTIALS.get("FLASK_SECRET_KEY")

# Load search engines and API keys from separate .env files as dictionaries
search_engines = dotenv_values(DATA_DIR + 'search_engines.env')
api_keys = dotenv_values(DATA_DIR + 'api_keys.env')

# Validate that the required environment variables are set
if not (api_keys and search_engines and CREDENTIALS and len(CREDENTIALS) > 1 and app.secret_key):
    raise ValueError("Either any of the required .env files or variables are missing or empty!")

# Initialize Flask-Limiter with IP-based rate limiting
limiter = Limiter(
    key_func=get_remote_address,  # gets real IP address of the client
    app=app,
    storage_uri="memory://",  # in-memory storage [for 1 gunicorn-worker only]
    default_limits=[]
)


# Helper functions to load data from files
def load_websites_data():
    """Load websites data from websites.xlsx."""
    try:
        # Read Excel file with multiple sheets
        with pd.ExcelFile(DATA_DIR + 'websites.xlsx') as xl:  # context manager ensures file is closed
            categories = {}
            # Process each sheet as a category
            for sheet_name in xl.sheet_names:
                df = pd.read_excel(xl, sheet_name=sheet_name)
                # Ensure columns exist and clean data
                if 'Website Name' in df.columns and 'Website Link' in df.columns:
                    websites = [
                        {"title": row['Website Name'], "link": row['Website Link']}
                        for _, row in df.iterrows()
                        if pd.notna(row['Website Name']) and pd.notna(row['Website Link'])
                    ]
                    categories[sheet_name] = {
                        "websites": websites,
                        "max_limit": len(websites)  # dynamic max limit per category
                    }
            return {"categories": categories, "default_category": list(categories.keys())[0] if categories else None}
    
    except Exception as e:
        app.logger.error(f"\n\n[ERROR]: Loading websites -> {e}\n----------\n")
        return {"categories": {}, "default_category": None}


def load_proxied_domains_data():
    """Load proxied domains from proxied_websites.txt."""
    try:
        with open(DATA_DIR + 'proxied_websites.txt', 'r') as f:
            return [line.strip() for line in f if line.strip()]
    
    except Exception as e:
        app.logger.error(f"\n\n[ERROR]: Loading proxied domains -> {e}\n----------\n")
        return []


# Initialize global file states
websites_data = load_websites_data()
proxied_domains = load_proxied_domains_data()

# Initialize watchdog
observer = PollingObserver()
running = Event()  # flag to control thread lifecycle


# Watchdog handler to fetch changes on any file in the data directory
class WatchdogFileHandler(FileSystemEventHandler):
    """Handles file system events for the watchdog observer."""
    def on_modified(self, event):
        file_path = event.src_path
        # app.logger.info(f"\n\n[DEBUG]: Event 'modified' detected - Path: {file_path}\n----------\n")

        if file_path.endswith('search_engines.env'):
            global search_engines
            search_engines = dotenv_values(DATA_DIR + 'search_engines.env')
            app.logger.info(f" Reloaded search_engines.env: {search_engines}")
        
        elif file_path.endswith('api_keys.env'):
            global api_keys
            api_keys = dotenv_values(DATA_DIR + 'api_keys.env')
            app.logger.info(f" Reloaded api_keys.env: {api_keys}")
        
        elif file_path.endswith('proxied_websites.txt'):
            global proxied_domains
            proxied_domains = load_proxied_domains_data()
            app.logger.info(f" Reloaded proxied_websites.txt: {len(proxied_domains)} domains")
    
    def on_created(self, event):
        if '~$' in event.src_path: return  # ignore temporary files (created by Excel)
        # app.logger.info(f"\n\n[DEBUG]: Event 'created' detected - Path: {event.src_path}\n----------\n")
        self.handle_websites_file(event.src_path)
    
    def on_moved(self, event):
        # app.logger.info(f"\n\n[DEBUG]: Event 'moved' detected - Path: {event.dest_path}\n----------\n")
        self.handle_websites_file(event.dest_path)
    
    @staticmethod
    def handle_websites_file(path):
        """Handle the websites file specifically."""
        if path.endswith('websites.xlsx'):
            global websites_data
            websites_data = load_websites_data()
            app.logger.info(f" Reloaded websites.xlsx: {len(websites_data.get('categories', {}))} categories")


def start_watchdog():
    """Start the watchdog observer in a separate thread to monitor files in data directory."""
    # app.logger.info("[DEBUG]: Attempting to start watchdog thread")
    try:
        observer.schedule(event_handler=WatchdogFileHandler(), path=DATA_DIR)
        observer.start()
        running.set()  # mark as running
        app.logger.info(" Started watchdog observer for data files")

        while running.is_set():
            sleep(1)  # keep thread alive
    
    except Exception as e:
        app.logger.error(f" Error in watchdog thread: {e}")

    finally:
        observer.stop()
        observer.join()
        app.logger.info(" Watchdog observer stopped")


def stop_watchdog():
    """Stop the watchdog observer and clean up resources."""
    if running.is_set():
        running.clear()  # signal thread to stop
        observer.stop()
        observer.join()
        app.logger.info(" Watchdog shutdown via atexit")
    
    # Join the thread if it exists
    watchdog_thread = app.config.get('WATCHDOG_THREAD')
    if watchdog_thread and watchdog_thread.is_alive():
        watchdog_thread.join()


# Register shutdown hook to ensure watchdog stops on exit
atexit.register(stop_watchdog)

# Start watchdog in a separate daemon thread
watchdog_thread = Thread(target=start_watchdog, daemon=True)
watchdog_thread.start()
app.config['WATCHDOG_THREAD'] = watchdog_thread  # store thread for shutdown


def google_search(api_key, search_engine_id, query, start, sort_by):
    """Fetch search results from Google Custom Search API."""
    url = "https://www.googleapis.com/customsearch/v1"
    params = {
        "key": api_key,
        "cx": search_engine_id,
        "q": query,
        "start": start,           # 1 -> first page, 11 -> second page, etc
        "sort": sort_by,          # "" -> by Relevance, "date" -> by Date
        # "filter": 1,            # removes duplicate results
        # "exactTerms": query,    # forces exact match
    }
    # app.logger.info(f"\n\n[DEBUG]: start={start}\n----------\n")
    try:
        # Fetch search results (from Google JSON API)
        json_response = requests.get(url, params).json()
        # app.logger.info(f"\n\n[DEBUG]: response={json_response}\n----------\n")

        # Pretty print JSON response (for debugging)
        # json_dump = dumps(json_response, indent=2)
        # app.logger.info(f"\n\n[DEBUG]: response={json_dump}")
        # app.logger.info("\n----------\n")

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
        app.logger.error(f"\n\n[ERROR]: Search Request -> {e}\n----------\n")
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
        url_part = sub(r'https?://', '', item.get("link"))         # remove protocol
        trail = sub(r'(.*?)(\?|\.php|\.html).*', r'\1', url_part)  # remove query params & file extension
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


def fetch_all_results(api_key, search_engine_id, query, sort_by, max_queries):
    """Fetch search results for a query dynamically using parallel requests."""
    # First, make a single request to get initial results and total count
    results, next_start, total_results, search_time = google_search(api_key, search_engine_id, query, 1, sort_by)
    results_map = {1: results}  # store first page results
    total_search_time = search_time
    
    # Calculate remaining pages to fetch
    remaining_pages = min(max_queries - 1, (total_results - 1) // MAX_RESULTS)
    # app.logger.info(f"\n\n[DEBUG]: remaining_pages={remaining_pages}\n----------\n")
    
    # Fetch remaining pages in parallel
    if remaining_pages and next_start:
        with concurrent.futures.ThreadPoolExecutor() as executor:
            remaining_indices = [next_start + i * MAX_RESULTS for i in range(remaining_pages)]
            futures = { 
                executor.submit(google_search, api_key, search_engine_id, query, start, sort_by): start 
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


def login_required(f):
    """Decorator to ensure user is logged in before accessing certain routes."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


@app.route("/login", methods=["GET", "POST"])
@limiter.limit("5 per minute")  #  5 attempts per minute per IP
def login():
    """Handles user login."""
    # Redirect to home if already logged in
    if session.get("logged_in"):
        return redirect(url_for("home"))

    error = ""
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        if username in CREDENTIALS and CREDENTIALS[username] == password:
            session.permanent = True  # activates TTL
            session["logged_in"] = True
            session["user"] = username
            return redirect(url_for("home"))
        else:
            error = "Invalid username or password."

    return render_template("login.html", error=error)


@app.route("/logout")  # [NOTE]: not used currently, but can be used for future logout functionality
def logout():
    """Handles user logout."""
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def home():
    """Renders the home page."""
    return render_template("index.html")


@app.route("/search")
@login_required
def search():
    """Handles search requests."""
    api_key = api_keys.get(request.args.get("apiKey"))
    search_engine_id = search_engines.get(request.args.get("searchEngine"))
    query = request.args.get("query")
    sort_by = request.args.get("sortBy", "")
    max_queries = int(request.args.get("maxQueries", 1))
    # app.logger.info(f"\n\n[DEBUG]: api_key= {api_key}, search_engine_id= {search_engine_id}, "
    #                 f"query={query}, sort_by={sort_by}, max_queries={max_queries}\n----------\n")

    if not all([api_key, search_engine_id, query]):
        return jsonify({"error": "Invalid or missing parameters"}), 400
    
    results, total_results, search_time = fetch_all_results(api_key, search_engine_id, query, sort_by, max_queries)
    
    return jsonify({
        "results": results,
        "total_results": total_results,
        "search_time": search_time
    })


@app.route("/proxy")
@login_required
def proxy():
    """Proxy endpoint to fetch and serve pages to bypass CORS issues."""
    url = request.args.get("url")
    if not url:
        return "Error: No URL provided", 400
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5"
    }
    try:
        response = requests.get(url, headers=headers, timeout=10) # [NOTE]: timeout & headers may need to be adjusted (for edge cases)
        response.raise_for_status()  # raises HTTPError for 4xx/5xx statuses
        
        html = response.text
        domain = match(r"https?://[^/]+", url).group(0)  # extract base domain

        # Fix relative links by injecting <base> tag in <head> section of HTML
        html = sub(r"(<head[^>]*>)", rf"\1<base href='{domain}/'>", html, count=1)

        return html
    
    except requests.exceptions.RequestException as e:
        app.logger.error(f"\n\n[ERROR]: Proxy -> {e}\n----------\n")
        return f"Error fetching page: {e}", 500


@app.route("/import_websites")
@login_required
def import_websites():
    """Import websites from a .xlsx file and return categorized data."""
    return jsonify(websites_data)


@app.route("/proxied_domains")
@login_required
def get_proxied_domains():
    """Fetch proxied websites domain from a text file."""
    return jsonify(proxied_domains)


@app.route('/get_settings_options')
@login_required
def get_settings_options():
    """Return available search engine and API key names only from .env files."""
    return jsonify({
        'searchEngines': list(search_engines.keys()),
        'apiKeys': list(api_keys.keys())
    })


# [NOTE]: deprecated for updating search engine and API key, will be redesigned later for updatig entries for add/delete operations in specific files
# @app.route('/update_settings', methods=['POST'])
# @login_required
# def update_settings():
#     """Update global settings based on user input."""
#     global MAX_QUERIES
#     try:
#         data = request.get_json()
#         MAX_QUERIES = int(data['maxQueries'])
        
#         # app.logger.info(f"\n\n[DEBUG]: maxQueries={MAX_QUERIES}\n----------\n")
#         return jsonify({'success': True})
    
#     except Exception as e:
#         app.logger.error(f"\n\n[ERROR]: Updating settings -> {e}\n----------\n")
#         return jsonify({'success': False, 'error': str(e)}), 500


if __name__ == "__main__":
    """Main entry point for the Flask application on development server (for testing purposes)."""
    app.run()
