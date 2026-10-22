import { initDemo } from './demo.js';

const $ = (s) => document.querySelector(s);
const make = (tag, className, content) => { const e = document.createElement(tag); if (className) e.className = className; if (content != null) e.textContent = content; return e; };
const brandName = (s = '') => /ROG/i.test(s) ? 'ROG' : /Razer/i.test(s) ? '雷蛇 Razer' : s;
const priority = ['Sony', '索尼', 'Xbox', '飞智', '盖世小鸡', '罗技', 'Logitech', 'Razer', '雷蛇', 'ROG', '北通', '动感指尖', '八位堂', 'Nintendo', '任天堂'];
const rank = (s) => { const n = priority.findIndex(t => s.toLowerCase().includes(t.toLowerCase())); return n < 0 ? 100 : n; };
const kindNames = { controller: '手柄', mouse: '鼠标', keyboard: '键盘' };
const state = { kind: 'controller', brand: '全部', query: '', cards: 'outline', view: 'outline', model: null, group: null };
let entries = [], groups = [], lastFocus = null;

async function start() {
  try {
    const response = await fetch('models.json');
    if (!response.ok) throw new Error(`catalog ${response.status}`);
    const manifest = await response.json();
    entries = manifest.models;
    const grouped = new Map();
    for (const m of entries) {
      const key = m.familyKey || `${m.kind}:${m.id}`;
      if (!grouped.has(key)) grouped.set(key, { key, name: m.familyName || m.name, brand: brandName(m.brand), kind: m.kind, models: [] });
      grouped.get(key).models.push(m);
    }
    groups = [...grouped.values()].sort((a, b) => rank(a.brand) - rank(b.brand) || a.brand.localeCompare(b.brand, 'zh-CN') || a.name.localeCompare(b.name, 'zh-CN'));
    renderWall(manifest.models);
    renderHero();
    renderBrands(); renderGrid(); initDemo(manifest.models);
    document.body.dataset.ready = 'true';
  } catch (error) {
    $('#model-grid').replaceChildren(make('p', 'empty-state', '模型库暂时无法载入，请刷新页面重试。'));
    console.error(error);
  }
}

function renderWall(models) {
  const fragment = document.createDocumentFragment();
  // A coprime stride interleaves every model without repeating or dropping any.
  for (let i = 0; i < models.length; i++) {
    const m = models[(i * 53) % models.length];
    const img = make('img'); img.src = m.outline; img.alt = ''; img.loading = 'lazy'; img.decoding = 'async'; fragment.append(img);
  }
  $('#model-wall').append(fragment);
}
function renderHero() {
  ['g502x', 'viper3', 'harpe2', 'ds5', 'elite2', 'apex6'].forEach(id => {
    const m = entries.find(e => e.id === id); if (!m) return;
    const image = make('img', 'hero-device'); image.src = m.outline; image.alt = ''; image.width = m.width; image.height = m.height; image.decoding = 'async'; $('#hero-models').append(image);
  });
}
function renderBrands() {
  const brands = [...new Set(groups.filter(g => g.kind === state.kind).map(g => g.brand))].sort((a,b) => rank(a)-rank(b) || a.localeCompare(b,'zh-CN'));
  if (state.brand !== '全部' && !brands.includes(state.brand)) state.brand = '全部';
  const fragment = document.createDocumentFragment();
  ['全部', ...brands].forEach(brand => {
    const button = make('button', 'brand-chip', brand); button.type = 'button'; button.setAttribute('aria-pressed', brand === state.brand);
    button.addEventListener('click', () => { state.brand = brand; renderBrands(); renderGrid(); }); fragment.append(button);
  });
  $('#brand-filters').replaceChildren(fragment);
}
function renderGrid() {
  const query = state.query.trim().toLowerCase();
  const filtered = groups.filter(g => g.kind === state.kind && (state.brand === '全部' || g.brand === state.brand) && (!query || `${g.name} ${g.brand} ${g.models.map(m => `${m.name} ${m.id} ${m.versionLabel}`).join(' ')}`.toLowerCase().includes(query)));
  const fragment = document.createDocumentFragment();
  filtered.forEach(group => {
    const m = group.models[0], button = make('button', 'model-card'); button.type = 'button'; button.dataset.kind = group.kind;
    button.setAttribute('aria-label', `查看 ${group.brand} ${group.name} 的版本与图集`);
    const img = make('img'); img.src = state.cards === 'atlas' ? m.atlasThumb || m.atlas || m.outline : m.outline; img.alt = ''; img.loading = 'lazy'; img.decoding = 'async';
    button.append(img, make('small', '', group.brand), make('strong', '', cleanFamilyName(group)), make('span', 'version-count', group.models.length > 1 ? `${group.models.length} 个版本` : '查看型号'), make('span', 'card-open', '↗'));
    button.addEventListener('click', () => openGroup(group, button)); fragment.append(button);
  });
  if (!filtered.length) fragment.append(make('p', 'empty-state', state.kind === 'keyboard' && !entries.some(m => m.kind === 'keyboard') ? '键盘图集正在整理。' : '没有找到匹配的型号，试试其他关键词。'));
  $('#model-grid').replaceChildren(fragment); $('#model-grid').scrollTop = 0;
  $('#library-label').textContent = `${state.brand === '全部' ? '全部' : state.brand + ' · '}${kindNames[state.kind]}`;
}
function cleanFamilyName(group) {
  return group.name.replace(new RegExp(`^${escapeRx(group.models[0]?.brand || '')}\\s*[·|—-]?\\s*`, 'i'), '') || group.name;
}
function escapeRx(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }
function openGroup(group, button) {
  lastFocus = button; state.group = group; state.model = group.models[0]; state.view = group.kind === 'keyboard' ? 'atlas' : 'outline';
  $('#detail-brand').textContent = group.brand; $('#detail-title').textContent = cleanFamilyName(group);
  const fragment = document.createDocumentFragment();
  group.models.forEach(m => {
    const btn = make('button', 'version-button', m.versionLabel || m.name); btn.type = 'button'; btn.dataset.id = m.id;
    btn.addEventListener('click', () => { state.model = m; renderDetail(); }); fragment.append(btn);
  });
  $('#detail-versions').replaceChildren(fragment); renderDetail(); $('#model-dialog').showModal(); document.body.style.overflow = 'hidden';
}
function renderDetail() {
  const m = state.model; if (!m) return;
  $('#detail-versions').querySelectorAll('button').forEach(b => b.setAttribute('aria-pressed', b.dataset.id === m.id));
  const atlasButton = $('[data-view="atlas"]'); atlasButton.disabled = !m.atlas;
  if (state.view === 'atlas' && !m.atlas) state.view = 'outline';
  document.querySelectorAll('[data-view]').forEach(b => b.setAttribute('aria-selected', b.dataset.view === state.view));
  const visual = $('#detail-visual'), fragment = document.createDocumentFragment();
  if (state.view === 'atlas' && m.atlas) {
    const img = make('img', 'atlas-image'); img.src = m.atlas; img.alt = `${m.name} 写实与轮廓对照图集`; img.decoding = 'async'; fragment.append(img);
  } else {
    [[m.outline, '正面'], [m.rear, '背面']].forEach(([src, label]) => {
      if (!src) return; const fig = make('figure'), img = make('img'); img.src = src; img.alt = `${m.name} ${label}轮廓`; img.decoding = 'async'; fig.append(img, make('figcaption', '', label)); fragment.append(fig);
    });
  }
  visual.replaceChildren(fragment);
  $('#detail-note').textContent = m.frontSchematic || m.rearSchematic ? '此型号含示意图；图集保留原有标注。' : state.view === 'atlas' ? '产品写实与轮廓对照。' : m.rear ? '背面已按工具显示方向镜像。' : '设备正面轮廓。';
  $('#atlas-open').hidden = !m.atlas; if (m.atlas) $('#atlas-open').href = m.atlas;
}
document.querySelectorAll('[data-kind]').forEach(button => button.addEventListener('click', () => {
  state.kind = button.dataset.kind; state.brand = '全部';
  document.querySelectorAll('[data-kind]').forEach(b => b.setAttribute('aria-selected', b === button)); renderBrands(); renderGrid();
}));
$('#model-search').addEventListener('input', e => { state.query = e.target.value; renderGrid(); });
$('#card-view').addEventListener('click', () => { state.cards = state.cards === 'outline' ? 'atlas' : 'outline'; $('#card-view').setAttribute('aria-pressed', state.cards === 'atlas'); $('#card-view').textContent = state.cards === 'atlas' ? '轮廓预览' : '图集预览'; renderGrid(); });
$('#library-top').addEventListener('click', () => { $('#model-grid').scrollTo({ top: 0, behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth' }); $('#models').scrollIntoView(); });
document.querySelectorAll('[data-view]').forEach(button => button.addEventListener('click', () => { state.view = button.dataset.view; renderDetail(); }));
$('#detail-close').addEventListener('click', () => $('#model-dialog').close());
$('#model-dialog').addEventListener('click', e => { if (e.target === $('#model-dialog')) { const r = e.target.getBoundingClientRect(); if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) e.target.close(); } });
$('#model-dialog').addEventListener('close', () => { document.body.style.overflow = ''; lastFocus?.focus({ preventScroll: true }); });
for (const selector of ['[data-kind]', '[data-view]']) {
  const tabs = [...document.querySelectorAll(selector)];
  const sync = () => tabs.forEach(t => t.tabIndex = t.getAttribute('aria-selected') === 'true' ? 0 : -1);
  tabs.forEach((tab, index) => {
    tab.addEventListener('click', sync);
    tab.addEventListener('keydown', event => {
      const choices = tabs.filter(t => !t.disabled), current = choices.indexOf(tab);
      let next = null;
      if (event.key === 'ArrowRight') next = choices[(current + 1) % choices.length];
      if (event.key === 'ArrowLeft') next = choices[(current - 1 + choices.length) % choices.length];
      if (event.key === 'Home') next = choices[0];
      if (event.key === 'End') next = choices.at(-1);
      if (next) { event.preventDefault(); next.click(); next.focus(); }
    });
  });
  sync();
}
if (!matchMedia('(prefers-reduced-motion: reduce)').matches && 'IntersectionObserver' in window) {
  const observer = new IntersectionObserver(items => items.forEach(item => { if (item.isIntersecting) { item.target.classList.remove('pending'); observer.unobserve(item.target); } }), { threshold: .08 });
  document.querySelectorAll('.reveal').forEach(el => { el.classList.add('pending'); observer.observe(el); });
}
start();
