export function setupGameTags() {
  window.addEventListener('mediahub:game-panel', event => {
    const game = event.detail;
    const panel = document.querySelector('#gpanel .gb');
    if (!panel || !game || !game.g || panel.querySelector('.game-tags-form')) return;
    const form = document.createElement('form');
    form.className = 'game-tags-form';
    form.innerHTML = `<label class="field"><span>Мои теги (через запятую)</span>
      <input name="tags" maxlength="1000" autocomplete="off" aria-describedby="game-tags-help"></label>
      <small id="game-tags-help">До 20 тегов, до 40 символов каждый. Жанры сайта сохраняются отдельно.</small>
      <div class="row"><button class="btn" type="submit">Сохранить теги</button><span role="status" class="mu"></span></div>`;
    const input = form.querySelector('input');
    const button = form.querySelector('button');
    const status = form.querySelector('[role="status"]');
    input.value = (game.g.tags || []).join(', ');
    form.addEventListener('submit', async e => {
      e.preventDefault();
      if (button.disabled) return;
      button.disabled = true; status.textContent = 'Сохраняю…';
      const tags = input.value.split(',').map(s => s.trim()).filter(Boolean);
      try {
        const response = await fetch('/api/game/tags', { method: 'POST',
          headers: { 'X-MH': '1', 'Content-Type': 'application/json' },
          body: JSON.stringify({ id: game.id, tags }) });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || 'Не удалось сохранить теги');
        input.value = result.tags.join(', ');
        status.textContent = 'Теги сохранены';
        window.dispatchEvent(new CustomEvent('mediahub:tags-saved', { detail: { id: game.id, tags: result.tags } }));
      } catch (error) { status.textContent = error.message || 'Не удалось сохранить теги'; }
      finally { button.disabled = false; }
    });
    panel.insertBefore(form, panel.querySelector(':scope > h4'));
  });
}
