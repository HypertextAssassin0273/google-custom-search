from shared import *
from flask import session
from pandas import ExcelFile, read_excel, notna
from os import getppid, kill
import signal, uuid

def load_websites_data():
    """Load websites data from websites.xlsx file."""
    categories = {}
    try:  # read excel file with multiple sheets
        with ExcelFile(WEB_PATH) as xl:  # context manager ensures file is closed
            for sheet_name in xl.sheet_names:  # process each sheet as a category
                df = read_excel(xl, sheet_name=sheet_name)
                # app.logger.info(f"\n\n[DEBUG]: `DF-Columns`: {df.columns}\n`DF-Head`:\n{df.head()}\n----------\n")
                if {'Website Name', 'Website Link', 'Require Proxy'}.issubset(df.columns):  # ensure columns exist
                    websites = [
                        {"title": WN, "link": WL,
                         "proxy_required": notna((RP := row['Require Proxy'])) and
                                           str(RP).strip().lower() in {"1.0", "true", "yes"}}  # ensure clean data
                        for _, row in df.iterrows()
                        if notna((WN := row['Website Name'])) and notna((WL := row['Website Link']))
                    ]
                    categories[sheet_name] = {"websites": websites, "max_limit": len(websites)}
    except FileNotFoundError: ...  # file doesn't exist yet
    except Exception as e: app.logger.error(f"\n\n[ERROR]: loading websites -> {e}\n----------\n")
    return categories

def load_proxied_domains():
    """Load proxied domains from proxied_websites.txt file."""
    try:
        with open(DOM_PATH, 'r') as f:
            return [l for line in f if (l := line.strip())]  # perfect walrus-operator ':=' usage
    except FileNotFoundError: ...  # file doesn't exist yet
    except Exception as e: app.logger.error(f"\n\n[ERROR]: loading proxied domains -> {e}\n----------\n")
    return []

def get_rate_limit_key():
    """Generate a unique key for rate limiting based on session ID."""
    if 'rate_limit_id' not in session:
        session['rate_limit_id'] = str(uuid.uuid4())
    return f"session:{session['rate_limit_id']}"

def clear_rate_limits(storage, rate_limit_id, path=''):
    """Clear rate limits for a specific session."""
    try:  # reset rate limit on successful login, [NOTE]: https://github.com/alisaifee/flask-limiter/issues/189
        pattern = f'LIMITS:LIMITER/session:{rate_limit_id}{path}/*'
        # app.logger.info(f"\n\n[DEBUG]: redis_keys={list(storage.scan_iter(pattern))}\n----------\n")
        for key in storage.scan_iter(pattern):
            storage.delete(key)
    except Exception as e:
        app.logger.error(f"\n\n[ERROR]: clearing rate limit for session {rate_limit_id}: {e}\n----------\n")

def signal_workers():
    """Signal gunicorn workers to reload gracefully."""
    ppid = getppid()
    if ppid > 1:  # avoid signaling init/systemd
        kill(ppid, signal.SIGHUP)  # SIGHUP -> graceful reload (workers only), SIGUSR2 -> full restart (master + workers)
        app.logger.info(f"Signaled gunicorn master (PID: {ppid}) to reload workers.")

def update_env_file(file_path, env_data, changes):
    """Apply add, update, delete changes to a .env file (dict-based)."""
    for name in changes.get('del', []):
        env_data.pop(name)
    update_map = {upd.get('original'): (upd.get('name'), upd.get('value')) for upd in changes.get('upd', [])}  
    env_data = {  # rebuild dict with renamed keys to preserve order, O(n) complexity
        (upd := update_map.get(k, (k, None)))[0]: upd[1] or v  # update entry if in map, retain original otherwise
        for k, v in env_data.items()
    }
    for add in changes.get('add', []):
        env_data[add.get('name')] = add.get('value')
    with open(file_path, 'w') as f:  # write back
        for k, v in env_data.items():
            f.write(f"'{k}'='{v}'\n")

def update_proxy_file(domains, changes):
    """Apply add, update, delete changes to a proxied domains file (list-based)."""
    for name in changes.get('del', []):
        domains.remove(name)
    update_map = {upd.get('original'): upd.get('name') for upd in changes.get('upd', [])}  # O(1) lookup
    domains = [update_map.get(d, d) for d in domains]  # rebuild list with updated names, O(n) complexity
    for add in changes.get('add', []):
        domains.append(add.get('name'))
    with open(DOM_PATH, 'w') as f:
        for domain in domains:
            f.write(f"{domain}\n")
