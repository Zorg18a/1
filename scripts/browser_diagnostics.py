"""Collect bounded browser startup failures for isolated smoke tests."""
from urllib.parse import urlsplit


class BrowserDiagnostics:
    def __init__(self, page):
        self.events = []
        self.startup = {}
        page.on('pageerror', lambda error: self._record('pageerror', str(error)))
        page.on('requestfailed', lambda request: self._record(
            'requestfailed', f'{self._path(request.url)}: {request.failure}'))
        page.on('response', lambda response: self._response(response))
        page.on('console', lambda message: self._record('console', message.text)
                if message.type == 'error' else None)

    @staticmethod
    def _path(url):
        # Do not include query strings: they can contain GameSweep session tokens.
        return urlsplit(url).path

    def _response(self, response):
        path = self._path(response.url)
        if path in ('/ui/app.js', '/ui/game-scan-settings.js', '/api/settings'):
            self.startup[path] = response.status
        if response.status >= 400:
            self._record('response', f'{path}: HTTP {response.status}')

    def _record(self, kind, message):
        if len(self.events) < 30:
            self.events.append(f'{kind}: {message[:500]}')

    def report(self):
        errors = '\n'.join(self.events) if self.events else '(no captured browser errors)'
        startup = ', '.join(f'{path}: {status}' for path, status in sorted(self.startup.items())) or '(no tracked responses)'
        return f'{errors}\nTracked startup responses: {startup}'
