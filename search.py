from shared import app, MAX_RESULTS
from concurrent.futures import ThreadPoolExecutor, as_completed
# from json import dump
from re import sub
import requests

def google_search(api_key, search_engine_id, query, start, sort_by):
    """Fetch search results from Google Custom Search JSON API."""
    url = "https://www.googleapis.com/customsearch/v1"
    params = {
        "key": api_key,
        "cx": search_engine_id,
        "q": query,
        "start": start,         # 1 -> first page, 11 -> second page, etc
        "sort": sort_by,        # "" -> by Relevance, "date" -> by Date
        # "filter": 1,          # removes duplicate results
        # "exactTerms": query,  # forces exact match
    }
    # app.logger.info(f"\n\n[DEBUG]: start={start}\n----------\n")
    try:
        json_response = requests.get(url, params).json()
        # json_dump = dumps(json_response, indent=2)  # pretty print JSON response (for debugging)
        # app.logger.info(f"\n\n[DEBUG]: response={json_dump}\n----------\n")  # OR directly log: json_response
        if 'error' in json_response:  # check for google API specific errors
            error = json_response['error']
            raise Exception(f"GoogleAPI({error['code']}), {error['message']}")
        results = extract_results(json_response)
        # app.logger.info(f"\n\n[DEBUG]: results={results}\n----------\n")
        next_start = get_next_start(json_response)
        total_results, search_time = extract_search_info(json_response)
        return results, next_start, total_results, search_time
    except Exception as e:
        app.logger.error(f"\n\n[ERROR]: search -> {e}\n----------\n")
        return [], 0, 0, 0

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

def extract_search_info(json_response):
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
    else:  # construct trail from URL as fallback
        url_part = sub(r'https?://', '', item.get("link"))         # remove protocol
        trail = sub(r'(.*?)(\?|\.php|\.html).*', r'\1', url_part)  # remove query params & file extension
        # app.logger.info(f"\n\n[DEBUG]: url={url_part}, trail={trail}\n----------\n")
        return refine_breadcrumb_trail(trail.split("/"))

def refine_breadcrumb_trail(segments):
    """Refines breadcrumb trail segments."""
    def __format(segment, value="..."): return value if len(segment) > 30 else segment
    trail = " > ".join([segments[0]] + [__format(segment) for segment in segments[1:-1]] + [segments[-1]])
    return trail[:95] + "..." if len(trail) > 95 else trail  # [NOTE]: this rules remain enforced until we handle it through CSS

def fetch_all_results(api_key, search_engine_id, query, sort_by, max_queries):
    """Fetch search results for a query dynamically using parallel requests."""
    # First, make a single request to get initial results and total count
    results, next_start, total_results, search_time = google_search(api_key, search_engine_id, query, 1, sort_by)
    results_map = {1: results}  # store first page results
    total_search_time = search_time
    remaining_pages = min(max_queries - 1, (total_results - 1) // MAX_RESULTS)  # calculate remaining pages to fetch
    # app.logger.info(f"\n\n[DEBUG]: remaining_pages={remaining_pages}\n----------\n")
    if remaining_pages and next_start:  # fetch remaining pages in parallel
        with ThreadPoolExecutor() as executor:
            remaining_indices = [next_start + i * MAX_RESULTS for i in range(remaining_pages)]
            futures = { 
                executor.submit(google_search, api_key, search_engine_id, query, start, sort_by): start 
                for start in remaining_indices
            }
            for future in as_completed(futures):
                start = futures[future]  # get the corresponding start index
                try:
                    results, _, _, page_search_time = future.result()
                    results_map[start] = results  # store results under their start index
                    total_search_time += page_search_time
                except Exception as e:
                    app.logger.error(f"\n\n[ERROR]: future.result() -> {e}\n----------\n")
    all_results = []
    for start in sorted(results_map.keys()):  # combine all results in order (based on start index)
        all_results.extend(results_map[start])
    return all_results, total_results, round(total_search_time, 2)
