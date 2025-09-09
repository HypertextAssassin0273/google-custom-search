from flask import Flask

# Fixed limits for custom search API
MAX_RESULTS, MAX_QUERIES = 10, 10

# Initialize Flask app
app = Flask(__name__)
