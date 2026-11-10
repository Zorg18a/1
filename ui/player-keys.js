import { readPreferences } from './preferences.js';

export function formatTime(value) {
  const seconds = Number.isFinite(value) ? Math.max(0, Math.floor(value)) : 0;
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor(seconds / 60) % 60;
  const rest = String(seconds % 60).padStart(2, '0');
  return hours ? `${hours}:${String(minutes).padStart(2, '0')}:${rest}` : `${minutes}:${rest}`;
}

export function cycleSubtitles(media) {
  const tracks = [...media.textTracks];
  if (!tracks.length) return 'Нет доступных субтитров';
  const current = tracks.findIndex(track => track.mode === 'showing');
  const next = current + 1;
  for (const track of tracks) track.mode = 'disabled';
  if (next >= tracks.length) return 'Субтитры выключены';
  tracks[next].mode = 'showing';
  return `Субтитры: ${tracks[next].label || tracks[next].language || next + 1}`;
}

export function setupPlayerKeys({ doc, win, media, storage, announce, showHelp }) {
  win.addEventListener('keydown', event => {
    if (!readPreferences(storage).hotkeys || event.ctrlKey || event.altKey || event.metaKey) return;
    if (doc.getElementById('player-help').open) return;
    const target = event.target;
    if (target?.isContentEditable || target?.closest?.('input,textarea,select,button,a,video,audio,[contenteditable]:not([contenteditable="false"])')) return;
    const key = event.key.toLowerCase();
    if (key === 'k') {
      if (media.paused) Promise.resolve().then(() => media.play()).then(() => announce('Воспроизведение')).catch(() => announce('Не удалось начать воспроизведение'));
      else { media.pause(); announce('Пауза'); }
    } else if (key === 'j' || key === 'l') {
      const offset = key === 'j' ? -10 : 10;
      const targetTime = Math.max(0, (Number.isFinite(media.currentTime) ? media.currentTime : 0) + offset);
      try {
        if (!media.readyState) throw new Error('metadata');
        media.currentTime = Number.isFinite(media.duration) ? Math.min(media.duration, targetTime) : targetTime;
        announce(`${offset < 0 ? 'Назад' : 'Вперёд'} на 10 секунд, ${formatTime(media.currentTime)}`);
      } catch { announce('Перемотка пока недоступна'); }
    } else if (key === '[' || key === ']') {
      media.playbackRate = Math.max(0.5, Math.min(2, Math.round((media.playbackRate + (key === '[' ? -0.25 : 0.25)) * 100) / 100));
      announce(`Скорость ${media.playbackRate}`);
    } else if (key === 'c') announce(cycleSubtitles(media));
    else if (key === 'm') { media.muted = !media.muted; announce(media.muted ? 'Звук выключен' : 'Звук включён'); }
    else if (key === 'f' && media.tagName === 'VIDEO') {
      const exiting = Boolean(doc.fullscreenElement);
      const operation = exiting ? doc.exitFullscreen?.bind(doc) : media.requestFullscreen?.bind(media);
      if (operation) Promise.resolve().then(operation).then(() => announce(exiting ? 'Обычный экран' : 'Полный экран')).catch(() => announce('Полный экран недоступен'));
      else announce('Полный экран недоступен');
    } else if (key === '?') showHelp();
    else return;
    event.preventDefault();
  });
}
