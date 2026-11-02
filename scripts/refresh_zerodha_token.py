#!/usr/bin/env python3
import os
from kiteconnect import KiteConnect

ENV_PATH = '/opt/tradingai/.env.zerodha'
REQ_PATH = '/tmp/request_token.txt'


def load_env():
    cfg = {}
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH) as f:
            for line in f:
                s = line.strip()
                if '=' in s and not s.startswith('#'):
                    k, v = s.split('=', 1)
                    cfg[k] = v
    return cfg


def main():
    cfg = load_env()
    if not os.path.exists(REQ_PATH):
        print('ERR1')
        return
    with open(REQ_PATH) as f:
        rt = f.read().strip()
    if not rt:
        print('ERR2')
        return
    kc = KiteConnect(api_key=cfg['KITE_API_KEY'])
    data = kc.generate_session(rt, api_secret=cfg['KITE_API_SECRET'])
    at = data.get('access_token')
    if not at:
        print(data)
        return
    with open(ENV_PATH, 'w') as f:
        f.write('ZERODHA_MODE=SHADOW\n')
        f.write('KITE_API_KEY=' + cfg['KITE_API_KEY'] + '\n')
        f.write('KITE_API_SECRET=' + cfg['KITE_API_SECRET'] + '\n')
        f.write('KITE_ACCESS_TOKEN=' + at + '\n')
        f.write('REDIRECT_URL=' + cfg.get('REDIRECT_URL', 'https://tradingai.in') + '\n')
    print('SUCCESS')
    print(at)
    kc2 = KiteConnect(api_key=cfg['KITE_API_KEY'])
    kc2.set_access_token(at)
    p = kc2.profile()
    print(p.get('user_id'), p.get('user_name'))


if __name__ == '__main__':
    main()
