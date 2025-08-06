# Google Custom Search

This is a simple web application that uses the **Google Custom Search API** to search for items on mentioned websites in **selected custom search engine**. 

The results are **grouped** by their corresponding website domain, making it easier for the user to identify the source of the similar search results.

Since the results are **preloaded** (requires proxy support), the user can very quickly preview search results in different pane on the same page, providing a smooth experience. 

## How to run the application?

### 1. Install dependencies
Install **python packages** by running the following command:
```bash
pip install -r requirements.txt
```
**Note:** make sure to have the latest pip version using `pip install --upgrade pip`.

### 2. Set the environment variables
Create `search_engines.env` file in the `data/` directory and set as many **search engines** as you want:
```bash
SEARCH_ENGINE_ID_1='<your_cse_id_1>'
SEARCH_ENGINE_ID_2='<your_cse_id_2>'
...
SEARCH_ENGINE_ID_N='<your_cse_id_N>'
```

Similarly, create `api_keys.env` file in the `data/` directory and set as many **API keys** as you want:

```bash
API_KEY_1='<your_cs_json_api_key_1>'
API_KEY_2='<your_cs_json_api_key_2>'
...
API_KEY_N='<your_cs_json_api_key_N>'
```

**Note:** there is no restriction on naming the environment variables. you can also add spaces in their names, e.g. `'My API Key'='<cs_json_api_key>'`, `'My Search Engine'='<cse_id>'`, etc. the only restriction is that the names should be unique.

#### 2.1. Setup the credentials
Create a `credentials.env` file in the `data/` directory and set the following variables:

```bash
FLASK_SECRET_KEY='<your_flask_secret_key>'
admin='<your_admin_password>'
employee1='<your_employee1_password>'
```

**Note:** generate a secure random string for `FLASK_SECRET_KEY` using `python -c "import secrets; print(secrets.token_hex(32))"`. This will be used to secure the session cookies and other sensitive data in the application.

### 3. Run the script to start the server
```bash
python app.py
```
**Note:** developed on python `3.13.1` version

### 4. Open the browser and go to the following URL
```bash
http://127.0.0.1:5000
```
**Note**: default port is `5000`

## Prerequisites

You need to have atleast one of both **Custom Search JSON API Key** and a **Custom Search Engine ID** to run this application. You can get them from [Google Custom Search](https://developers.google.com/custom-search/v1/overview).


## Additional Features 

### 1. Website Previewer Tab
This application also provides a **website previewer** tab, which allows you to quickly preview the websites imported from an excel file.

You can add websites under different categories in the `websites.xlsx` file. The application will automatically load the websites from the excel file and display them accordingly in the previewer tab.

**Note:** make sure to add `websites.xlsx` file in `data\` directory and ensure that the websites are in the correct format and accessible. otherwise, it will not work correctly.

### 2. Proxy Support (requests user-agent)
If you want to optimize **page-search** results of a specific website, you can add that website's **domain** name in `proxied_websites.txt` file. The application will automatically fetch and cache the proxied content for all the pages of that website.

You can use this feature to fetch some annoying websites faster, cache their content, prevent them from being blocked (by CORS, strict CSP, etc.), and view their content super efficiently.

**Note:** this feature works for both **website previewer** and **search results** tabs.

### 3. Watchdog Support
The application also provides a **watchdog** support, which monitors the changes in **data files** and automatically reloads the changes in the application.

**Note:** currently, it monitors both `.env` files along with `websites.xlsx` and `proxied_websites.txt` files.
