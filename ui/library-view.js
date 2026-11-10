const KEY = 'mediahub.library-view.v1';
const sorts = ['added', 'title', 'size'];
const groups = ['author', 'topic', ''];
const kinds = ['', 'video', 'audio', 'manga', 'site', 'game', 'link'];

export function normalizeLibraryView(value) {
  const v = value && typeof value === 'object' && !Array.isArray(value) ? value : {};
  return {
    sort: sorts.includes(v.sort) ? v.sort : 'added',
    group: groups.includes(v.group) ? v.group : 'author',
    kind: kinds.includes(v.kind) ? v.kind : '',
  };
}

export function readLibraryView(storage) {
  try { return normalizeLibraryView(JSON.parse(storage.getItem(KEY) || '{}')); }
  catch { return normalizeLibraryView({}); }
}

export function saveLibraryView(storage, value) {
  try { storage.setItem(KEY, JSON.stringify(normalizeLibraryView(value))); return true; }
  catch { return false; }
}

export function setupLibraryView() {
  let storage;
  try { storage = window.localStorage; } catch { storage = null; }
  const sort = document.getElementById('so'), group = document.getElementById('gb');
  const warning = document.createElement('p');
  warning.className = 'mu'; warning.hidden = true;
  warning.setAttribute('role', 'status');
  warning.textContent = 'Настройки вида не удалось сохранить в этом браузере.';
  document.querySelector('#v-library .tools').append(warning);
  const saved = readLibraryView(storage);
  sort.value = saved.sort; group.value = saved.group;
  let kind = saved.kind;
  // The existing library renderer owns the active filter and redraws the view.
  window.setK(kind);
  const persist = () => { warning.hidden = saveLibraryView(storage, { sort: sort.value, group: group.value, kind }); };
  sort.addEventListener('change', persist);
  group.addEventListener('change', persist);
  window.addEventListener('mediahub:library-kind', event => {
    kind = normalizeLibraryView({ kind: event.detail }).kind;
    persist();
  });
}
