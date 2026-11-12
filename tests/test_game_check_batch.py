"""Game check count and retry behavior with synthetic data, without network."""
import os
import subprocess
import sys
import tempfile
import unittest


class GameCheckBatchTests(unittest.TestCase):
    def test_all_86_are_selected_and_a_new_job_starts_over(self):
        code = r'''
from legacy import app
app.ext_online = lambda: True
rows = [{'id': i, 'title': f'Game {i}', 'kind': 'game', 'url': f'game:{i}', 'thread': f'https://example.com/threads/{i}/'} for i in range(1, 87)]
def sql(query, params=()):
    if query == "select * from items where kind='game'": return rows
    if query == 'select * from items where id=?': return [rows[params[0] - 1]]
    raise AssertionError(query)
app.sql = sql
app.ginfo = lambda row: {'meta': {'thread': row['thread'], 'version': '1'}}
seen, titles = [], []
def fetch(url, job):
    seen.append(url)
    titles.append(job['title'])
    return url
app.fetch_html = fetch
app.gamelib.parse_thread = lambda html, url: {'name': 'Game', 'version': '1'}
app.apply_meta = lambda meta, thread: None
job = {'cancel': False}
app.game_check(job)
assert len(seen) == 86 and '1/86' in titles[0] and '86/86' in titles[-1]
assert 'проверено 86' in job['final']
seen.clear(); titles.clear()
app.game_check({'cancel': False, 'ids': [1, 2, 3]})
assert seen == [row['thread'] for row in rows[:3]]
'''
        with tempfile.TemporaryDirectory() as directory:
            env = dict(os.environ, MEDIAHUB_DATA_DIR=directory, MEDIAHUB_GAME_DELAY='0')
            subprocess.run([sys.executable, '-c', code], env=env, check=True, timeout=30)
