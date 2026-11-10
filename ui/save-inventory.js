export function setupSaveInventory() {
  window.addEventListener('mediahub:game-panel', event => {
    const game = event.detail;
    const section = document.querySelector('#gpanel .gb .update-preview');
    if (!section || !game?.g?.downloaded || section.querySelector('.save-inventory')) return;
    const block = document.createElement('div');
    block.className = 'save-inventory';
    block.innerHTML = `<p class="mu">Можно отдельно посмотреть имена и размеры файлов внутри найденных папок сохранений. Это не резервная копия.</p>
      <button type="button" class="btn">Посмотреть состав возможных сохранений</button>
      <p role="status" aria-live="polite" class="mu"></p><div class="save-inventory-results"></div>`;
    const button = block.querySelector('button');
    const status = block.querySelector('[role="status"]');
    const results = block.querySelector('.save-inventory-results');
    button.addEventListener('click', async () => {
      if (button.disabled) return;
      button.disabled = true; results.replaceChildren(); status.textContent = 'Просматриваю состав…';
      try {
        const response = await fetch('/api/game/incoming', { method: 'POST',
          headers: { 'X-MH': '1', 'Content-Type': 'application/json' },
          body: JSON.stringify({ id: game.id, mode: 'save_inventory' }) });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Не удалось просмотреть состав');
        const inventory = data.save_inventory;
        status.textContent = `Папка игры: ${inventory.game_folder}. Показано файлов: ${inventory.files.length}, размер: ${inventory.total_bytes} Б.${inventory.incomplete ? ' Просмотр неполный: есть пропуски или достигнут лимит.' : ''} Содержимое файлов, AppData и облако не проверяются; отсутствие результатов не означает отсутствие сохранений. Это не резервная копия.`;
        const list = document.createElement('ul');
        for (const file of inventory.files) {
          const item = document.createElement('li');
          item.textContent = `${file.path} — ${file.size_bytes} Б`;
          list.append(item);
        }
        results.append(list);
      } catch (error) { status.textContent = error.message || 'Не удалось просмотреть состав'; }
      finally { button.disabled = false; }
    });
    section.append(block);
  });
}
