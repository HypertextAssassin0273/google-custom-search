from flask import Flask
from os import path
import logging

# Fixed limits for custom search API
MAX_RESULTS, MAX_QUERIES = 10, 10

# Initialize Flask app
app = Flask(__name__)

# Configure app logging
logging.basicConfig(level=logging.INFO)

# Set directory for data files
DATA_DIR = path.join(path.dirname(path.abspath(__file__)), 'data', '')  # ensure trailing slash for consistency

# Set paths for various data files
ENG_PATH = DATA_DIR + 'search_engines.env'
API_PATH = DATA_DIR + 'api_keys.env'
WEB_PATH = DATA_DIR + 'websites.xlsx'
DOM_PATH = DATA_DIR + 'proxied_domains.txt'
