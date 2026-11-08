const ROUTES = { l: 'library', i: 'inbox', d: 'downloads', g: 'games', s: 'settings' };

export function nextShortcut(armed, key) {
  const k = key.toLowerCase();
  if (armed && ROUTES[k]) return { armed: false, route: ROUTES[k] };
  return { armed: k === 'g', route: null };
}

export function setupHotkeys(preferences) {
  const button = document.createElement('button');
  button.className = 'btn shortcuts-launch';
  button.setAttribute('aria-label', 'Показать горячие клавиши');
  button.innerHTML = '<span aria-hidden="true">⌨</span><span class="lbl">Горячие клавиши</span>';
  document.querySelector('.side').insertBefore(button, document.querySelector('#disk'));
  const dialog = document.createElement('dialog');
  dialog.setAttribute('aria-labelledby', 'shortcut-title');
  dialog.innerHTML = `<div class="dh"><h2 id="shortcut-title">Горячие клавиши</h2></div>
    <div class="db"><p>Нажмите G, затем букву в течение полутора секунд. Клавиши можно отключить в настройках.</p>
    <ul class="shortcut-list"><li><kbd>G</kbd> <kbd>L</kbd> — библиотека</li><li><kbd>G</kbd> <kbd>I</kbd> — входящие</li>
    <li><kbd>G</kbd> <kbd>D</kbd> — загрузки</li><li><kbd>G</kbd> <kbd>G</kbd> — игры</li><li><kbd>G</kbd> <kbd>S</kbd> — настройки</li></ul></div>
    <div class="df"><button class="btn primary" id="shortcut-close">Закрыть</button></div>`;
  document.body.append(dialog);
  button.addEventListener('click', () => dialog.showModal());
  dialog.querySelector('#shortcut-close').addEventListener('click', () => dialog.close());
  let armed = false, timer;
  document.addEventListener('keydown', event => {
    const el = event.target;
    if (!preferences().hotkeys || event.ctrlKey || event.altKey || event.metaKey || event.repeat ||
        el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName) || document.querySelector('dialog[open]')) {
      armed = false; return;
    }
    const result = nextShortcut(armed, event.key);
    armed = result.armed;
    clearTimeout(timer);
    if (armed) timer = setTimeout(() => { armed = false; }, 1500);
    if (result.route) { event.preventDefault(); window.location.hash = '#' + result.route; }
  });
}
