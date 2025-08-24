from os.path import join, dirname, abspath, exists
from flask import Flask

MAX_RESULTS, MAX_QUERIES = 10, 10  # fixed limits for custom search API

# Set directory for data files
DATA_DIR = join(dirname(abspath(__file__)), 'data', '')  # ensure trailing slash for consistency

# Ensure the data directory exists
if not exists(DATA_DIR):
    raise Exception(f"Data directory '{DATA_DIR}' does not exist.")

# Initialize Flask app
app = Flask(__name__)
