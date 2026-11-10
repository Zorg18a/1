// This preference applies to startup scans; manual GameSweep scans have their own selector.
export function setupGameScanSettings() {
  const root = document.querySelector('#s_games_root')?.closest('.sr');
  if (!root) return;
  const row = document.createElement('div');
  row.className = 'sr';
  row.innerHTML = `<div><label for="s_games_layout"><b>Структура папок игр</b></label><small>Выберите уровень папки с игрой. При неверном выборе категории или внутренние папки могут выглядеть как игры. Настройка действует при запуске MediaHub.</small><p class="mu" role="status"></p></div>
    <div class="ctl"><select id="s_games_layout" disabled>
      <option value="auto">Авто: папки new1 и т. п.</option>
      <option value="flat">Корень → игра</option>
      <option value="nested">Корень → категория → игра</option>
      <option value="nested2">Корень → категория → подпапка → игра</option>
    </select></div>`;
  root.after(row);
  const select = row.querySelector('select'), status = row.querySelector('[role="status"]');
  let previous = 'auto';
  async function request(url, body) {
    const response = await fetch(url, body && { method: 'POST', headers: { 'X-MH': '1' }, body: JSON.stringify(body) });
    if (!response.ok) throw new Error('HTTP');
    const result = await response.json();
    if (!result || result.error) throw new Error('JSON');
    return result;
  }
  request('/api/settings').then(config => {
    previous = ['auto', 'flat', 'nested', 'nested2'].includes(config.games_layout) ? config.games_layout : 'auto';
    select.value = previous;
    select.disabled = false;
  }).catch(() => { status.textContent = 'Не удалось загрузить настройку. Обновите страницу.'; });
  select.addEventListener('change', async () => {
    select.disabled = true;
    try {
      const result = await request('/api/settings', { games_layout: select.value });
      if (result.games_layout !== select.value) throw new Error('unexpected setting');
      previous = select.value;
      status.textContent = 'Сохранено для запуска. Чтобы пересканировать сейчас, в «Игры → Версии» выберите ту же структуру и нажмите «Сканировать».';
    } catch {
      select.value = previous;
      status.textContent = 'Не удалось подтвердить сохранение настройки. Обновите страницу и проверьте её.';
    } finally {
      select.disabled = false;
    }
  });
}
