const KEY = 'mediahub.display.v1';
const defaults = Object.freeze({ theme: 'dark', size: 'normal', contrast: 'normal', hotkeys: true });

export function normalizePreferences(value) {
  const v = value && typeof value === 'object' ? value : {};
  return {
    theme: ['dark', 'light'].includes(v.theme) ? v.theme : defaults.theme,
    size: ['normal', 'large', 'larger'].includes(v.size) ? v.size : defaults.size,
    contrast: ['normal', 'high'].includes(v.contrast) ? v.contrast : defaults.contrast,
    hotkeys: typeof v.hotkeys === 'boolean' ? v.hotkeys : defaults.hotkeys,
  };
}

export function readPreferences(storage) {
  try { return normalizePreferences(JSON.parse(storage.getItem(KEY) || '{}')); }
  catch { return normalizePreferences({}); }
}

export function savePreferences(storage, preferences) {
  try { storage.setItem(KEY, JSON.stringify(normalizePreferences(preferences))); return true; }
  catch { return false; }
}

export function setupPreferences() {
  let storage;
  try { storage = window.localStorage; } catch { storage = null; }
  let prefs = readPreferences(storage);
  const panel = document.createElement('div');
  panel.className = 'sg';
  panel.innerHTML = `<h2>Отображение и доступность</h2>
    <div class="sr"><label for="display-theme">Тема</label><div class="ctl"><select id="display-theme"><option value="dark">Тёмная</option><option value="light">Светлая</option></select></div></div>
    <div class="sr"><label for="display-size">Размер интерфейса</label><div class="ctl"><select id="display-size"><option value="normal">Обычный</option><option value="large">Крупный</option><option value="larger">Очень крупный</option></select></div></div>
    <div class="sr"><label for="display-contrast">Контрастность</label><div class="ctl"><select id="display-contrast"><option value="normal">Обычная</option><option value="high">Высокая</option></select></div></div>
    <div class="sr"><label for="display-hotkeys">Горячие клавиши</label><div class="ctl"><input type="checkbox" id="display-hotkeys"></div></div>
    <p id="display-storage-warning" role="status" hidden>Настройки не удалось сохранить в этом браузере.</p>`;
  document.querySelector('#v-settings .set h1').after(panel);
  const controls = Object.fromEntries(['theme', 'size', 'contrast', 'hotkeys'].map(k => [k, panel.querySelector('#display-' + k)]));
  function apply() {
    for (const key of ['theme', 'size', 'contrast']) {
      document.documentElement.dataset[key] = prefs[key];
      controls[key].value = prefs[key];
    }
    controls.hotkeys.checked = prefs.hotkeys;
  }
  for (const [key, control] of Object.entries(controls)) {
    control.addEventListener('change', () => {
      prefs = normalizePreferences({ ...prefs, [key]: key === 'hotkeys' ? control.checked : control.value });
      apply();
      panel.querySelector('#display-storage-warning').hidden = savePreferences(storage, prefs);
    });
  }
  apply();
  return () => prefs;
}
