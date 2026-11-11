"""Smoke-test diagnostics should preserve errors and not expose request tokens."""
import unittest
from types import SimpleNamespace

from scripts.browser_diagnostics import BrowserDiagnostics


class FakePage:
    def __init__(self):
        self.handlers = {}

    def on(self, name, handler):
        self.handlers[name] = handler

    def emit(self, name, event):
        self.handlers[name](event)


class BrowserDiagnosticsTests(unittest.TestCase):
    def test_captures_failures_without_request_query(self):
        page = FakePage(); diagnostics = BrowserDiagnostics(page)
        page.emit('requestfailed', SimpleNamespace(url='http://127.0.0.1/ui/app.js?t=secret', failure='net::ERR_FAILED'))
        page.emit('response', SimpleNamespace(url='http://127.0.0.1/ui/backup.js?token=secret', status=500))
        page.emit('response', SimpleNamespace(url='http://127.0.0.1/ok', status=200))
        page.emit('pageerror', ValueError('initialization failed'))
        page.emit('console', SimpleNamespace(type='error', text='module failure'))
        page.emit('console', SimpleNamespace(type='log', text='not an error'))
        report = diagnostics.report()
        for text in ('/ui/app.js: net::ERR_FAILED', '/ui/backup.js: HTTP 500', 'initialization failed', 'module failure'):
            self.assertIn(text, report)
        for text in ('secret', '/ok', 'not an error'):
            self.assertNotIn(text, report)

    def test_limits_output(self):
        page = FakePage(); diagnostics = BrowserDiagnostics(page)
        self.assertIn('no captured', diagnostics.report())
        for _ in range(40):
            page.emit('pageerror', ValueError('x' * 900))
        self.assertEqual(len(diagnostics.events), 30)
        self.assertTrue(all(len(event) <= 511 for event in diagnostics.events))


if __name__ == '__main__':
    unittest.main()
