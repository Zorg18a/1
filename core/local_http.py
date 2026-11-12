"""Local HTTP server with room for a browser's concurrent module requests."""
from http.server import ThreadingHTTPServer


class LocalHTTPServer(ThreadingHTTPServer):
    # Python 3.11 defaults to a backlog of 5, which can refuse a burst of
    # independent ES-module requests before the server accepts connections.
    request_queue_size = 128
