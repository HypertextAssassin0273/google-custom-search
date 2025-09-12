from shared import app
from pandas import ExcelFile, read_excel, notna
from os import getppid, kill
from sys import platform
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
    if platform.startswith('win'): return  # [[DEV-ENV-GUARD]]
    ppid = getppid()
    if ppid > 1:  # avoid signaling init/systemd
        kill(ppid, signal.SIGUSR1)  # SIGUSR1 -> gunicorn specific signal? where does it exist??
        app.logger.info(f"Signaled gunicorn master (PID: {ppid}) to reload workers.")
