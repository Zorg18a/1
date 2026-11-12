"""Choose a likely game image from a thread, not obvious site branding.

This is a heuristic, not proof of image content. Prefer the first post, then
page metadata. Never fall back to an obvious logo or a tiny UI image.
"""
import re
from urllib.parse import urljoin, urlsplit


_BRANDING = re.compile(r'(?:^|[^a-z0-9])(logo|favicon|avatar|smil(?:e|ey|ie)s?|emoji|sprite|icon|banner)(?:[^a-z0-9]|$)', re.I)


def _image(value, base, attrs=None):
    if not isinstance(value, str) or not value.strip() or len(value) > 4000:
        return ''
    try:
        url = urljoin(base, value.strip())
        parts = urlsplit(url)
        if parts.scheme not in ('http', 'https') or not parts.hostname or parts.username or parts.password:
            return ''
        if _BRANDING.search(parts.path):
            return ''
        if attrs:
            if _BRANDING.search(' '.join(str(attrs.get(k) or '') for k in ('class', 'alt', 'id'))):
                return ''
            for dimension in ('width', 'height'):
                value = str(attrs.get(dimension) or '').strip()
                if value.isdigit() and int(value) < 100:
                    return ''
        return url
    except ValueError:
        return ''


def choose(post_images, meta, base):
    """Prefer first-post images; use a plausible social image only as fallback."""
    for attrs in post_images:
        for key in ('data-src', 'data-url', 'src'):
            candidate = _image(attrs.get(key), base, attrs)
            if candidate:
                return candidate
    for key in ('og:image', 'twitter:image'):
        candidate = _image(meta.get(key), base)
        if candidate:
            return candidate
    return ''
