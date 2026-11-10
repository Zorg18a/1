"""Conservative outcome handling for yt-dlp downloads and partial playlists."""


def playlist_urls(info, errors):
    """Keep a warning if flattening a playlist discards unidentifiable entries."""
    urls = []
    for entry in info.get('entries') or []:
        url = (entry.get('url') or entry.get('webpage_url')) if isinstance(entry, dict) else None
        if isinstance(url, str) and url.startswith('http'):
            urls.append(url)
        else:
            errors.append('не удалось определить адрес элемента плейлиста')
    return urls


def checked_download(downloader, url):
    """yt-dlp may return a nonzero status rather than raising an exception."""
    result = downloader.download([url])
    if result != 0:
        raise RuntimeError('загрузчик сообщил об ошибке; проверьте источник и повторите вручную')


def mark_partial(job, saved_count, errors):
    """Keep a partial result distinct from success; cancellation still takes precedence."""
    if not job.get('cancel') and saved_count and errors:
        job['final'] = ('частично: ошибки при проверке или загрузке; '
                        'проверьте библиотеку перед повтором')
