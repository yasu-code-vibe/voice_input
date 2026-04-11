#!/usr/bin/env python3
"""
Dummy data creation script (998 entries, English)
Target: history_server.json / MySQL
"""

import os
import json
import sys

# Same settings as server.py
HISTORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'history_server.json')
DB_HOST     = os.environ.get('DB_HOST', '')
DB_PORT     = int(os.environ.get('DB_PORT', '3306'))
DB_NAME     = os.environ.get('DB_NAME', 'voice_input')
DB_USER     = os.environ.get('DB_USER', 'voice_input')
DB_PASSWORD = os.environ.get('DB_PASSWORD', 'voice_input_pass')

COUNT = 998
BASE_TS = '2026-01-01T00:00:00.000Z'


def make_entries():
    """Generate entries in descending order (newest first). Server prepends with insert(0, ...)."""
    entries = []
    for i in range(COUNT, 0, -1):
        entries.append({
            'seq': (i - 1) % 1000,
            'text': f'Dummy data {i:03d}',
            'ts': BASE_TS,
        })
    return entries


# ── JSON ──────────────────────────────────────────────────────────────────────
def create_json():
    entries = make_entries()
    data = {'seq': COUNT - 1, 'history': entries}
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f'[JSON] {COUNT} entries created → {HISTORY_FILE}')


# ── MySQL ─────────────────────────────────────────────────────────────────────
def create_mysql():
    try:
        import pymysql
    except ImportError:
        print('[MySQL] pymysql not found. Skipping.')
        return

    conn = pymysql.connect(
        host=DB_HOST, port=DB_PORT, db=DB_NAME,
        user=DB_USER, password=DB_PASSWORD,
        charset='utf8mb4', autocommit=False
    )
    try:
        with conn.cursor() as cur:
            cur.execute('DELETE FROM history')
            cur.execute("UPDATE meta SET value_int = %s WHERE key_name = 'seq'", (COUNT - 1,))
            rows = [
                ((i - 1) % 1000, f'Dummy data {i:03d}', BASE_TS)
                for i in range(1, COUNT + 1)
            ]
            cur.executemany(
                'INSERT INTO history (seq, text, ts) VALUES (%s, %s, %s)',
                rows
            )
        conn.commit()
        print(f'[MySQL] {COUNT} entries created')
    finally:
        conn.close()


if __name__ == '__main__':
    create_json()
    if DB_HOST:
        create_mysql()
    else:
        print('[MySQL] DB_HOST not set. Skipping. Set DB_HOST to use MySQL.')

    print()
    print('── LocalStorage JS snippet ───────────────────────────────────────')
    print('Paste the following into DevTools > Console and run:')
    print()
    print("""(function(){
  const KEY='voice_input_history', SEQ_KEY='voice_input_seq', N=998;
  const entries=[];
  for(let i=1;i<=N;i++){
    entries.push({seq:(i-1)%1000, text:'Dummy data '+String(i).padStart(3,'0'), ts:'2026-01-01T00:00:00.000Z'});
  }
  localStorage.setItem(KEY, JSON.stringify(entries));
  localStorage.setItem(SEQ_KEY, String(N-1));
  console.log('Created '+N+' entries in localStorage');
})();""")
