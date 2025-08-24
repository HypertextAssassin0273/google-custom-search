from shared import app, DATA_DIR, MAX_QUERIES
from utils import load_websites_data, load_proxied_domains
from search import fetch_all_results
from flask import request, session, redirect, url_for, jsonify, render_template
from dotenv import dotenv_values
from datetime import timedelta
from werkzeug.middleware.proxy_fix import ProxyFix
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from requests.adapters import HTTPAdapter
from functools import wraps
from re import match, sub
import requests, logging


# Load credentials
CREDENTIALS = dotenv_values(DATA_DIR + "credentials.env")
app.secret_key = CREDENTIALS.get("FLASK_SECRET_KEY")

# Load search engines and API keys (as dictionaries)
search_engines = dotenv_values(DATA_DIR + 'search_engines.env')
api_keys = dotenv_values(DATA_DIR + 'api_keys.env')

# Validate the required environment variables
if not (api_keys and search_engines and CREDENTIALS and len(CREDENTIALS) > 1 and app.secret_key):
    raise Exception("Either any of the required .env files or variables are missing or empty!")

# App configuration (for security and session management)
app.config.update(
    SESSION_COOKIE_SECURE=True,     # use secure cookies (HTTPS only)
    SESSION_COOKIE_HTTPONLY=True,   # prevent JavaScript access to session cookie
    SESSION_COOKIE_SAMESITE='Lax',  # prevent CSRF attacks, 'Lax' is default for modern browsers
    PERMANENT_SESSION_LIFETIME=timedelta(weeks=1)  # set session timeout to 1 week duration
)

# Apply reverse proxy fix
app.wsgi_app = ProxyFix(
    app.wsgi_app,
    x_for=1,    # trust X-Forwarded-For
    x_proto=1,  # trust X-Forwarded-Proto
    x_host=1,   # trust X-Forwarded-Host
    x_port=1    # trust X-Forwarded-Port
)

# Initialize Flask-Limiter (with IP-based rate limiting)
limiter = Limiter(
    key_func=get_remote_address,  # gets real IP address of the client
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
    return jsonify({"error": "Too many login attempts. Try again later."}), 429

@app.errorhandler(404)
def handle_404(e):
    if session.get("logged_in"):
        return render_template("404.html")
    return redirect(url_for("login"))

# Load other data files
websites_data = load_websites_data()
proxied_domains = load_proxied_domains()


@app.route("/login")
def login():
    """Renders the login page."""
    if session.get("logged_in"):
        return redirect(url_for("home"))
    return render_template("login.html")

@app.route("/login", methods=["POST"])
@limiter.limit("10 per hour", deduct_when=lambda response: response.status_code == 200)
def login_submit():
    """Handles login form submission."""
    username = request.form.get("username")
    if username in CREDENTIALS and CREDENTIALS[username] == request.form.get("password"):
        try:  # reset rate limit on successful login, [NOTE]: https://github.com/alisaifee/flask-limiter/issues/189
            storage = limiter.storage.storage
            pattern = f'LIMITS:LIMITER/{request.remote_addr}/*'
            # app.logger.info(f"\n\n[DEBUG]: remote_address={request.remote_addr},\n---\n"
            #                 f"redis_keys={list(storage.scan_iter(pattern))}\n----------\n")
            for key in storage.scan_iter(pattern):
                storage.delete(key)
        except Exception as e:
            app.logger.error(f"\n\n[ERROR]: resetting rate limit for IP {request.remote_addr}: {e}\n----------\n")
        session.permanent = True  # persist even when browser restarts
        session["logged_in"] = True
        session["user"] = username  # [NOTE]: kept for audit purposes, can be used later for user-specific settings
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
    session.clear()  # [NOTE]: we may need to implement a proper logout mechanism later, testing also required
    return redirect(url_for("login"))

@app.route("/")
@login_required
def home():
    """Renders the home page."""
    return render_template("index.html")

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

@app.route('/dev/reload')  # [NOTE]: in testing, not complete
@login_required
def reload_settings():
    global search_engines, api_keys, proxied_domains, websites_data
    search_engines = dotenv_values(DATA_DIR + 'search_engines.env')
    api_keys = dotenv_values(DATA_DIR + 'api_keys.env')
    proxied_domains = load_proxied_domains()
    websites_data = load_websites_data()
    return jsonify({'success': True})

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
