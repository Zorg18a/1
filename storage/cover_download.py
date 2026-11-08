"""Download artwork while checking every redirect before connecting."""
import urllib.request


class GuardedRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, guard):
        super().__init__()
        self.guard = guard

    def redirect_request(self, request, fp, code, msg, headers, newurl):
        self.guard(newurl)
        return super().redirect_request(request, fp, code, msg, headers, newurl)


def download_cover(url, referer, guard, existing_opener, limit):
    guard(url)
    cookies = [h for h in existing_opener.handlers if isinstance(h, urllib.request.HTTPCookieProcessor)]
    client = urllib.request.build_opener(GuardedRedirect(guard), *cookies)
    request = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Referer': referer})
    with client.open(request, timeout=30) as response:
        guard(response.geturl())
        return response.read(limit + 1)
