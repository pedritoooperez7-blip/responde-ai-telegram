/* LiggaCuba · Anuncios (usuarios sin Premium + pantalla "Anunciar mi negocio").
 * Reutiliza de app.js: state, $, $$, toast, showScreen, showPaymentMethods, goBack.
 * Todo el contenido de los anuncios se pinta con textContent (nunca como HTML). */
(function () {
  'use strict';
  const PLAN_ORDER = ['ad_daily', 'ad_weekly', 'ad_monthly', 'ad_annual'];
  const NAMES = { ad_daily: 'Diario', ad_weekly: 'Semanal', ad_monthly: 'Mensual', ad_annual: 'Anual' };
  const DAYS_LABEL = { ad_daily: '1 día', ad_weekly: '7 días', ad_monthly: '30 días', ad_annual: '365 días' };
  const STATUS_TEXT = {
    draft: 'Aún no has enviado tu anuncio',
    pending: 'En revisión: lo mostraremos cuando administración lo apruebe',
    approved: 'Aprobado',
    rejected: 'Rechazado',
    paused: 'Pausado por administración',
  };
  let pricing = null;
  let selected = 'ad_monthly';

  function el(tag, attrs, ...kids) {
    const n = document.createElement(tag);
    Object.entries(attrs || {}).forEach(([k, v]) => {
      if (k === 'text') n.textContent = v;
      else if (k === 'class') n.className = v;
      else if (k.startsWith('on')) n.addEventListener(k.slice(2), v);
      else if (v !== null && v !== undefined) n.setAttribute(k, v);
    });
    kids.flat().forEach(c => { if (c) n.append(c); });
    return n;
  }
  async function api(path, opts) {
    const r = await fetch(path, opts);
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.detail || 'Ocurrió un error');
    return d;
  }
  function fmtDate(iso) {
    try { return typeof formatCubaDate === 'function' ? formatCubaDate(iso) : new Date(iso).toLocaleDateString('es'); } catch (_) { return iso || '—'; }
  }
  function safeHttps(url) {
    try { const u = new URL(url); return u.protocol === 'https:' || u.protocol === 'http:' ? u.href : ''; } catch (_) { return ''; }
  }

  /* ---------- Anuncio mostrado mientras la IA trabaja ---------- */
  function adCard(ad) {
    const wrap = el('div', { class: 'ad-card' },
      el('span', { class: 'ad-tag', text: 'Anuncio' }),
      ad.image_url && safeHttps(ad.image_url) ? el('img', { class: 'ad-img', src: safeHttps(ad.image_url), alt: '', loading: 'eager', referrerpolicy: 'no-referrer' }) : null,
      el('strong', { class: 'ad-title', text: ad.title }),
      el('p', { class: 'ad-body', text: ad.body }),
      el('small', { class: 'ad-by', text: ad.business_name }),
      el('button', { class: 'secondary ad-cta', type: 'button', text: ad.cta || 'Ver más', onclick: async () => {
        try {
          const d = await api('/api/ads/click', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id: ad.id }) });
          const url = safeHttps(d.url);
          if (!url) return;
          if (window.Telegram?.WebApp?.openLink && !/^https:\/\/t\.me\//i.test(url)) window.Telegram.WebApp.openLink(url);
          else if (window.Telegram?.WebApp?.openTelegramLink && /^https:\/\/t\.me\//i.test(url)) window.Telegram.WebApp.openTelegramLink(url);
          else window.open(url, '_blank', 'noopener');
        } catch (_) { /* un anuncio caído nunca debe romper el análisis */ }
      } }));
    return wrap;
  }

  /* start() se llama al pulsar Analizar. Si el usuario no es Premium y hay un
   * anuncio vigente, lo muestra mientras se genera la respuesta; finish() espera
   * a que pasen unos segundos y el usuario pulse "Ver respuestas". Cualquier
   * fallo se ignora: sin anuncio, el flujo es el de siempre. */
  function start() {
    if (state.premium) return { finish: async () => {}, cancel: () => {} };
    const host = $('#adInterstitial');
    if (!host) return { finish: async () => {}, cancel: () => {} };
    let shown = false;
    let minDone = null;
    const adPromise = api('/api/ads/next').then(d => d.ad ? { ad: d.ad, min: Math.max(2, Math.min(8, Number(d.min_seconds) || 4)) } : null).catch(() => null);
    adPromise.then(info => {
      if (!info) return;
      shown = true;
      const body = $('#adInterstitialBody');
      body.replaceChildren(adCard(info.ad));
      const btn = $('#adContinue');
      btn.disabled = true;
      let left = info.min;
      btn.textContent = `Ver respuestas (${left})`;
      host.classList.remove('hidden');
      minDone = new Promise(resolve => {
        const timer = setInterval(() => {
          left -= 1;
          if (left > 0) { btn.textContent = `Ver respuestas (${left})`; return; }
          clearInterval(timer);
          btn.textContent = 'Ver respuestas';
          btn.disabled = false;
          btn.onclick = () => { host.classList.add('hidden'); resolve(); };
        }, 1000);
      });
    });
    return {
      // Se llama cuando la respuesta ya está lista.
      finish: async () => {
        const info = await adPromise;
        if (!info || !shown) return;
        await minDone;
      },
      cancel: () => host.classList.add('hidden'),
    };
  }

  /* ---------- Pantalla "Anunciar mi negocio" ---------- */
  async function loadPricing() {
    try {
      const d = await api('/api/ads/pricing');
      pricing = d.plans;
    } catch (_) { pricing = null; }
  }

  function renderPlans(box) {
    box.replaceChildren();
    const grid = el('div', { class: 'plan-stack' });
    PLAN_ORDER.forEach(id => {
      const p = pricing?.[id];
      if (!p) return;
      const btn = el('button', { class: 'plan' + (id === selected ? ' selected' : ''), type: 'button', 'data-ad-plan': id,
        onclick: () => { selected = id; renderPlans(box); } },
        p.saved_percent > 0 ? el('span', { class: 'save-pill', text: `Ahorras ${p.saved_percent}%` }) : null,
        el('strong', { text: NAMES[id] }),
        el('b', { text: p.amount }),
        el('span', { text: `${DAYS_LABEL[id]} · ${p.per_day} al día` }),
        p.saved_percent > 0 ? el('small', { class: 'ad-saving', text: `Ahorras ${p.saved} frente a pagar día a día` }) : null);
      grid.append(btn);
    });
    box.append(grid);
  }

  function renderEditor(box, info) {
    box.replaceChildren();
    const statusClass = info.status === 'approved' ? 'ok' : info.status === 'rejected' ? 'bad' : '';
    box.append(
      el('div', { class: 'd-card soft' },
        el('strong', { text: info.plan_active ? `Plan activo hasta ${fmtDate(info.paid_until)}` : 'Tu plan de anuncio venció' }),
        el('p', { class: 'd-muted ad-status ' + statusClass, text: STATUS_TEXT[info.status] || info.status }),
        info.status === 'rejected' && info.reject_reason ? el('p', { class: 'd-muted', text: 'Motivo: ' + info.reject_reason }) : null,
        el('p', { class: 'd-muted', text: `Vistas: ${info.impressions} · Clics: ${info.clicks}` })));
    const f = {};
    const field = (key, label, max, tag, ph) => {
      const input = el(tag || 'input', { class: 'admin-input', maxlength: String(max), placeholder: ph || '' });
      input.value = info[key] || '';
      f[key] = input;
      return el('label', { class: 'ad-field' }, el('span', { text: label }), input);
    };
    const err = el('p', { class: 'd-muted ad-error', text: '' });
    const save = el('button', { class: 'primary', type: 'button', text: 'Enviar a revisión', onclick: async () => {
      save.disabled = true; err.textContent = '';
      try {
        const body = {}; Object.keys(f).forEach(k => { body[k] = f[k].value; });
        const d = await api('/api/business-ad', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
        toast('Anuncio enviado a revisión');
        renderEditor(box, d);
      } catch (e) { err.textContent = e.message; } finally { save.disabled = false; }
    } });
    box.append(el('div', { class: 'd-card' },
      field('business_name', 'Nombre del negocio', 60),
      field('title', 'Título', 60),
      field('body', 'Descripción', 220, 'textarea'),
      field('cta', 'Texto del botón (opcional)', 24, 'input', 'Ver más'),
      field('link_url', 'Enlace (https:// o t.me/…)', 300, 'input', 'https://t.me/minegocio'),
      field('image_url', 'Imagen (enlace https, opcional)', 400),
      el('p', { class: 'd-muted', text: 'Cada cambio vuelve a revisión. Debe cumplir las reglas de contenido.' }),
      el('a', { href: '/rules.html', text: 'Ver reglas de contenido' }),
      err, save));
  }

  async function openBusiness() {
    showScreen('businessAdScreen');
    const plans = $('#businessAdPlans'), editor = $('#businessAdEditor');
    plans.replaceChildren(el('p', { class: 'd-muted', text: 'Cargando…' }));
    editor.replaceChildren();
    if (!pricing) await loadPricing();
    if (!pricing) { plans.replaceChildren(el('p', { class: 'd-muted', text: 'No se pudieron cargar los precios. Inténtalo de nuevo.' })); return; }
    renderPlans(plans);
    try {
      const info = await api('/api/business-ad');
      if (info.has_plan) renderEditor(editor, info);
    } catch (_) { /* sin plan todavía */ }
  }

  function buy() {
    state.plan = selected;
    showPaymentMethods();
  }

  document.addEventListener('DOMContentLoaded', () => {});
  const open = $('#openBusinessAd');
  if (open) open.onclick = openBusiness;
  const back = $('#businessAdBack');
  if (back) back.onclick = goBack;
  const buyBtn = $('#businessAdBuy');
  if (buyBtn) buyBtn.onclick = buy;
  window.LCAds = { start, openBusiness, refreshBusiness: openBusiness };
})();
