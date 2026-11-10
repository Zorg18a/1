const keyFor = itemId => `mediahub.player.subtitles.v1.${itemId}`;

export function subtitleTracks(media) {
  return Array.from(media.textTracks || []).filter(track => track.kind === 'subtitles' || track.kind === 'captions');
}

function activeIndex(tracks) { return tracks.findIndex(track => track.mode === 'showing'); }
function identity(track) { return { language: track.language || '', label: track.label || '' }; }

function selectTrack(tracks, index) {
  for (const track of tracks) track.mode = 'disabled';
  if (index >= 0 && index < tracks.length) tracks[index].mode = 'showing';
}

export function cycleSubtitles(media) {
  const tracks = subtitleTracks(media);
  if (!tracks.length) return 'Нет доступных субтитров';
  const next = activeIndex(tracks) + 1;
  selectTrack(tracks, next);
  return next >= tracks.length ? 'Субтитры выключены' :
    `Субтитры: ${tracks[next].label || tracks[next].language || next + 1}`;
}

function readChoice(storage, itemId) {
  try {
    const raw = storage?.getItem(keyFor(itemId));
    if (!raw || raw.length > 1024) return null;
    const choice = JSON.parse(raw);
    if (choice?.mode === 'off') return { mode: 'off' };
    if (choice?.mode === 'track' && typeof choice.language === 'string' &&
        typeof choice.label === 'string' && choice.language.length <= 100 && choice.label.length <= 200) return choice;
  } catch { /* blocked storage or malformed data */ }
  return null;
}

export function setupSubtitleSelector({ doc, media, container, select, storage, itemId, expected }) {
  let pending = readChoice(storage, itemId);
  let initialized = false;

  function save() {
    const tracks = subtitleTracks(media), index = activeIndex(tracks);
    const choice = index < 0 ? { mode: 'off' } : { mode: 'track', ...identity(tracks[index]) };
    try { storage?.setItem(keyFor(itemId), JSON.stringify(choice)); } catch { /* optional preference */ }
  }
  function refresh() {
    const tracks = subtitleTracks(media);
    if (!initialized && tracks.length >= expected) {
      initialized = true;
      if (pending?.mode === 'off') selectTrack(tracks, -1);
      else if (pending?.mode === 'track') {
        const matches = tracks.map((track, i) => ({ ...identity(track), i }))
          .filter(track => track.language === pending.language && track.label === pending.label);
        if (matches.length === 1) selectTrack(tracks, matches[0].i);
      }
      pending = null;
    }
    const options = [];
    const off = doc.createElement('option'); off.value = '-1'; off.textContent = 'Выключены'; options.push(off);
    tracks.forEach((track, index) => {
      const option = doc.createElement('option'); option.value = String(index);
      option.textContent = track.label || track.language || `Дорожка ${index + 1}`;
      options.push(option);
    });
    select.replaceChildren(...options);
    select.value = String(activeIndex(tracks));
    container.hidden = !tracks.length;
  }
  select.addEventListener('change', () => {
    const tracks = subtitleTracks(media), value = select.value;
    if (value !== '-1' && (!/^(0|[1-9][0-9]*)$/.test(value) || Number(value) >= tracks.length)) {
      refresh(); return;
    }
    pending = null; initialized = true;
    selectTrack(tracks, Number(value));
    save(); refresh();
  });
  media.textTracks?.addEventListener?.('change', () => { refresh(); if (initialized && subtitleTracks(media).length) save(); });
  media.textTracks?.addEventListener?.('addtrack', refresh);
  media.textTracks?.addEventListener?.('removetrack', refresh);
  refresh();
  return () => { if (subtitleTracks(media).length) { pending = null; initialized = true; refresh(); save(); } };
}
