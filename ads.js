/* LiggaCuba · Anuncios (usuarios sin Premium + pantalla "Anunciar mi negocio").
 * Reutiliza de app.js: state, $, $$, toast, showScreen, showPaymentMethods, goBack. */
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
  const AD_SECONDS = 15;
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
  function authHeaders() {
    return { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + (state.authToken || '') };
  }
  function fmtDate(iso) {
    try { return typeof formatCubaDate === 'function' ? formatCubaDate(iso) : new Date(iso).toLocaleDateString('es'); } catch (_) { return iso || '—'; }
  }
  function safeHttps(url) {
    try { const u = new URL(url); return u.protocol === 'https:' || u.protocol === 'http:' ? u.href : ''; } catch (_) { return ''; }
  }

  /* ─── Fullscreen ad interstitial ──────────────────────────────────────── */
  function showFullscreenAd(ad, onDone) {
    const host      = $('#adInterstitial');
    const imgBox    = $('#adFsImage');
    const titleEl   = $('#adFsTitle');
    const bodyEl    = $('#adFsBody');
    const bylineEl  = $('#adFsByline');
    const ctaBtn    = $('#adFsCta');
    const continueBtn = $('#adContinue');
    const timerBadge  = $('#adTimerBadge');
    const progressBar = $('#adFsProgress');
    if (!host) { onDone(); return; }

    // Fill content
    titleEl.textContent  = ad.title || '';
    bodyEl.textContent   = ad.body  || '';
    bylineEl.textContent = ad.business_name || '';
    ctaBtn.textContent   = ad.cta || 'Ver más';

    // Image
    imgBox.innerHTML = '';
    const imgUrl = safeHttps(ad.image_url || '');
    if (imgUrl) {
      const img = document.createElement('img');
      img.src = imgUrl;
      img.alt = '';
      img.className = 'ad-fs-img';
      img.referrerPolicy = 'no-referrer';
      imgBox.appendChild(img);
      imgBox.classList.remove('hidden');
    } else {
      imgBox.classList.add('hidden');
    }

    // Reset state
    continueBtn.disabled = true;
    continueBtn.textContent = `Ver respuestas (${AD_SECONDS})`;
    timerBadge.textContent = AD_SECONDS;
    progressBar.style.width = '0%';
    host.classList.remove('hidden');
    document.body.classList.add('ad-open');

    let skipped = false;
    let resolved = false;
    function finish() {
      if (resolved) return;
      resolved = true;
      clearInterval(timer);
      host.classList.add('hidden');
      document.body.classList.remove('ad-open');
      onDone();
    }

    // CTA click → register click + open link + skip ad immediately
    ctaBtn.onclick = async () => {
      try {
        const d = await api('/api/ads/click', { method: 'POST', headers: authHeaders(), body: JSON.stringify({ id: ad.id }) });
        const url = safeHttps(d.url);
        if (url) {
          if (window.Telegram?.WebApp?.openLink && !/^https:\/\/t\.me\//i.test(url)) window.Telegram.WebApp.openLink(url);
          else if (window.Telegram?.WebApp?.openTelegramLink && /^https:\/\/t\.me\//i.test(url)) window.Telegram.WebApp.openTelegramLink(url);
          else window.open(url, '_blank', 'noopener');
        }
      } catch (_) {}
      skipped = true;
      finish();
    };

    // Countdown
    let left = AD_SECONDS;
    const startTime = Date.now();
    const timer = setInterval(() => {
      const elapsed = (Date.now() - startTime) / 1000;
      left = Math.max(0, AD_SECONDS - Math.floor(elapsed));
      const pct = Math.min(100, (elapsed / AD_SECONDS) * 100);
      progressBar.style.width = pct + '%';
      timerBadge.textContent = left > 0 ? left : '✓';
      if (left > 0) {
        continueBtn.textContent = `Ver respuestas (${left})`;
      } else {
        clearInterval(timer);
        continueBtn.textContent = 'Ver respuestas ✓';
        continueBtn.disabled = false;
        continueBtn.onclick = finish;
      }
    }, 250);
  }

  /* start() se llama al pulsar Analizar. Devuelve { finish, cancel }. */
  function start() {
    if (state.premium) return { finish: async () => {}, cancel: () => {} };
    const host = $('#adInterstitial');
    if (!host) return { finish: async () => {}, cancel: () => {} };

    let minDone = null;
    let shown = false;

    const adPromise = api('/api/ads/next')
      .then(d => d.ad ? d.ad : null)
      .catch(() => null);

    adPromise.then(ad => {
      if (!ad) return;
      shown = true;
      minDone = new Promise(resolve => {
        showFullscreenAd(ad, resolve);
      });
    });

    return {
      finish: async () => {
        await adPromise;
        if (!shown) return;
        if (minDone) await minDone;
      },
      cancel: () => {
        host.classList.add('hidden');
        document.body.classList.remove('ad-open');
      },
    };
  }

  /* ─── Pantalla "Anunciar mi negocio" ──────────────────────────────────── */
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

  /* ─── Image upload helper (gallery → base64 → API → URL) ─────────────── */
  function createImageUploader({ currentUrl, onUrl, label }) {
    const wrap = el('div', { class: 'ad-img-uploader' });
    const preview = el('div', { class: 'ad-img-preview' + (currentUrl ? '' : ' hidden') });
    if (currentUrl) {
      const img = el('img', { src: safeHttps(currentUrl) || currentUrl, alt: '', class: 'ad-img-thumb' });
      preview.appendChild(img);
    }
    const urlInput = el('input', { class: 'admin-input', type: 'url', placeholder: 'https://… (pega un enlace)', value: currentUrl || '' });
    urlInput.oninput = () => onUrl(urlInput.value.trim());

    const fileInput = el('input', { type: 'file', accept: 'image/jpeg,image/png,image/webp,image/gif', class: 'hidden' });
    const uploadBtn = el('button', { type: 'button', class: 'secondary ad-upload-btn', text: '📷 Subir desde galería' });
    const statusEl  = el('p', { class: 'd-muted ad-upload-status', text: '' });

    uploadBtn.onclick = () => fileInput.click();
    fileInput.onchange = async () => {
      const file = fileInput.files?.[0];
      if (!file) return;
      uploadBtn.disabled = true;
      statusEl.textContent = 'Subiendo imagen…';
      try {
        const b64 = await new Promise((res, rej) => {
          const r = new FileReader();
          r.onload = () => res(r.result);
          r.onerror = rej;
          r.readAsDataURL(file);
        });
        const d = await api('/api/ads/upload-image', {
          method: 'POST',
          headers: authHeaders(),
          body: JSON.stringify({ image: b64 }),
        });
        urlInput.value = d.url;
        onUrl(d.url);
        preview.innerHTML = '';
        const img = el('img', { src: d.url, alt: '', class: 'ad-img-thumb' });
        preview.appendChild(img);
        preview.classList.remove('hidden');
        statusEl.textContent = '✓ Imagen subida';
        setTimeout(() => { statusEl.textContent = ''; }, 3000);
      } catch (e) {
        statusEl.textContent = e.message || 'Error subiendo imagen';
      } finally {
        uploadBtn.disabled = false;
      }
    };

    const orLine = el('div', { class: 'ad-upload-or' }, el('span', { text: 'o pega un enlace' }));
    wrap.append(el('label', { class: 'ad-field' }, el('span', { text: label || 'Imagen' })), preview, uploadBtn, fileInput, statusEl, orLine, urlInput);
    return wrap;
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
    // Image uploader
    const imgUrlHolder = { value: info.image_url || '' };
    const imgUploader = createImageUploader({
      currentUrl: info.image_url,
      label: 'Imagen del anuncio (opcional)',
      onUrl: url => { imgUrlHolder.value = url; },
    });
    const err  = el('p', { class: 'd-muted ad-error', text: '' });
    const save = el('button', { class: 'primary', type: 'button', text: 'Enviar a revisión', onclick: async () => {
      save.disabled = true; err.textContent = '';
      try {
        const body = {}; Object.keys(f).forEach(k => { body[k] = f[k].value; });
        body.image_url = imgUrlHolder.value;
        const d = await api('/api/business-ad', { method: 'POST', headers: authHeaders(), body: JSON.stringify(body) });
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
      imgUploader,
      el('p', { class: 'd-muted', text: 'Cada cambio vuelve a revisión. Debe cumplir las reglas de contenido.' }),
      el('a', { href: '/rules.html', text: 'Ver reglas de contenido para anunciantes' }),
      err, save));
  }

  async function openBusiness() {
    let info = null, failed = false;
    try { info = await api('/api/business-ad'); } catch (_) { failed = true; }
    if (info && info.has_plan && info.plan_active) return openEditor(info);
    return openPlans(info, failed);
  }

  async function openPlans(info, failed) {
    showScreen('businessAdScreen');
    const plans = $('#businessAdPlans'), notice = $('#businessAdNotice'), buyBtn = $('#businessAdBuy');
    notice.textContent = failed
      ? 'No pudimos comprobar si ya tienes un plan activo. Revisa tu conexión antes de contratar.'
      : (info && info.has_plan ? `Tu plan venció el ${fmtDate(info.paid_until)}. Elige uno para volver a mostrar tu anuncio.` : '');
    plans.replaceChildren(el('p', { class: 'd-muted', text: 'Cargando…' }));
    if (buyBtn) buyBtn.classList.add('hidden');
    if (!pricing) await loadPricing();
    if (!pricing) { plans.replaceChildren(el('p', { class: 'd-muted', text: 'No se pudieron cargar los precios. Inténtalo de nuevo.' })); return; }
    renderPlans(plans);
    if (buyBtn) buyBtn.classList.remove('hidden');
  }

  function openEditor(info) {
    showScreen('businessAdEditorScreen');
    renderEditor($('#businessAdEditor'), info);
  }

  function buy() {
    state.plan = selected;
    showPaymentMethods();
  }

  const open = $('#openBusinessAd');
  if (open) open.onclick = openBusiness;
  const back = $('#businessAdBack');
  if (back) back.onclick = goBack;
  const editorBack = $('#businessAdEditorBack');
  if (editorBack) editorBack.onclick = goBack;
  const buyBtn = $('#businessAdBuy');
  if (buyBtn) buyBtn.onclick = buy;
  window.LCAds = { start, openBusiness, refreshBusiness: openBusiness };
})();
