"""Exact allowlist of browser assets served by the local application."""

UI_FILES = frozenset((
    '/ui/app.js',
    '/ui/backup.js',
    '/ui/download-preflight.js',
    '/ui/download-preflight-dialog.js',
    '/ui/inbox-submit.js',
    '/ui/preferences.js',
    '/ui/notifications.js',
    '/ui/hotkeys.js',
    '/ui/job-events.js',
    '/ui/cancel-all.js',
    '/ui/delete-dialog.js',
    '/ui/game-library.js',
    '/ui/game-search.js',
    '/ui/game-scan-settings.js',
    '/ui/library-view.js',
    '/ui/library-search.js',
    '/ui/game-tags.js',
    '/ui/game-update-preview.js',
    '/ui/save-inventory.js',
    '/ui/accessibility.css',
    '/ui/reader.js',
    '/ui/reader-images.js',
    '/ui/reader-progress.js',
    '/ui/reader-modes.js',
    '/ui/reader.css',
    '/ui/player.js',
    '/ui/player-keys.js',
    '/ui/player-subtitles.js',
    '/ui/player-progress.js',
    '/ui/player.css',
    '/ui/recent.js',
))


def allowed(path):
    return path == '/' or path in UI_FILES
