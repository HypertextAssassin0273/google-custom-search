# Google Custom Search

This is a simple web application that uses the **Google Custom Search API** to search for items on mentioned websites in **selected custom search engine**. 

The results are **grouped** by their corresponding website domain, making it easier for the user to identify the source of the similar search results.

Since the results are **preloaded**, the user can very quickly preview search results in different pane on the same page, providing a smooth experience.

## How to run the application:

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Run the script to start the server
```bash
python app.py
```

### 3. Open the browser and go to the following URL
```bash
http://127.0.0.1:5000
```
**Note**: default port is `5000`

## Prerequisites

You need to have a **Google Custom Search API key** and a **Custom Search Engine ID** to run this application. You can get them from [Google Custom Search](https://developers.google.com/custom-search/v1/overview).
