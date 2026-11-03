/* LiggaCuba Citas — interfaz de la Mini App.
 *
 * No hay chat dentro de la app: al hacer match se muestran los botones para
 * hablar por Telegram o WhatsApp (los canales que cada persona decidió compartir).
 * Reutiliza de app.js: state, $, $$, toast, tg, showPremium, home().
 * Todo el contenido de otros usuarios se inserta con textContent (nunca innerHTML).
 */
(function () {
  'use strict';

  const TEXT = {
    es: {
      title: 'Citas', tab_discover: 'Descubrir', tab_matches: 'Matches', tab_mine: 'Mi perfil',
      intro_title: 'Conoce gente nueva', intro_text: 'Dale like a quien te guste. Si hay match, hablan por Telegram o WhatsApp: en LiggaCuba no hay chat interno.',
      intro_1: 'Solo mayores de 18 años', intro_2: 'Tu contacto lo ven únicamente tus matches', intro_3: 'Todas las fotos se revisan antes de publicarse',
      create_profile: 'Crear mi perfil', edit_profile: 'Editar perfil', save: 'Guardar', saving: 'Guardando…', cancel: 'Cancelar', back: 'Atrás',
      name: 'Nombre', birth: 'Fecha de nacimiento', gender: 'Soy', looking: 'Quiero conocer', province: 'Provincia', municipality: 'Municipio (opcional)',
      bio: 'Sobre mí', bio_help: 'Sin enlaces ni usuarios. Máximo 300 caracteres.', interests: 'Intereses (separados por comas)', age_range: 'Rango de edad que buscas',
      contact_title: 'Cómo te escriben tus matches', share_tg: 'Compartir mi usuario de Telegram', tg_missing: 'Tu cuenta de Telegram no tiene @usuario. Créalo en Ajustes de Telegram para poder compartirlo.',
      whatsapp: 'WhatsApp (opcional, con código de país)', adult: 'Confirmo que soy mayor de 18 años', terms: 'Acepto los términos de Citas',
      terms_link: 'Ver términos', hombre: 'Hombre', mujer: 'Mujer', otro: 'Otro', hombres: 'Hombres', mujeres: 'Mujeres', todos: 'Todos',
      pick: 'Selecciona…', profile_saved: 'Perfil guardado', need_photo: 'Sube al menos una foto para ver perfiles.',
      photos: 'Mis fotos', add_photo: 'Agregar foto', photo_pending: 'En revisión', photo_approved: 'Aprobada', photo_rejected: 'Rechazada', photo_delete: 'Eliminar foto',
      photo_review_note: 'Tu perfil aparece para otras personas cuando una foto sea aprobada.', uploading: 'Subiendo…', photo_sent: 'Foto enviada a revisión',
      pause: 'Pausar mi perfil', unpause: 'Mostrar mi perfil', paused: 'Tu perfil está pausado y no aparece para nadie.', delete_data: 'Borrar mis datos de Citas',
      delete_confirm: '¿Borrar tu perfil, fotos, likes y matches de Citas? No se puede deshacer.', deleted: 'Datos de Citas eliminados',
      under_review: 'Tu perfil está en revisión y no aparece para otras personas por ahora.', suspended: 'Tu perfil de Citas está suspendido. Contacta a soporte.',
      pass: 'Pasar', like: 'Me gusta', undo: 'Deshacer', likes_left: 'Te quedan {n} likes hoy', likes_unlimited: 'Premium · likes ilimitados',
      empty_title: 'No hay más perfiles por ahora', empty_text: 'Vuelve más tarde o amplía tu rango de edad.', refresh: 'Actualizar',
      same_province: 'Tu provincia', report: 'Reportar', block: 'Bloquear', unmatch: 'Deshacer match', matches_empty: 'Aún no tienes matches. ¡Sigue descubriendo!',
      match_title: '¡Es un match!', match_text: 'Ahora puedes escribirle a {n} por:', keep: 'Seguir viendo', write_to: 'Escribir por',
      no_contact: 'Esta persona no compartió un canal de contacto.', likes_you: '{n} personas te dieron like', likes_you_one: '1 persona te dio like', see_who: 'Ver quién (Premium)',
      report_reason: 'Motivo del reporte', report_send: 'Enviar reporte', report_sent: 'Reporte enviado. Gracias por ayudar.', blocked: 'Usuario bloqueado', unmatched: 'Match eliminado',
      block_confirm: '¿Bloquear a esta persona? No volverán a verse.', unmatch_confirm: '¿Deshacer este match? Dejarás de ver su contacto.',
      r_fake: 'Perfil falso', r_inappropriate_photo: 'Foto inapropiada', r_harassment: 'Acoso o falta de respeto', r_minor: 'Parece menor de edad', r_scam: 'Estafa o spam', r_other: 'Otro motivo',
      daily_limit: 'Llegaste al límite diario de likes.', error: 'Ocurrió un error', years: 'años', premium_only: 'Función Premium', loading: 'Cargando…',
      safety: 'Consejo: antes de ver a alguien en persona, reúnanse en un lugar público y avisa a una persona de confianza.',
    },
    en: {
      title: 'Dating', tab_discover: 'Discover', tab_matches: 'Matches', tab_mine: 'My profile',
      intro_title: 'Meet new people', intro_text: 'Like the people you want to meet. On a match you talk on Telegram or WhatsApp: LiggaCuba has no in-app chat.',
      intro_1: 'Adults 18+ only', intro_2: 'Only your matches can see your contact', intro_3: 'Every photo is reviewed before it goes live',
      create_profile: 'Create my profile', edit_profile: 'Edit profile', save: 'Save', saving: 'Saving…', cancel: 'Cancel', back: 'Back',
      name: 'Name', birth: 'Date of birth', gender: 'I am', looking: 'I want to meet', province: 'Province', municipality: 'Municipality (optional)',
      bio: 'About me', bio_help: 'No links or usernames. 300 characters max.', interests: 'Interests (comma separated)', age_range: 'Age range you are looking for',
      contact_title: 'How your matches reach you', share_tg: 'Share my Telegram username', tg_missing: 'Your Telegram account has no @username. Create one in Telegram settings to share it.',
      whatsapp: 'WhatsApp (optional, with country code)', adult: 'I confirm I am 18 or older', terms: 'I accept the Dating terms',
      terms_link: 'View terms', hombre: 'Man', mujer: 'Woman', otro: 'Other', hombres: 'Men', mujeres: 'Women', todos: 'Everyone',
      pick: 'Select…', profile_saved: 'Profile saved', need_photo: 'Upload at least one photo to see profiles.',
      photos: 'My photos', add_photo: 'Add photo', photo_pending: 'In review', photo_approved: 'Approved', photo_rejected: 'Rejected', photo_delete: 'Delete photo',
      photo_review_note: 'Your profile shows to others once a photo is approved.', uploading: 'Uploading…', photo_sent: 'Photo sent for review',
      pause: 'Pause my profile', unpause: 'Show my profile', paused: 'Your profile is paused and hidden from everyone.', delete_data: 'Delete my Dating data',
      delete_confirm: 'Delete your Dating profile, photos, likes and matches? This cannot be undone.', deleted: 'Dating data deleted',
      under_review: 'Your profile is under review and hidden for now.', suspended: 'Your Dating profile is suspended. Contact support.',
      pass: 'Pass', like: 'Like', undo: 'Undo', likes_left: '{n} likes left today', likes_unlimited: 'Premium · unlimited likes',
      empty_title: 'No more profiles for now', empty_text: 'Come back later or widen your age range.', refresh: 'Refresh',
      same_province: 'Your province', report: 'Report', block: 'Block', unmatch: 'Remove match', matches_empty: 'No matches yet. Keep discovering!',
      match_title: "It's a match!", match_text: 'You can now message {n} on:', keep: 'Keep browsing', write_to: 'Message on',
      no_contact: 'This person did not share a contact channel.', likes_you: '{n} people liked you', likes_you_one: '1 person liked you', see_who: 'See who (Premium)',
      report_reason: 'Reason for the report', report_send: 'Send report', report_sent: 'Report sent. Thanks for helping.', blocked: 'User blocked', unmatched: 'Match removed',
      block_confirm: 'Block this person? You will not see each other again.', unmatch_confirm: 'Remove this match? You will stop seeing their contact.',
      r_fake: 'Fake profile', r_inappropriate_photo: 'Inappropriate photo', r_harassment: 'Harassment or disrespect', r_minor: 'Looks underage', r_scam: 'Scam or spam', r_other: 'Other',
      daily_limit: 'You reached the daily like limit.', error: 'Something went wrong', years: 'years', premium_only: 'Premium feature', loading: 'Loading…',
      safety: 'Tip: before meeting anyone in person, choose a public place and tell someone you trust.',
    },
  };
  const T = (k, vars) => {
    const lang = state.language === 'en' ? 'en' : 'es';
    let s = (TEXT[lang][k] ?? TEXT.es[k] ?? k);
    if (vars) for (const [a, b] of Object.entries(vars)) s = s.replace('{' + a + '}', b);
    return s;
  };

  const D = { cfg: null, me: null, tab: 'discover', feed: [], photoIdx: 0, busy: false, likesInfo: null, lastSwiped: false };
  const root = () => $('#datingBody');

  // ---- utilidades -------------------------------------------------------
  function el(tag, props, ...kids) {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(props || {})) {
      if (v == null || v === false) continue;
      if (k === 'class') n.className = v;
      else if (k === 'text') n.textContent = v;
      else if (k === 'value' || k === 'checked' || k === 'disabled' || k === 'selected') n[k] = v;
      else if (k.startsWith('on')) n[k] = v;
      else n.setAttribute(k, v === true ? '' : v);
    }
    for (const c of kids.flat()) { if (c != null && c !== false) n.append(c.nodeType ? c : document.createTextNode(String(c))); }
    return n;
  }
  async function jpost(url, body) {
    const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) });
    const d = await r.json().catch(() => ({ detail: T('error') }));
    if (!r.ok) { const e = new Error(typeof d.detail === 'string' ? d.detail : T('error')); e.status = r.status; throw e; }
    return d;
  }
  const safePhoto = (u) => (typeof u === 'string' && u.startsWith('/api/dating/photo/')) ? u : '';
  const safeContact = (u) => (typeof u === 'string' && (u.startsWith('https://t.me/') || u.startsWith('https://wa.me/'))) ? u : '';
  function openExternal(url) {
    if (!safeContact(url)) return;
    try {
      if (url.startsWith('https://t.me/') && tg?.openTelegramLink) return tg.openTelegramLink(url);
      if (tg?.openLink) return tg.openLink(url);
    } catch (_) { /* usa el respaldo */ }
    window.open(url, '_blank', 'noopener');
  }
  // Abre la pantalla Premium y, al cerrarla, vuelve a Citas.
  function goPremium(reason) {
    showPremium(reason);
    screenStack.length = 0;
    screenStack.push('datingScreen');
  }
  const fail = (e) => toast(e?.message || T('error'));
  function setBusy(btn, on, label) { if (!btn) return; btn.disabled = on; if (label) btn.textContent = label; }

  // ---- navegación -------------------------------------------------------
  function hideOthers() {
    ['#homeScreen', '#profileScreen', '#settingsScreen', '#moreScreen', '#premiumScreen', '#transferScreen'].forEach(s => $(s)?.classList.add('hidden'));
    $('#datingScreen').classList.remove('hidden');
    $('.bottom-nav').classList.remove('hidden');
    $$('.nav-item').forEach(b => b.classList.toggle('active', b.dataset.nav === 'dating'));
  }
  async function openDating() {
    hideOthers();
    root().replaceChildren(el('p', { class: 'd-muted', text: T('loading') }));
    try {
      if (!D.cfg) D.cfg = await (await fetch('/api/dating/config')).json();
      D.me = await jpost('/api/dating/me');
      D.tab = D.me.profile ? (['intro', 'form'].includes(D.tab) ? 'discover' : D.tab) : 'intro';
      render();
    } catch (e) { root().replaceChildren(el('p', { class: 'd-muted', text: e.message || T('error') })); }
  }
  function render() {
    const head = $('#datingTabs');
    const hasProfile = !!D.me?.profile;
    head.classList.toggle('hidden', !hasProfile);
    head.replaceChildren(...['discover', 'matches', 'mine'].map(t =>
      el('button', { class: 'segment' + (D.tab === t ? ' active' : ''), type: 'button', text: T('tab_' + t), onclick: () => { D.tab = t; render(); } })));
    if (!hasProfile && D.tab !== 'form') return renderIntro();
    if (D.tab === 'form') return renderForm();
    const status = D.me.profile.status;
    if (D.tab === 'discover') {
      if (status === 'suspended') return root().replaceChildren(el('p', { class: 'd-notice danger', text: T('suspended') }));
      return renderDiscover();
    }
    if (D.tab === 'matches') return renderMatches();
    return renderMine();
  }

  // ---- introducción y formulario ---------------------------------------
  function renderIntro() {
    root().replaceChildren(
      el('div', { class: 'd-card' },
        el('h2', { text: T('intro_title') }),
        el('p', { class: 'd-muted', text: T('intro_text') }),
        el('ul', { class: 'd-list' }, ['intro_1', 'intro_2', 'intro_3'].map(k => el('li', { text: T(k) }))),
        el('button', { class: 'primary', type: 'button', text: T('create_profile'), onclick: () => { D.tab = 'form'; render(); } })));
  }

  function field(label, control, help) {
    return el('label', { class: 'd-field' }, el('span', { text: label }), control, help ? el('small', { text: help }) : null);
  }
  function select(name, options, current, labelFn) {
    return el('select', { name }, el('option', { value: '', text: T('pick') }),
      options.map(o => el('option', { value: o, text: labelFn ? labelFn(o) : o, selected: o === current })));
  }

  function renderForm() {
    const p = D.me?.profile || {};
    const creating = !D.me?.profile;
    const username = p.telegram_username || tg?.initDataUnsafe?.user?.username || '';
    const f = {};
    const form = el('form', { class: 'd-form', novalidate: true },
      field(T('name'), f.display_name = el('input', { name: 'display_name', maxlength: 40, value: p.display_name || tg?.initDataUnsafe?.user?.first_name || '' })),
      field(T('birth'), f.birth_date = el('input', { name: 'birth_date', type: 'date', value: p.birth_date || '', max: new Date().toISOString().slice(0, 10) })),
      field(T('gender'), f.gender = select('gender', D.cfg.genders, p.gender, T)),
      field(T('looking'), f.looking_for = select('looking_for', D.cfg.looking_for, p.looking_for, T)),
      field(T('province'), f.province = select('province', D.cfg.provinces, p.province)),
      field(T('municipality'), f.municipality = el('input', { name: 'municipality', maxlength: 60, value: p.municipality || '' })),
      field(T('bio'), f.bio = el('textarea', { name: 'bio', maxlength: D.cfg.max_bio, rows: 4, value: p.bio || '' }), T('bio_help')),
      field(T('interests'), f.interests = el('input', { name: 'interests', value: (p.interests || []).join(', ') })),
      el('div', { class: 'd-field' }, el('span', { text: T('age_range') }),
        el('div', { class: 'd-row' },
          f.min_age = el('input', { type: 'number', inputmode: 'numeric', min: 18, max: 99, value: p.min_age || 18, 'aria-label': 'min' }),
          el('span', { text: '–' }),
          f.max_age = el('input', { type: 'number', inputmode: 'numeric', min: 18, max: 99, value: p.max_age || 60, 'aria-label': 'max' }))),
      el('div', { class: 'd-card soft' }, el('strong', { text: T('contact_title') }),
        el('label', { class: 'd-check' }, f.share_telegram = el('input', { type: 'checkbox', checked: !!p.share_telegram, disabled: !username }), el('span', { text: T('share_tg') + (username ? ' (@' + username + ')' : '') })),
        username ? null : el('small', { class: 'd-muted', text: T('tg_missing') }),
        field(T('whatsapp'), f.whatsapp = el('input', { name: 'whatsapp', type: 'tel', inputmode: 'tel', placeholder: '+53 5xxxxxxx', value: p.whatsapp || '' }))),
      creating ? el('label', { class: 'd-check' }, f.confirm_adult = el('input', { type: 'checkbox' }), el('span', { text: T('adult') })) : null,
      creating ? el('label', { class: 'd-check' }, f.accept_terms = el('input', { type: 'checkbox' }),
        el('span', {}, T('terms') + ' ', el('a', { href: '/terms.html', target: '_blank', rel: 'noopener', text: T('terms_link') }))) : null,
      el('div', { class: 'd-row' },
        el('button', { class: 'secondary', type: 'button', text: T('cancel'), onclick: () => { D.tab = D.me?.profile ? 'mine' : 'intro'; render(); } }),
        f.submit = el('button', { class: 'primary', type: 'submit', text: T('save') })));
    form.onsubmit = async (ev) => {
      ev.preventDefault();
      setBusy(f.submit, true, T('saving'));
      try {
        const body = {
          display_name: f.display_name.value, birth_date: f.birth_date.value, gender: f.gender.value, looking_for: f.looking_for.value,
          province: f.province.value, municipality: f.municipality.value, bio: f.bio.value,
          interests: f.interests.value.split(',').map(s => s.trim()).filter(Boolean),
          min_age: Number(f.min_age.value) || 18, max_age: Number(f.max_age.value) || 99,
          whatsapp: f.whatsapp.value, share_telegram: !!f.share_telegram.checked,
          confirm_adult: creating ? !!f.confirm_adult.checked : true, accept_terms: creating ? !!f.accept_terms.checked : true,
        };
        D.me = await jpost('/api/dating/profile', body);
        D.feed = []; toast(T('profile_saved'));
        D.tab = D.me.photos.length ? 'discover' : 'mine';
        if (!D.me.photos.length) toast(T('need_photo'));
        render();
      } catch (e) { fail(e); setBusy(f.submit, false, T('save')); }
    };
    root().replaceChildren(el('h2', { text: creating ? T('create_profile') : T('edit_profile') }), form);
  }

  // ---- mi perfil y fotos -----------------------------------------------
  function renderMine() {
    const p = D.me.profile;
    const badge = (s) => el('span', { class: 'd-badge ' + s, text: T('photo_' + s) });
    const grid = el('div', { class: 'photo-grid' }, D.me.photos.map(ph => el('div', { class: 'photo-tile' },
      el('img', { src: safePhoto(ph.url), alt: '' }), badge(ph.status),
      ph.status === 'rejected' && ph.reject_reason ? el('small', { text: ph.reject_reason }) : null,
      el('button', { class: 'photo-del', type: 'button', 'aria-label': T('photo_delete'), text: '×', onclick: async () => {
        try { await fetch('/api/dating/photos/' + Number(ph.id), { method: 'DELETE' }); D.me = await jpost('/api/dating/me'); renderMine(); } catch (e) { fail(e); } } }))));
    const input = el('input', { type: 'file', accept: 'image/*', hidden: true });
    const addBtn = el('button', { class: 'secondary', type: 'button', text: T('add_photo'), disabled: D.me.photos.length >= D.cfg.max_photos, onclick: () => input.click() });
    input.onchange = async () => {
      const file = input.files?.[0]; input.value = '';
      if (!file) return;
      setBusy(addBtn, true, T('uploading'));
      try {
        const image = await shrink(file);
        await jpost('/api/dating/photos', { image });
        toast(T('photo_sent'));
        D.me = await jpost('/api/dating/me');
      } catch (e) { fail(e); }
      renderMine();
    };
    const status = p.status === 'under_review' ? el('p', { class: 'd-notice', text: T('under_review') })
      : p.status === 'suspended' ? el('p', { class: 'd-notice danger', text: T('suspended') }) : null;
    root().replaceChildren(
      status,
      el('div', { class: 'd-card' },
        el('h2', { text: `${p.display_name}, ${p.age}` }),
        el('p', { class: 'd-muted', text: [p.province, p.municipality].filter(Boolean).join(' · ') }),
        p.bio ? el('p', { text: p.bio }) : null,
        el('button', { class: 'secondary', type: 'button', text: T('edit_profile'), onclick: () => { D.tab = 'form'; render(); } })),
      el('h3', { class: 'd-sub', text: T('photos') }), grid, input, addBtn,
      el('p', { class: 'd-muted small', text: T('photo_review_note') }),
      p.visible ? null : el('p', { class: 'd-notice', text: T('paused') }),
      el('button', { class: 'secondary', type: 'button', text: p.visible ? T('pause') : T('unpause'), onclick: async () => {
        try { await jpost('/api/dating/visibility', { visible: !p.visible }); D.me = await jpost('/api/dating/me'); renderMine(); } catch (e) { fail(e); } } }),
      el('button', { class: 'secondary danger-btn', type: 'button', text: T('delete_data'), onclick: async () => {
        if (!confirm(T('delete_confirm'))) return;
        try { await jpost('/api/dating/delete'); D.me = { profile: null, photos: [] }; D.feed = []; D.tab = 'intro'; toast(T('deleted')); render(); } catch (e) { fail(e); } } }));
  }
  // Reduce la foto en el dispositivo antes de subirla (ahorra datos móviles).
  function shrink(file) {
    return new Promise((resolve, reject) => {
      const url = URL.createObjectURL(file); const img = new Image();
      img.onload = () => {
        const scale = Math.min(1, 1080 / Math.max(img.naturalWidth, img.naturalHeight));
        const c = document.createElement('canvas'); c.width = Math.round(img.naturalWidth * scale); c.height = Math.round(img.naturalHeight * scale);
        c.getContext('2d').drawImage(img, 0, 0, c.width, c.height); URL.revokeObjectURL(url);
        resolve(c.toDataURL('image/jpeg', 0.85));
      };
      img.onerror = () => { URL.revokeObjectURL(url); reject(new Error(T('error'))); };
      img.src = url;
    });
  }

  // ---- descubrir --------------------------------------------------------
  async function loadFeed() {
    const d = await jpost('/api/dating/feed');
    D.feed = d.profiles || []; D.photoIdx = 0; D.premium = !!d.premium; D.likesLeft = d.likes_left;
    try { D.likesInfo = await jpost('/api/dating/likes'); } catch (_) { D.likesInfo = null; }
  }
  async function renderDiscover() {
    if (!D.feed.length) {
      root().replaceChildren(el('p', { class: 'd-muted', text: T('loading') }));
      try { await loadFeed(); } catch (e) {
        if (e.status === 409) { D.tab = 'mine'; toast(e.message); return render(); }
        return root().replaceChildren(el('p', { class: 'd-muted', text: e.message }));
      }
    }
    const p = D.feed[0];
    if (!p) {
      return root().replaceChildren(likesBanner(),
        el('div', { class: 'd-card center' }, el('h2', { text: T('empty_title') }), el('p', { class: 'd-muted', text: T('empty_text') }),
          el('button', { class: 'secondary', type: 'button', text: T('refresh'), onclick: renderDiscover })));
    }
    const photos = p.photos.map(safePhoto).filter(Boolean);
    const idx = Math.min(D.photoIdx, photos.length - 1);
    const shot = el('div', { class: 'd-photo' },
      photos.length ? el('img', { src: photos[idx], alt: '' }) : null,
      photos.length > 1 ? el('div', { class: 'd-dots' }, photos.map((_, i) => el('i', { class: i === idx ? 'on' : '' }))) : null,
      el('button', { class: 'tap left', type: 'button', 'aria-label': '‹', onclick: () => { D.photoIdx = Math.max(0, idx - 1); renderDiscover(); } }),
      el('button', { class: 'tap right', type: 'button', 'aria-label': '›', onclick: () => { D.photoIdx = Math.min(photos.length - 1, idx + 1); renderDiscover(); } }));
    const limitText = D.premium ? T('likes_unlimited') : (D.likesLeft != null ? T('likes_left', { n: D.likesLeft }) : '');
    root().replaceChildren(likesBanner(),
      el('div', { class: 'd-card profile' }, shot,
        el('div', { class: 'd-info' },
          el('h2', { text: `${p.display_name}, ${p.age}` }),
          el('p', { class: 'd-muted', text: [p.province, p.municipality].filter(Boolean).join(' · ') + (p.same_province ? ' · ' + T('same_province') : '') }),
          p.bio ? el('p', { text: p.bio }) : null,
          el('div', { class: 'chips' }, (p.interests || []).map(i => el('span', { class: 'chip', text: i }))),
          el('button', { class: 'text-btn small', type: 'button', text: T('report'), onclick: () => reportSheet(p.public_id) }))),
      el('div', { class: 'd-actions' },
        el('button', { class: 'round', type: 'button', 'aria-label': T('pass'), onclick: () => swipe('pass'), text: '✕' }),
        el('button', { class: 'round like', type: 'button', 'aria-label': T('like'), onclick: () => swipe('like'), text: '♥' }),
        el('button', { class: 'pill-btn', type: 'button', text: T('undo') + (D.premium ? '' : ' · Premium'), onclick: undo })),
      el('p', { class: 'd-muted center small', text: limitText }),
      el('p', { class: 'd-muted center small', text: T('safety') }));
  }
  function likesBanner() {
    const info = D.likesInfo;
    if (!info || !info.count) return null;
    const text = info.count === 1 ? T('likes_you_one') : T('likes_you', { n: info.count });
    return el('button', { class: 'd-banner', type: 'button', onclick: () => info.locked ? goPremium('locked') : renderLikes() },
      el('span', { text }), el('b', { text: info.locked ? T('see_who') : '→' }));
  }
  function renderLikes() {
    const list = D.likesInfo?.profiles || [];
    root().replaceChildren(
      el('button', { class: 'back-btn', type: 'button', onclick: renderDiscover }, el('span', { text: '← ' + T('back') })),
      list.map(p => el('div', { class: 'match-row' },
        el('img', { src: safePhoto(p.photos[0]), alt: '' }),
        el('div', { class: 'grow' }, el('strong', { text: `${p.display_name}, ${p.age}` }), el('small', { text: p.province })),
        el('button', { class: 'mini-btn', type: 'button', text: '✕', 'aria-label': T('pass'), onclick: () => quick(p, 'pass') }),
        el('button', { class: 'mini-btn like', type: 'button', text: '♥', 'aria-label': T('like'), onclick: () => quick(p, 'like') }))));
  }
  async function quick(p, action) {
    try { const r = await jpost('/api/dating/swipe', { target: p.public_id, action });
      D.likesInfo.profiles = D.likesInfo.profiles.filter(x => x.public_id !== p.public_id); D.likesInfo.count = D.likesInfo.profiles.length; D.feed = [];
      if (r.matched) matchSheet(r.match); else renderLikes();
    } catch (e) { swipeError(e); }
  }
  function swipeError(e) {
    if (e.status === 403 && /l[ií]mite|limit/i.test(e.message)) { toast(T('daily_limit')); goPremium('limit'); } else fail(e);
  }
  async function swipe(action) {
    if (D.busy || !D.feed.length) return;
    D.busy = true; const p = D.feed[0];
    try {
      const r = await jpost('/api/dating/swipe', { target: p.public_id, action });
      D.feed.shift(); D.photoIdx = 0; D.lastSwiped = true; if (r.likes_left != null) D.likesLeft = r.likes_left;
      if (r.matched) matchSheet(r.match);
      await renderDiscover();
    } catch (e) { swipeError(e); } finally { D.busy = false; }
  }
  async function undo() {
    if (!D.premium) return goPremium('locked');
    try { const r = await jpost('/api/dating/undo'); if (r.profile) D.feed.unshift(r.profile); D.photoIdx = 0; await renderDiscover(); } catch (e) { fail(e); }
  }

  // ---- matches (contacto por Telegram/WhatsApp) ------------------------
  function contactButtons(contacts) {
    const list = (contacts || []).filter(c => safeContact(c.url));
    if (!list.length) return el('small', { class: 'd-muted', text: T('no_contact') });
    return el('div', { class: 'contact-row' }, list.map(c =>
      el('button', { class: 'contact-btn ' + (c.type === 'whatsapp' ? 'wa' : 'tg'), type: 'button', text: T('write_to') + ' ' + (c.type === 'whatsapp' ? 'WhatsApp' : 'Telegram'), onclick: () => openExternal(c.url) })));
  }
  async function renderMatches() {
    root().replaceChildren(el('p', { class: 'd-muted', text: T('loading') }));
    try {
      const d = await jpost('/api/dating/matches');
      if (!d.matches.length) return root().replaceChildren(el('div', { class: 'd-card center' }, el('p', { class: 'd-muted', text: T('matches_empty') })));
      root().replaceChildren(d.matches.map(m => el('div', { class: 'd-card match' },
        el('div', { class: 'match-row' },
          el('img', { src: safePhoto(m.photos[0]), alt: '' }),
          el('div', { class: 'grow' }, el('strong', { text: `${m.display_name}, ${m.age}` }), el('small', { text: [m.province, m.municipality].filter(Boolean).join(' · ') })),
          el('button', { class: 'mini-btn', type: 'button', text: '⋯', 'aria-label': T('report'), onclick: () => manageSheet(m) })),
        contactButtons(m.contacts))));
    } catch (e) { root().replaceChildren(el('p', { class: 'd-muted', text: e.message })); }
  }

  // ---- hojas modales ----------------------------------------------------
  function sheet(...kids) {
    const close = () => m.remove();
    const m = el('div', { class: 'modal dating-modal' }, el('div', { class: 'crop-backdrop', onclick: close }), el('div', { class: 'result-sheet' }, kids));
    m.close = close; $('#datingScreen').append(m); return m;
  }
  function matchSheet(match) {
    const m = sheet(el('div', { class: 'center' },
      el('h2', { text: T('match_title') }),
      el('p', { class: 'd-muted', text: T('match_text', { n: match.display_name }) }),
      contactButtons(match.contacts),
      el('button', { class: 'primary', type: 'button', text: T('keep'), onclick: () => m.close() })));
  }
  function manageSheet(match) {
    const m = sheet(el('h3', { text: match.display_name }),
      el('button', { class: 'secondary', type: 'button', text: T('unmatch'), onclick: async () => {
        if (!confirm(T('unmatch_confirm'))) return;
        try { await jpost('/api/dating/unmatch', { match_id: match.match_id }); toast(T('unmatched')); m.close(); renderMatches(); } catch (e) { fail(e); } } }),
      el('button', { class: 'secondary', type: 'button', text: T('block'), onclick: async () => {
        if (!confirm(T('block_confirm'))) return;
        try { await jpost('/api/dating/block', { target: match.public_id }); toast(T('blocked')); m.close(); D.feed = []; renderMatches(); } catch (e) { fail(e); } } }),
      el('button', { class: 'secondary danger-btn', type: 'button', text: T('report'), onclick: () => { m.close(); reportSheet(match.public_id); } }),
      el('button', { class: 'cancel-btn', type: 'button', text: T('cancel'), onclick: () => m.close() }));
  }
  function reportSheet(target) {
    const reason = el('select', {}, D.cfg.report_reasons.map(r => el('option', { value: r, text: T('r_' + r) })));
    const details = el('textarea', { maxlength: 500, rows: 3, placeholder: '…' });
    const m = sheet(el('h3', { text: T('report') }), field(T('report_reason'), reason), details,
      el('button', { class: 'primary', type: 'button', text: T('report_send'), onclick: async () => {
        try { await jpost('/api/dating/report', { target, reason: reason.value, details: details.value }); toast(T('report_sent'));
          m.close(); D.feed = D.feed.filter(p => p.public_id !== target); if (D.tab === 'discover') renderDiscover(); } catch (e) { fail(e); } } }),
      el('button', { class: 'cancel-btn', type: 'button', text: T('cancel'), onclick: () => m.close() }));
  }

  // ---- arranque ---------------------------------------------------------
  const nav = $('[data-nav="dating"]');
  if (nav) nav.onclick = openDating;
  window.openDating = openDating;
})();
