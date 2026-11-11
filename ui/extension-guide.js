const browsers = {
  chrome: ['Chrome', 'chrome://extensions'], edge: ['Edge', 'edge://extensions'],
  yandex: ['Яндекс Браузер', 'browser://extensions'], brave: ['Brave', 'brave://extensions'],
  firefox: ['Firefox', 'about:debugging#/runtime/this-firefox'],
};

export function connectionSummary(data) {
  if (!data || !Array.isArray(data.paired) || !Array.isArray(data.pending)) throw new Error('Некорректный ответ сервера.');
  const pairs = data.paired.length, pending = data.pending.length;
  return `На момент проверки: сохранённых разрешений — ${pairs}, ожидающих запросов — ${pending}. ` +
    (pending ? 'Проверьте запрос в верхней части MediaHub; разрешайте только знакомое расширение.' :
      'Запросов сейчас не видно. Если подключение отклонено или запрос истёк, его может понадобиться отправить снова.') +
    ' Это общее число, не статус выбранного браузера; разрешение не подтверждает, что расширение сейчас на связи.';
}

export function setupExtensionGuide({ doc = document, win = window, fetcher = fetch } = {}) {
  const anchor = doc.getElementById('extSt'), section = anchor?.closest('.sg');
  if (!section) return;
  const box = doc.createElement('div'); box.className = 'sr extension-guide'; box.id = 'extension-guide';
  const content = doc.createElement('div');
  const title = doc.createElement('b'); title.textContent = 'Пошаговая настройка (необязательно)';
  const label = doc.createElement('label'); label.textContent = 'Ваш браузер'; label.htmlFor = 'extension-browser';
  const select = doc.createElement('select'); select.id = 'extension-browser';
  for (const [value, name] of [['', 'Выберите браузер'], ...Object.entries(browsers).map(([id, [name]]) => [id, name])]) {
    const option = doc.createElement('option'); option.value = value; option.textContent = name; select.append(option);
  }
  const steps = doc.createElement('ol'); steps.className = 'mu';
  const note = doc.createElement('p'); note.className = 'mu';
  note.textContent = 'Выбор браузера и проверка ниже не устанавливают расширение, не выдают разрешений и не передают вкладки. Ранее выбранный список может храниться в расширении и отправиться после подключения. Перед повтором проверьте «Входящие». Если при отправке было включено закрытие, вкладки могут закрыться после успешной обработки.';
  const button = doc.createElement('button'); button.type = 'button'; button.className = 'btn'; button.textContent = 'Обновить состояние подключения';
  const status = doc.createElement('p'); status.className = 'mu'; status.setAttribute('role', 'status');
  content.append(title, label, select, steps, note, button, status); box.append(content); section.append(box);
  function render() {
    steps.replaceChildren();
    const choice = browsers[select.value];
    if (!choice) return;
    const lines = choice[0] === 'Firefox' ? [
      `Откройте ${choice[1]} и выберите «Загрузить временное дополнение», затем файл manifest.json из пути выше. После перезапуска Firefox временное дополнение нужно загрузить снова.`,
    ] : [
      `Откройте ${choice[1]}, включите режим разработчика и выберите загрузку распакованного расширения. Выберите папку из пути выше.`,
    ];
    lines.push('Чтобы запросить подключение, откройте значок MediaHub в браузере и выберите вкладки для списка. Это действие может отложить и затем отправить выбранные адреса и названия.',
      'В MediaHub проверьте запрос и выберите «Разрешить» или «Отклонить». Состояние можно обновить кнопкой ниже. При ошибке проверьте, что приложение и браузер запущены.');
    for (const text of lines) { const item = doc.createElement('li'); item.textContent = text; steps.append(item); }
  }
  select.addEventListener('change', render); render();
  let busy = false;
  button.addEventListener('click', async () => {
    if (busy) return;
    busy = true; button.disabled = true; status.textContent = 'Проверяем сохранённые разрешения и запросы…';
    const controller = new AbortController(); let timedOut = false;
    const timer = win.setTimeout(() => { timedOut = true; controller.abort(); }, 15000);
    try {
      const response = await fetcher('/api/ext', { cache: 'no-store', signal: controller.signal });
      if (timedOut) throw new Error('Время ожидания истекло.');
      if (!response.ok) throw new Error('Сервер не ответил успешно.');
      const data = await response.json();
      if (timedOut) throw new Error('Время ожидания истекло.');
      status.textContent = connectionSummary(data);
    } catch (error) {
      status.textContent = `Состояние неизвестно: ${timedOut ? 'время ожидания истекло' : (error?.message || 'нет связи с MediaHub')}. Проверьте приложение и повторите.`;
    } finally { win.clearTimeout(timer); busy = false; button.disabled = false; }
  });
}
