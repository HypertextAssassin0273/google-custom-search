from shared import app, MAX_QUERIES
from utils import load_websites_data, load_proxied_domains, clear_rate_limits, signal_workers
from search import fetch_all_results
from flask import request, session, redirect, url_for, jsonify, render_template, send_file
from werkzeug.exceptions import RequestEntityTooLarge
from dotenv import dotenv_values
from datetime import timedelta
from flask_limiter import Limiter
from requests.adapters import HTTPAdapter
from functools import wraps
from re import match, sub
from os import chmod, path
from sys import platform
import requests, logging, uuid


# Set directory for data files
DATA_DIR = path.join(path.dirname(path.abspath(__file__)), 'data', '')  # ensure trailing slash for consistency

# Load credentials
credentials = dotenv_values(DATA_DIR + "credentials.env")
app.secret_key = credentials.get("FLASK_SECRET_KEY")

# Load search engines and API keys (as dictionaries)
search_engines = dotenv_values(DATA_DIR + 'search_engines.env')
api_keys = dotenv_values(DATA_DIR + 'api_keys.env')

# Validate the required environment variables
if not (api_keys and search_engines and credentials and len(credentials) > 1 and app.secret_key):
    raise Exception("Either any of the required .env files or variables are missing or empty!")

# App configuration (for security and session management)
app.config.update(
    MAX_CONTENT_LENGTH=16*1024*1024,  # 16MB limit on incoming request data (file uploads)
    SESSION_COOKIE_SECURE=True,       # use secure cookies (HTTPS only)
    SESSION_COOKIE_HTTPONLY=True,     # prevent JavaScript access to session cookie
    SESSION_COOKIE_SAMESITE='Lax',    # prevent CSRF attacks, 'Lax' is default for modern browsers
    PERMANENT_SESSION_LIFETIME=timedelta(weeks=1)  # set session timeout to 1 week duration
)

# Create a custom key function for session-based rate limiting
def get_rate_limit_key():
    """Generate a unique key for rate limiting based on session ID."""
    if 'rate_limit_id' not in session:
        session['rate_limit_id'] = str(uuid.uuid4())
    return f"session:{session['rate_limit_id']}"

# Initialize Flask-Limiter (with session-based rate limiting)
limiter = Limiter(
    key_func=get_rate_limit_key,
    app=app,
    storage_uri="redis://127.0.0.1:6379"  # use redis-server to enforce consistent limits across multiple workers
)

# Configure logging
logging.basicConfig(level=logging.INFO)
limiter.logger.setLevel(logging.ERROR)

# Create optimized HTTP session for proxy requests
proxy_session = requests.Session()
adapter = HTTPAdapter(
    pool_connections=20,  # maps unique domains
    pool_maxsize=40       # maps connections per domain
)
proxy_session.mount("http://", adapter)  # [NOTE]: will be removed if no non-secure websites are present in CSE
proxy_session.mount("https://", adapter)

# Error response handlers
@app.errorhandler(429)
def handle_429(e):
    return jsonify({"error": "Too many attempts. Try again later."}), 429

@app.errorhandler(404)
def handle_404(e):
    if session.get("logged_in"):
        return render_template("404.html")
    return redirect(url_for("login"))

# Load other data files
websites_data = load_websites_data(DATA_DIR + 'websites.xlsx')
proxied_domains = load_proxied_domains(DATA_DIR + 'proxied_websites.txt')


@app.route("/login")
def login():
    """Renders the login page."""
    if session.get("logged_in"):
        return redirect(url_for("home"))
    return render_template("login.html")

@app.route("/login", methods=["POST"])
@limiter.limit("10 per hour")  # 10 attempts allowed per hour per session
def login_submit():
    """Handles login form submission."""
    username = request.form.get("username")
    if username in credentials and credentials[username] == request.form.get("password"):
        clear_rate_limits(limiter.storage.storage, session.get('rate_limit_id', ''))
        session.permanent = True  # persist even when browser restarts
        session["logged_in"] = True
        session["user"] = username
        return redirect(url_for("home"))
    return jsonify({"error": "Invalid username or password."})

def login_required(f):
    """Decorator to ensure user is logged in before accessing certain routes."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if session.get("logged_in"):
            return f(*args, **kwargs)
        return redirect(url_for("login"))
    return wrapper

@app.route("/logout")  # [NOTE]: not used currently, but can be used for future logout functionality
@login_required
def logout():
    """Handles user logout."""
    session.clear()  # [NOTE]: we may need to implement a more robust logout mechanism later
    return redirect(url_for("login"))

@app.route("/")
@login_required
def home():
    """Renders the home page."""
    return render_template("index.html")

@app.route("/get_websites")
@login_required
def get_websites():
    """Fetch websites from a .xlsx file and return categorized data."""
    return jsonify(websites_data)

@app.route("/get_proxied_domains")
@login_required
def get_proxied_domains():
    """Fetch proxied websites domain from a text file."""
    return jsonify(proxied_domains)

@app.route('/get_settings_options')
@login_required
def get_settings_options():
    """Fetch available search engine and API key names only from .env files."""
    return jsonify({
        'searchEngines': list(search_engines.keys()),
        'apiKeys': list(api_keys.keys())
    })

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
    if not (api_key and search_engine_id) or max_queries > MAX_QUERIES:
        return jsonify({"error": "Invalid or missing required parameters"}), 400
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
        response = proxy_session.get(url, headers=headers, timeout=10) # [NOTE]: timeout may need some adjustments (for edge cases)
        response.raise_for_status()  # raises HTTPError for 4xx/5xx statuses
        domain = match(r"https?://[^/]+", url).group(0)  # extract base domain
        return sub(r"(<head[^>]*>)", rf"\1<base href='{domain}/'>", response.text, count=1) # fix relative links by injecting <base> tag
    except Exception as e:
        app.logger.error(f"\n\n[ERROR]: proxy -> {e}\n----------\n")
        return f"Error fetching page", 500

@app.route("/import_websites", methods=["POST"])
@login_required
def import_websites():
    """Import and replace websites.xlsx file with proper permissions."""
    try:
        if 'file' not in request.files:
            return jsonify({"error": "No file provided."}), 400
        file = request.files['file']
        if file.filename == '' or file.filename != 'websites.xlsx':
            return jsonify({"error": "Invalid or missing websites.xlsx file."}), 400
        websites_file = DATA_DIR + 'websites.xlsx'
        file.save(websites_file)   # replace existing file
        if not platform.startswith('win'):  # [[DEV-ENV-GUARD]]
            from os import getuid, getgid, chown
            chown(websites_file, getuid(), getgid())  # ubuntu:ubuntu ownership
            chmod(websites_file, 0o640)  # set proper permissions
        temp_data = load_websites_data(websites_file)
        if not temp_data['categories']:
            return jsonify({"error": "Invalid or empty websites.xlsx file."}), 400
        global websites_data; websites_data = temp_data
        signal_workers()  # notify workers to reload data
        return jsonify({"success": True})
    except RequestEntityTooLarge:
        return jsonify({"error": ".xlsx file too large (max 16MB)"}), 413
    except Exception as e:
        app.logger.error(f"\n\n[ERROR]: importing websites -> {e}\n----------\n")
        return jsonify({"error": str(e)}), 500

@app.route("/export_websites")
@login_required
def export_websites():
    """Export websites.xlsx file for download."""
    file = DATA_DIR + 'websites.xlsx'
    if path.exists(file): return send_file(file, as_attachment=True)
    return jsonify({"error": "websites.xlsx file not found"}), 404

@app.route('/dev/reload/<data>')  # [NOTE]: for development/testing purposes only
@login_required
def reload(data):
    """Reload specific data source and update global variable."""
    global search_engines, api_keys, websites_data, proxied_domains
    match data:
        case 'search_engines': 
            payload = search_engines = dotenv_values(DATA_DIR + 'search_engines.env')
        case 'api_keys':
            payload = api_keys = dotenv_values(DATA_DIR + 'api_keys.env')
        case 'websites':
            payload = websites_data = load_websites_data(DATA_DIR + 'websites.xlsx')
        case 'proxied_domains':
            payload = proxied_domains = load_proxied_domains(DATA_DIR + 'proxied_websites.txt')
        case _:
            return jsonify({"error": "Invalid data source specified"}), 400
    signal_workers()
    return jsonify(payload)

# [NOTE]: deprecated, will be redesigned later for updating entries for add/delete operations in specific files
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
#         app.logger.error(f"\n\n[ERROR]: updating settings -> {e}\n----------\n")
#         return jsonify({'success': False, 'error': str(e)}), 500


if __name__ == "__main__":
    """Main entry point for the Flask application on development server (for testing purposes)."""
    app.run()
