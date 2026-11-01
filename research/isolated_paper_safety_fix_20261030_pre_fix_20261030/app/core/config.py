import json, os
# Single env-driven base: TRADINGAI_BASE (default /opt/tradingai).
# DB path canonical: TRADINGAI_DB_PATH else <BASE>/database/tradingai.db.
# Eliminates /opt/tradingai vs /opt/tradingai_new split (see core/db.py, observability/monitor.py).
BASE = os.environ.get('TRADINGAI_BASE', '/opt/tradingai')
DB_PATH = os.environ.get('TRADINGAI_DB_PATH', os.path.join(BASE, 'database/tradingai.db'))
def load_json(path):
    with open(os.path.join(BASE, path)) as f: return json.load(f)
_instruments_data = load_json('config/instruments.json')
instruments = _instruments_data['instruments'] if isinstance(_instruments_data, dict) and 'instruments' in _instruments_data else _instruments_data
settings = load_json('config/settings.json')
