const ext = globalThis.browser || globalThis.chrome;
const APP = 'http://127.0.0.1:8765';
const $ = id => document.getElementById(id);
const eligible = t => /^https?:/.test(t.url || '') && !(t.url || '').startsWith(APP);
let sets = {}, labels = {};
const MSG = {
  offline: 'MediaHub не запущен. Запустите приложение: выбранные вкладки сохранены в расширении и будут переданы.',
  pending: 'Подтвердите подключение в приложении: во вкладке MediaHub нажмите «Разрешить».',
};
async function load() {
  const win = await ext.windows.getCurrent();
  const all = await ext.tabs.query({ windowId: win.id }), ok = all.filter(eligible);
  let groups = []; try { groups = await ext.tabGroups.query({ windowId: win.id }); } catch (e) {}
  const marked = all.filter(t => t.highlighted && eligible(t));
  sets = { current: all.filter(t => t.active && eligible(t)), marked: marked.length > 1 ? marked : [], all: ok };
  labels = { current: 'Текущая вкладка', marked: 'Отмеченные вкладки (Ctrl+клик)', all: 'Все вкладки этого окна' };
  groups.forEach(g => { sets['g' + g.id] = ok.filter(t => t.groupId === g.id); labels['g' + g.id] = 'Группа «' + (g.title || 'без названия') + '»'; });
  const order = ['current', 'marked', ...groups.map(g => 'g' + g.id), 'all'], first = sets.marked.length ? 'marked' : sets.current.length ? 'current' : 'all';
  $('opts').innerHTML = order.map(k => `<label class="opt${sets[k].length ? '' : ' off'}"><input type="radio" name="s" value="${k}" ${k === first ? 'checked' : ''} ${sets[k].length ? '' : 'disabled'}> ${labels[k]}<b>${sets[k].length}</b></label>`).join('');
  $('opts').addEventListener('change', upd); upd();
}
const sel = () => (document.querySelector('input[name=s]:checked') || {}).value;
function upd() { const n = (sets[sel()] || []).length; $('go').disabled = !n; $('go').textContent = n ? `Показать список в приложении (${n})` : 'Нет подходящих вкладок'; }
$('f').addEventListener('submit', async e => {
  e.preventDefault(); $('go').disabled = true; $('msg').textContent = '';
  const tabs = sets[sel()].map(t => ({ id: t.id, windowId: t.windowId, url: t.url, title: t.title }));
  const r = await ext.runtime.sendMessage({ type: 'send', tabs, close: $('close').checked });
  if (r && r.ok) window.close(); else { $('msg').textContent = MSG[(r && r.error) || 'offline'] || MSG.offline; $('go').disabled = false; }
});
load();
