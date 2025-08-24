from shared import app, DATA_DIR
from pandas import ExcelFile, read_excel, notna

def load_websites_data():
    """Load websites data from websites.xlsx file."""
    try:  # read excel file with multiple sheets
        with ExcelFile(DATA_DIR + 'websites.xlsx') as xl:  # context manager ensures file is closed
            categories = {}
            for sheet_name in xl.sheet_names:  # process each sheet as a category
                df = read_excel(xl, sheet_name=sheet_name)
                if 'Website Name' in df.columns and 'Website Link' in df.columns:  # ensure columns exist and clean data
                    websites = [
                        {"title": row['Website Name'], "link": row['Website Link']}
                        for _, row in df.iterrows()
                        if notna(row['Website Name']) and notna(row['Website Link'])
                    ]
                    categories[sheet_name] = {
                        "websites": websites,
                        "max_limit": len(websites)  # dynamic max limit per category
                    }
            return {"categories": categories, "default_category": list(categories.keys())[0] if categories else None}
    except Exception as e:
        app.logger.error(f"\n\n[ERROR]: loading websites -> {e}\n----------\n")
        return {"categories": {}, "default_category": None}

def load_proxied_domains():
    """Load proxied domains from proxied_websites.txt file."""
    try:
        with open(DATA_DIR + 'proxied_websites.txt', 'r') as f:
            return [line.strip() for line in f if line.strip()]
    except Exception as e:
        app.logger.error(f"\n\n[ERROR]: loading proxied domains -> {e}\n----------\n")
        return []
