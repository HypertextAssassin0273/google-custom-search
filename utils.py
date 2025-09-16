from shared import *
from pandas import ExcelFile, read_excel, notna
from dotenv import dotenv_values
from os import getppid, kill
import signal

def load_websites_data(file_path):
    """Load websites data from websites.xlsx file."""
    categories = {}
    try:  # read excel file with multiple sheets
        with ExcelFile(file_path) as xl:  # context manager ensures file is closed
            for sheet_name in xl.sheet_names:  # process each sheet as a category
                df = read_excel(xl, sheet_name=sheet_name)
                if 'Website Name' in df.columns and 'Website Link' in df.columns:  # ensure columns exist and clean data
                    websites = [
                        {"title": row['Website Name'], "link": row['Website Link']}
                        for _, row in df.iterrows()
                        if notna(row['Website Name']) and notna(row['Website Link'])
                    ]
                    categories[sheet_name] = {"websites": websites, "max_limit": len(websites)}
    except FileNotFoundError: ...  # file doesn't exist yet
    except Exception as e: app.logger.error(f"\n\n[ERROR]: loading websites -> {e}\n----------\n")
    return categories

def load_proxied_domains(file_path):
    """Load proxied domains from proxied_websites.txt file."""
    try:
        with open(file_path, 'r') as f:
            return [line.strip() for line in f if line.strip()]
    except Exception as e:
        app.logger.error(f"\n\n[ERROR]: loading proxied domains -> {e}\n----------\n")
        return []

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

def update_env_file(file_path, changes):
    """Apply add, update, delete changes to a .env file (dict-based)."""
    env_data = dotenv_values(file_path)
    for name in changes.get('delete', []):
        env_data.pop(name, None)
    for upd in changes.get('update', []):
        orig, name, value = upd.get('original'), upd.get('name'), upd.get('value')
        if orig in env_data:
            env_data.pop(orig)
        if name and value:
            env_data[name] = value
    for add in changes.get('add', []):
        name, value = add.get('name'), add.get('value')
        if name and value:
            env_data[name] = value
    with open(file_path, 'w') as f:  # write back
        for k, v in env_data.items():
            f.write(f"'{k}'='{v}'\n")

def update_proxy_file(file_path, changes):
    """Apply add, update, delete changes to a proxied domains file (list-based)."""
    try:
        with open(file_path, 'r') as f:
            domains = [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        domains = []
    for name in changes.get('delete', []):
        while name in domains:
            domains.remove(name)
    for upd in changes.get('update', []):
        orig, name = upd.get('original'), upd.get('name')
        if orig in domains and name:
            domains = [name if d == orig else d for d in domains]
    for add in changes.get('add', []):
        name = add.get('name')
        if name and name not in domains:
            domains.append(name)
    with open(file_path, 'w') as f:
        for domain in domains:
            f.write(f"{domain}\n")
