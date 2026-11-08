const LIMIT = 200;
export function createHistory() {
  const items = [];
  return {
    add(event) { items.unshift(event); if (items.length > LIMIT) items.pop(); },
    list() { return [...items]; },
    clear() { items.length = 0; },
  };
}

export function setupNotifications() {
  const history = createHistory();
  const side = document.querySelector('.side');
  const button = document.createElement('button');
  button.className = 'btn notify-launch';
  button.setAttribute('aria-label', 'Журнал уведомлений');
  button.innerHTML = '<span aria-hidden="true">🔔</span><span class="lbl">Уведомления</span>';
  side.insertBefore(button, document.querySelector('#disk'));
  const dialog = document.createElement('dialog');
  dialog.setAttribute('aria-labelledby', 'notify-title');
  dialog.innerHTML = `<div class="dh"><h2 id="notify-title">Уведомления за эту сессию</h2></div>
    <div class="db"><p id="notify-empty">Событий пока нет.</p><ol class="notify-list"></ol></div>
    <div class="df"><button class="btn" id="notify-clear">Очистить журнал</button><button class="btn primary" id="notify-close">Закрыть</button></div>`;
  document.body.append(dialog);
  const list = dialog.querySelector('.notify-list');
  const box = document.querySelector('#toastBox');
  box.setAttribute('aria-live', 'polite');
  box.setAttribute('aria-relevant', 'additions');
  function render() {
    list.replaceChildren();
    const items = history.list();
    dialog.querySelector('#notify-empty').hidden = !!items.length;
    for (const item of items) {
      const li = document.createElement('li');
      const time = document.createElement('time');
      time.dateTime = item.time.toISOString();
      time.textContent = item.time.toLocaleTimeString('ru');
      li.append(time, document.createTextNode(' — ' + item.message));
      if (item.label && typeof item.action === 'function') {
        const action = document.createElement('button');
        action.className = 'btn'; action.textContent = item.label;
        action.addEventListener('click', () => { dialog.close(); item.action(); });
        li.append(' ', action);
      }
      list.append(li);
    }
  }
  button.addEventListener('click', () => { render(); dialog.showModal(); });
  dialog.querySelector('#notify-close').addEventListener('click', () => dialog.close());
  dialog.querySelector('#notify-clear').addEventListener('click', () => { history.clear(); render(); });
  window.addEventListener('mediahub:notify', event => {
    const { message, label, action } = event.detail || {};
    if (typeof message !== 'string' || !message) return;
    const item = { message, label, action, time: new Date() };
    history.add(item);
    if (dialog.open) render();
    const toast = document.createElement('div');
    toast.className = 'toast';
    const text = document.createElement('span'); text.textContent = message; toast.append(text);
    if (label && typeof action === 'function') {
      const link = document.createElement('button'); link.textContent = label;
      link.addEventListener('click', () => { toast.remove(); action(); }); toast.append(link);
    }
    box.append(toast);
    while (box.children.length > 4) box.firstElementChild.remove();
    setTimeout(() => toast.remove(), 8000);
  });
}
