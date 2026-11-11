// Clarify existing links without changing their destination or playback behavior.
export function setupLibraryPlaybackHint({ doc = document, Observer = MutationObserver } = {}) {
  const library = doc.getElementById('lib');
  if (!library) return;
  const hint = doc.createElement('p');
  hint.id = 'library-playback-hint'; hint.className = 'mu library-playback-hint';
  hint.textContent = 'Видео и аудио: обложка открывает файл напрямую в новой вкладке и не использует позицию предпросмотра. «Предпросмотр плеера» может сохранять позицию только в этом браузере; это предварительная функция.';
  library.before(hint);
  function describe(node) {
    const ids = (node.getAttribute('aria-describedby') || '').split(/\s+/).filter(Boolean);
    if (!ids.includes(hint.id)) { ids.push(hint.id); node.setAttribute('aria-describedby', ids.join(' ')); }
  }
  function update() {
    for (const preview of library.querySelectorAll('.c .player-preview')) {
      const card = preview.closest('.c');
      const cover = card?.querySelector('a.cv'), title = card?.querySelector('h3.t');
      if (!cover || !title) continue;
      cover.setAttribute('aria-label', `Открыть файл напрямую: ${title.textContent}`);
      describe(cover); describe(preview);
    }
  }
  const observer = new Observer(update);
  observer.observe(library, { childList: true, subtree: true });
  update();
  return () => observer.disconnect();
}
