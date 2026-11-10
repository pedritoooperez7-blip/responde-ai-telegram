/* LiggaCuba Citas — interfaz de la Mini App.
 *
 * No hay chat dentro de la app: al hacer match se muestran los botones para
 * hablar por Telegram o WhatsApp (los canales que cada persona decidió compartir).
 * Reutiliza de app.js: state, $, $$, toast, tg, showPremium, home().
 * Todo el contenido de otros usuarios se inserta con textContent (nunca innerHTML).
 */
(function () {
  'use strict';
  // Helper: usa tg.showConfirm (nativo en Telegram) o window.confirm como fallback.
  // window.confirm() está bloqueado en iOS Telegram y congela la app.
  function datingConfirm(msg) {
    return new Promise(resolve => {
      if (tg && tg.showConfirm) {
        try { return tg.showConfirm(msg, ok => resolve(!!ok)); } catch (_) {}
      }
      resolve(window.confirm(msg));
    });
  }

  const TEXT = {
    es: {
      form_create_sub: 'Cuéntanos un poco de ti. Tarda menos de un minuto.', form_edit_sub: 'Actualiza la información que ven los demás.',
      sec_basic: 'Lo básico', sec_identity: 'Identidad y preferencias', sec_location: 'Dónde vives', sec_about: 'Sobre ti', sec_age: 'Edad de las personas que buscas', sec_contact: 'Contacto', sec_legal: 'Confirmaciones',
      chars_left: '{n} caracteres restantes', interests_ph: 'música, viajes, cine…', bio_ph: 'Cuenta algo sobre ti…', name_ph: 'Tu nombre', municipality_ph: 'Ej. Plaza de la Revolución', age_to: 'a', age_summary: 'De {a} a {b} años',
      title: 'Citas', tab_discover: 'Descubrir', tab_matches: 'Matches', tab_mine: 'Mi perfil',
      intro_title: 'Conoce gente nueva', intro_text: 'Dale like a quien te guste. Si hay match, hablan por Telegram o WhatsApp: en LiggaCuba no hay chat interno.',
      intro_1: 'Solo mayores de 18 años', intro_2: 'Tu contacto lo ven únicamente tus matches', intro_3: 'Todas las fotos se revisan antes de publicarse',
      create_profile: 'Crear mi perfil', edit_profile: 'Editar perfil', save: 'Guardar', saving: 'Guardando…', cancel: 'Cancelar', back: 'Atrás',
      name: 'Nombre', birth: 'Fecha de nacimiento', gender: 'Soy', looking: 'Quiero conocer', province: 'Provincia', province_ph: 'Selecciona tu provincia', municipality: 'Municipio (opcional)',
      bio: 'Sobre mí', bio_help: 'Sin enlaces ni usuarios. Máximo 300 caracteres.', interests: 'Intereses (separados por comas)', age_range: 'Rango de edad que buscas',
      contact_title: 'Cómo te escriben tus matches', share_tg: 'Compartir mi usuario de Telegram', tg_missing: 'Tu cuenta de Telegram no tiene @usuario. Créalo en Ajustes de Telegram para poder compartirlo.',
      whatsapp: 'WhatsApp (opcional)', whatsapp_abroad: 'WhatsApp (opcional, con código de país)', retry: 'Reintentar', adult: 'Confirmo que soy mayor de 18 años', terms: 'Acepto los términos de Citas',
      terms_link: 'Ver términos', hombre: 'Hombre', mujer: 'Mujer', otro: 'Otro', hombres: 'Hombres', mujeres: 'Mujeres', todos: 'Todos',
      pick: 'Selecciona…', profile_saved: 'Perfil guardado', need_photo: 'Sube al menos una foto para ver perfiles.',
      photos: 'Mis fotos', add_photo: 'Agregar foto', photo_pending: 'En revisión', photo_approved: 'Aprobada', photo_rejected: 'Rechazada', photo_delete: 'Eliminar foto',
      photo_review_note: 'Tu perfil aparece para otras personas cuando una foto sea aprobada.', uploading: 'Subiendo…', photo_sent: 'Foto enviada a revisión',
      pause: 'Pausar mi perfil', unpause: 'Mostrar mi perfil', paused: 'Tu perfil está pausado y no aparece para nadie.', delete_data: 'Borrar mis datos de Citas',
      delete_confirm: '¿Borrar tu perfil, fotos, likes y matches de Citas? No se puede deshacer.', deleted: 'Datos de Citas eliminados',
      under_review: 'Tu perfil está en revisión y no aparece para otras personas por ahora.', suspended: 'Tu perfil de Citas está suspendido. Contacta a soporte.',
      pass: 'Pasar', like: 'Me gusta', undo: 'Deshacer', likes_left: 'Te quedan {n} likes hoy', likes_unlimited: 'Premium · likes ilimitados',
      share_earn_cta: '🎁 Comparte en tu estado de WhatsApp y gana +10 likes gratis hoy', share_earn_btn: 'Compartir y ganar +10 likes', share_earn_done: '✅ ¡Ganaste +10 likes extra hoy!', share_earn_confirm: 'Confirmando…',
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
      form_create_sub: 'Tell us a little about you. It takes under a minute.', form_edit_sub: 'Update the information others can see.',
      sec_basic: 'The basics', sec_identity: 'Identity and preferences', sec_location: 'Where you live', sec_about: 'About you', sec_age: 'Age of the people you look for', sec_contact: 'Contact', sec_legal: 'Confirmations',
      chars_left: '{n} characters left', interests_ph: 'music, travel, movies…', bio_ph: 'Tell something about yourself…', name_ph: 'Your name', municipality_ph: 'e.g. Downtown', age_to: 'to', age_summary: 'From {a} to {b} years old',
      title: 'Dating', tab_discover: 'Discover', tab_matches: 'Matches', tab_mine: 'My profile',
      intro_title: 'Meet new people', intro_text: 'Like the people you want to meet. On a match you talk on Telegram or WhatsApp: LiggaCuba has no in-app chat.',
      intro_1: 'Adults 18+ only', intro_2: 'Only your matches can see your contact', intro_3: 'Every photo is reviewed before it goes live',
      create_profile: 'Create my profile', edit_profile: 'Edit profile', save: 'Save', saving: 'Saving…', cancel: 'Cancel', back: 'Back',
      name: 'Name', birth: 'Date of birth', gender: 'I am', looking: 'I want to meet', province: 'Province', province_ph: 'Select your province', municipality: 'Municipality (optional)',
      bio: 'About me', bio_help: 'No links or usernames. 300 characters max.', interests: 'Interests (comma separated)', age_range: 'Age range you are looking for',
      contact_title: 'How your matches reach you', share_tg: 'Share my Telegram username', tg_missing: 'Your Telegram account has no @username. Create one in Telegram settings to share it.',
      whatsapp: 'WhatsApp (optional)', whatsapp_abroad: 'WhatsApp (optional, with country code)', retry: 'Retry', adult: 'I confirm I am 18 or older', terms: 'I accept the Dating terms',
      terms_link: 'View terms', hombre: 'Man', mujer: 'Woman', otro: 'Other', hombres: 'Men', mujeres: 'Women', todos: 'Everyone',
      pick: 'Select…', profile_saved: 'Profile saved', need_photo: 'Upload at least one photo to see profiles.',
      photos: 'My photos', add_photo: 'Add photo', photo_pending: 'In review', photo_approved: 'Approved', photo_rejected: 'Rejected', photo_delete: 'Delete photo',
      photo_review_note: 'Your profile shows to others once a photo is approved.', uploading: 'Uploading…', photo_sent: 'Photo sent for review',
      pause: 'Pause my profile', unpause: 'Show my profile', paused: 'Your profile is paused and hidden from everyone.', delete_data: 'Delete my Dating data',
      delete_confirm: 'Delete your Dating profile, photos, likes and matches? This cannot be undone.', deleted: 'Dating data deleted',
      under_review: 'Your profile is under review and hidden for now.', suspended: 'Your Dating profile is suspended. Contact support.',
      pass: 'Pass', like: 'Like', undo: 'Undo', likes_left: '{n} likes left today', likes_unlimited: 'Premium · unlimited likes',
      share_earn_cta: '🎁 Share to your WhatsApp status and get +10 free likes today', share_earn_btn: 'Share & get +10 likes', share_earn_done: '✅ You earned +10 extra likes today!', share_earn_confirm: 'Confirming…',
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

  const ABROAD = 'Fuera de Cuba';
  // Móvil cubano: 8 dígitos (el +53 se pone solo). Acepta pegar el número con 53 delante.
  const cubaLocal = (v) => { let d = String(v || '').replace(/\D/g, ''); if (d.length > 8 && d.startsWith('53')) d = d.slice(2); return d.slice(0, 8); };
  const D = { cfg: null, warm: null, me: null, tab: 'discover', feed: [], photoIdx: 0, busy: false, likesInfo: null, lastSwiped: false };
  const root = () => $('#datingBody');
  // replaceChildren() convierte null y arreglos en texto ("null", "[object HTMLDivElement]"): se aplanan y filtran antes.
  const setBody = (...kids) => root().replaceChildren(...kids.flat(Infinity).filter(k => k != null && k !== false));

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
    ['#homeScreen', '#profileScreen', '#settingsScreen', '#moreScreen', '#premiumScreen', '#transferScreen', '#paymentMethodScreen', '#proofScreen', '#supportScreen','#businessAdScreen'].forEach(s => $(s)?.classList.add('hidden'));
    $('#datingScreen').classList.remove('hidden');
    $('.bottom-nav').classList.remove('hidden');
    $$('.nav-item').forEach(b => b.classList.toggle('active', b.dataset.nav === 'dating'));
  }
  // Las peticiones base se hacen en paralelo (antes eran 4 en cadena: config → me → feed → likes).
  function startBase() {
    const cfgP = D.cfg ? Promise.resolve(D.cfg)
      : fetch('/api/dating/config')
          .then(r => r.ok ? r.json() : Promise.reject(new Error(T('error'))))
          .catch(e => Promise.reject(e));
    return Promise.all([cfgP, jpost('/api/dating/me')]).then(([cfg, me]) => { D.cfg = cfg; D.me = me; return me; }).catch(e => { fail(e); return Promise.reject(e); });
  }
  async function fetchFeedBundle() {
    const [d, likes] = await Promise.all([jpost('/api/dating/feed'), jpost('/api/dating/likes').catch(() => null)]);
    (d.profiles || []).slice(0, 2).forEach(p => { const u = safePhoto((p.photos || [])[0]); if (u) { const i = new Image(); i.src = u; } });  // precarga fotos
    return { d, likes };
  }
  // Se llama al iniciar sesión: deja listos config, perfil y feed antes de que la persona abra Citas.
  function warmDating() {
    if (D.warm && Date.now() - D.warm.at < 60000) return;
    const base = startBase();
    const feed = base.then(me => (me.profile && me.profile.status !== 'suspended') ? fetchFeedBundle() : null).catch(() => null);
    D.warm = { at: Date.now(), base, feed };
    base.catch(() => { D.warm = null; });
  }
  const entryTab = () => { D.tab = D.me.profile ? (['intro', 'form'].includes(D.tab) ? 'discover' : D.tab) : 'intro'; };
  function _handleChatDeepLink() {
    try {
      const startParam = (typeof tg !== 'undefined' && tg?.initDataUnsafe?.start_param) || '';
      if (startParam.startsWith('chat_') && window.LiggaChat) {
        window.LiggaChat.handleDeepLink(startParam);
      }
    } catch (_) { /* ignore */ }
  }
  async function openDating() {
    hideOthers();
    const warm = D.warm && Date.now() - D.warm.at < 60000 ? D.warm : null;
    if (D.cfg && D.me) {           // ya hay datos: se pinta al instante y se refresca en segundo plano
      entryTab(); render();
      _handleChatDeepLink();
      if (!warm) startBase().catch(() => {});
      return;
    }
    setBody(el('p', { class: 'd-muted', text: T('loading') }));
    try {
      await (warm ? warm.base : startBase());
      entryTab(); render();
      _handleChatDeepLink();
    } catch (e) {
      D.warm = null;
      setBody(el('p', { class: 'd-muted', text: e.message || T('error') }),
        el('button', { class: 'secondary', type: 'button', text: T('retry'), onclick: openDating }));
    }
  }
  function render() {
    $('#datingScreen').classList.remove('wz-on');
    if (D.tab !== 'form') $('.bottom-nav').classList.remove('hidden');
    const head = $('#datingTabs');
    const hasProfile = !!D.me?.profile;
    head.classList.toggle('hidden', !hasProfile);
    head.replaceChildren(...['discover', 'matches', 'mine'].map(t =>
      el('button', { class: 'segment' + (D.tab === t ? ' active' : ''), type: 'button', text: T('tab_' + t), onclick: () => { D.tab = t; render(); } })));
    if (!hasProfile && D.tab !== 'form') return renderIntro();
    if (D.tab === 'form') return renderForm();
    const status = D.me.profile.status;
    if (D.tab === 'discover') {
      if (status === 'suspended') return setBody(el('p', { class: 'd-notice danger', text: T('suspended') }));
      return renderDiscover();
    }
    if (D.tab === 'matches') return renderMatches();
    return renderMine();
  }

  // ---- introducción y formulario ---------------------------------------
  function renderIntro() {
    setBody(
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

  // Selector de opción única con botones (sustituye al <select>); el valor vive en un input oculto.
  function chipGroup(name, options, current, labelFn) {
    const input = el('input', { type: 'hidden', name, value: current || '' });
    const wrap = el('div', { class: 'df-chips', role: 'radiogroup' });
    const paint = () => wrap.querySelectorAll('button').forEach(b => {
      const on = b.dataset.v === input.value;
      b.classList.toggle('on', on); b.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
    options.forEach(o => wrap.append(el('button', {
      class: 'df-chip', type: 'button', 'data-v': o, text: labelFn ? labelFn(o) : o,
      onclick: () => { input.value = o; paint(); },
    })));
    paint();
    return { node: el('div', {}, wrap, input), input };
  }
  function section(icon, title, ...kids) {
    return el('div', { class: 'df-section' },
      el('div', { class: 'df-sec-head' }, el('span', { class: 'df-sec-icon' }, el('i', { class: 'fa-solid ' + icon })), el('h3', { text: title })),
      ...kids);
  }
  function dfield(label, control, help) {
    return el('label', { class: 'df-field' }, el('span', { class: 'df-label', text: label }), control, help ? el('small', { text: help }) : null);
  }

  // ---- asistente de perfil (una pregunta por pantalla) -------------------
  // Mismos colores y componentes que el resto de la app. Las respuestas de estilo de vida
  // y objetivos se guardan como preferencias (lista blanca en el servidor) y ordenan el feed.
  const WT = {
    es: {
      stage_0: 'Sobre ti', stage_1: 'Tu tipo', stage_2: 'Estilo de vida', stage_3: 'Objetivos de pareja', stage_4: 'Casi listo',
      next: 'Continuar', skip: 'Omitir', done_btn: 'Listo', create: 'Crear mi perfil', save: 'Guardar cambios', edit: 'Editar',
      multi_sub: 'Elige todas las que quieras', opt_sub: 'Opcional',
      name_t: '¿Cómo te llamas?', name_s: 'Es el nombre que verán las demás personas.', name_bad: 'Escribe al menos 2 letras, sin enlaces ni @usuarios.',
      birth_t: '¿Cuál es tu fecha de nacimiento?', birth_s: 'Solo para mayores de 18 años. Nunca mostramos tu fecha: solo tu edad.',
      birth_age: 'Tienes {n} años', birth_under: 'Citas es solo para mayores de 18 años.', birth_bad: 'Escribe una fecha válida.',
      birth_locked: 'La fecha de nacimiento no se puede cambiar. Si te equivocaste, contacta a soporte.',
      ages_t: '¿Qué rango de edad te interesa?', ages_s: 'Solo verás personas dentro de este rango (y ellas deben encajar con tu edad).', ages_bad: 'La edad mínima no puede ser mayor que la máxima (entre 18 y 99).',
      loc_t: '¿Dónde vives?', loc_s: 'Mostramos primero a quienes viven cerca de ti.', loc_pick: 'Elige tu provincia.',
      about_t: 'Cuéntanos algo de ti', about_s: 'Opcional. Sin enlaces ni @usuarios: tu contacto solo lo ven tus matches.',
      contact_t: '¿Cómo te escriben tus matches?', contact_s: 'Solo lo verán las personas con las que hagas match. Elige al menos un canal.', contact_bad: 'Elige Telegram o escribe un WhatsApp válido (con código de país).', contact_bad_cu: 'Escribe un número de WhatsApp cubano válido: 8 dígitos, empieza por 5.',
      legal_t: 'Último paso', legal_s: 'Confirma estas dos cosas para crear tu perfil.', legal_bad: 'Debes confirmar las dos casillas.',
      sum_t: 'Tu perfil de Citas', sum_s: 'Toca una sección para cambiarla.', n_answers: '{n} respuestas', cancel: 'Cancelar',
      done_t: '¡Tu perfil está listo!', done_s: 'Último paso: sube tus fotos. Se revisan antes de que tu perfil aparezca para otras personas.', add_photos: 'Agregar fotos',
      prem_t: 'Con Premium', prem_s: 'Likes ilimitados, ver quién te dio like y deshacer el último swipe.', see_premium: 'Ver Premium',
      in_common: '{n} cosas en común', in_common_one: '1 cosa en común', draft_saved: 'Guardamos tu avance en este teléfono.',
    },
    en: {
      stage_0: 'About you', stage_1: 'Your type', stage_2: 'Lifestyle', stage_3: 'Relationship goals', stage_4: 'Almost done',
      next: 'Continue', skip: 'Skip', done_btn: 'Done', create: 'Create my profile', save: 'Save changes', edit: 'Edit',
      multi_sub: 'Choose as many as you like', opt_sub: 'Optional',
      name_t: "What's your name?", name_s: 'This is the name other people will see.', name_bad: 'Use at least 2 letters, with no links or @usernames.',
      birth_t: "What's your date of birth?", birth_s: 'Adults 18+ only. We never show your date, only your age.',
      birth_age: 'You are {n} years old', birth_under: 'Dating is for adults 18+ only.', birth_bad: 'Enter a valid date.',
      birth_locked: 'Your date of birth cannot be changed. If you made a mistake, contact support.',
      ages_t: 'What age range interests you?', ages_s: 'You will only see people in this range (and they must fit your age).', ages_bad: 'Minimum age cannot be higher than maximum (18 to 99).',
      loc_t: 'Where do you live?', loc_s: 'We show people who live near you first.', loc_pick: 'Choose your province.',
      about_t: 'Tell us about yourself', about_s: 'Optional. No links or @usernames: only your matches see your contact.',
      contact_t: 'How should your matches reach you?', contact_s: 'Only people you match with will see it. Pick at least one channel.', contact_bad: 'Pick Telegram or enter a valid WhatsApp number (with country code).', contact_bad_cu: 'Enter a valid Cuban WhatsApp number: 8 digits, starting with 5.',
      legal_t: 'Last step', legal_s: 'Confirm these two things to create your profile.', legal_bad: 'You must tick both boxes.',
      sum_t: 'Your Dating profile', sum_s: 'Tap a section to change it.', n_answers: '{n} answers', cancel: 'Cancel',
      done_t: 'Your profile is ready!', done_s: 'Last step: add your photos. They are reviewed before your profile shows to other people.', add_photos: 'Add photos',
      prem_t: 'With Premium', prem_s: 'Unlimited likes, see who liked you and undo your last swipe.', see_premium: 'See Premium',
      in_common: '{n} things in common', in_common_one: '1 thing in common', draft_saved: 'Your progress is saved on this phone.',
    },
  };
  const L = () => (state.language === 'en' ? 'en' : 'es');
  const X = (k, vars) => {
    let s = WT[L()][k] ?? WT.es[k] ?? k;
    if (vars) for (const [a, b] of Object.entries(vars)) s = s.replace('{' + a + '}', b);
    return s;
  };
  const lab = (o) => o[L()] || o.es;
  const op = (v, icon, es, en) => ({ v, icon, es, en });
  // kind: single | multi | name | birth | ages | location | about | contact | legal
  // field = campo del perfil; pref = clave dentro de prefs (ver PREF_SCHEMA en dating.py)
  const STEPS = [
    { id: 'gender', stage: 0, kind: 'single', field: 'gender', required: true, title: { es: '¿Cuál es tu género?', en: 'What is your gender?' },
      opts: [op('hombre', 'fa-mars', 'Hombre', 'Man'), op('mujer', 'fa-venus', 'Mujer', 'Woman'), op('otro', 'fa-genderless', 'Otro', 'Other')] },
    { id: 'name', stage: 0, kind: 'name' },
    { id: 'birth', stage: 0, kind: 'birth' },
    { id: 'intent', stage: 0, kind: 'multi', pref: 'intent', title: { es: '¿Qué buscas ahora mismo?', en: 'What are you looking for right now?' },
      opts: [op('serious', 'fa-heart', 'Una relación seria', 'A serious relationship'), op('casual', 'fa-champagne-glasses', 'Salir y ver qué surge', 'Go out and see what happens'),
        op('online', 'fa-mobile-screen', 'Hablar online', 'Chat online'), op('unsure', 'fa-compass', 'Aún no lo sé', 'Not sure yet')] },
    { id: 'important', stage: 0, kind: 'multi', pref: 'important', title: { es: '¿Qué es lo más importante para ti?', en: 'What matters most to you?' },
      opts: [op('travel', 'fa-plane', 'Alguien con quien viajar', 'Someone to travel with'), op('emotional', 'fa-heart', 'Conexión emocional', 'Emotional connection'),
        op('fun', 'fa-face-laugh', 'Diversión y espontaneidad', 'Fun and spontaneity'), op('family', 'fa-house', 'Formar una familia', 'Building a family'),
        op('goals', 'fa-bullseye', 'Una pareja que apoye mis metas', 'A partner who supports my goals')] },

    { id: 'looking', stage: 1, kind: 'single', field: 'looking_for', required: true, title: { es: '¿A quién te interesa conocer?', en: 'Who do you want to meet?' },
      opts: [op('hombres', 'fa-mars', 'Hombres', 'Men'), op('mujeres', 'fa-venus', 'Mujeres', 'Women'), op('todos', 'fa-users', 'Todos', 'Everyone')] },
    { id: 'ages', stage: 1, kind: 'ages' },
    { id: 'attention', stage: 1, kind: 'multi', pref: 'attention', title: { es: '¿Qué es lo primero que te llama la atención?', en: 'What do you notice first?' },
      opts: [op('eyes', 'fa-eye', 'Ojos', 'Eyes'), op('hair', 'fa-scissors', 'Pelo', 'Hair'), op('smile', 'fa-face-smile', 'Sonrisa', 'Smile'),
        op('style', 'fa-shirt', 'Estilo', 'Style'), op('voice', 'fa-microphone', 'Voz', 'Voice'), op('humor', 'fa-face-laugh', 'Sentido del humor', 'Sense of humor')] },
    { id: 'distance', stage: 1, kind: 'single', pref: 'distance', title: { es: '¿A qué distancia debería vivir esa persona?', en: 'How far away should they live?' },
      opts: [op('neighborhood', 'fa-location-dot', 'En mi barrio', 'In my neighborhood'), op('city', 'fa-city', 'En mi ciudad', 'In my city'),
        op('province', 'fa-map', 'En mi provincia', 'In my province'), op('any', 'fa-earth-americas', 'La distancia no importa', 'Distance does not matter')] },
    { id: 'first_move', stage: 1, kind: 'single', pref: 'first_move', title: { es: '¿Quién debería dar el primer paso?', en: 'Who should make the first move?' },
      opts: [op('me', 'fa-hand-point-up', 'Yo', 'Me'), op('them', 'fa-hand-holding-heart', 'La otra persona', 'The other person'), op('either', 'fa-shuffle', 'Me da igual', 'Either one')] },

    { id: 'work', stage: 2, kind: 'single', pref: 'work', title: { es: '¿Cómo es tu horario de trabajo?', en: 'What is your work schedule like?' },
      opts: [op('office', 'fa-laptop', 'Horario de oficina', 'Office hours'), op('flexible', 'fa-clock', 'Horario flexible', 'Flexible hours'),
        op('night', 'fa-moon', 'Turnos de noche', 'Night shifts'), op('own', 'fa-briefcase', 'Tengo mi propio negocio', 'I run my own business')] },
    { id: 'weekend', stage: 2, kind: 'single', pref: 'weekend', title: { es: '¿Cómo sueles pasar el fin de semana?', en: 'How do you usually spend weekends?' },
      opts: [op('out', 'fa-people-group', 'Saliendo y conociendo gente', 'Going out and meeting people'), op('sport', 'fa-person-running', 'Deporte y aire libre', 'Sports and outdoors'),
        op('home', 'fa-couch', 'En casa, recargando pilas', 'At home, recharging'), op('work', 'fa-book', 'Trabajando o estudiando', 'Working or studying')] },
    { id: 'social', stage: 2, kind: 'single', pref: 'social', title: { es: '¿Cómo es tu energía social?', en: 'What is your social energy like?' },
      opts: [op('party', 'fa-champagne-glasses', 'Soy el alma de la fiesta', 'Life of the party'), op('small', 'fa-user-group', 'Me abro en grupos pequeños', 'I open up in small groups'),
        op('reserved', 'fa-user', 'Soy reservado/a hasta tener confianza', 'Reserved until I trust people'), op('mood', 'fa-gauge', 'Depende de mi humor', 'Depends on my mood')] },
    { id: 'first_date', stage: 2, kind: 'single', pref: 'first_date', title: { es: '¿Cómo sería tu primera cita ideal?', en: 'What would your ideal first date be?' },
      opts: [op('coffee', 'fa-mug-hot', 'Café y un paseo', 'Coffee and a walk'), op('dinner', 'fa-utensils', 'Cena y copas', 'Dinner and drinks'),
        op('active', 'fa-person-running', 'Algo activo', 'Something active'), op('undecided', 'fa-circle-question', 'Aún no lo he decidido', 'Not decided yet')] },

    { id: 'kids', stage: 3, kind: 'single', pref: 'kids', title: { es: '¿Hijos en tus planes?', en: 'Are kids in your plans?' },
      opts: [op('want', 'fa-baby', 'Quiero tener hijos', 'I want kids'), op('open', 'fa-seedling', 'Estoy abierto/a a la idea', 'Open to the idea'),
        op('have', 'fa-children', 'Ya tengo hijos', 'I already have kids'), op('no', 'fa-ban', 'Prefiero no tener hijos', 'I prefer not to have kids')] },
    { id: 'ambition', stage: 3, kind: 'single', pref: 'ambition', title: { es: '¿Qué nivel de ambición buscas en tu pareja?', en: 'What level of ambition do you look for in a partner?' },
      opts: [op('career', 'fa-briefcase', 'Con foco en su carrera', 'Career-focused'), op('balanced', 'fa-scale-balanced', 'Equilibrio entre trabajo y vida', 'Work-life balance'),
        op('family', 'fa-house', 'La familia primero', 'Family first'), op('any', 'fa-shuffle', 'No importa', 'Does not matter')] },
    { id: 'common', stage: 3, kind: 'multi', pref: 'common', title: { es: '¿Qué te gustaría tener en común?', en: 'What would you like to have in common?' },
      opts: [op('traditional', 'fa-ring', 'Valores tradicionales', 'Traditional values'), op('home', 'fa-house', 'Hogar y comodidad', 'Home and comfort'),
        op('travel', 'fa-plane', 'Viajes y descubrimientos', 'Travel and discovery'), op('growth', 'fa-book', 'Desarrollo personal', 'Personal growth'),
        op('career', 'fa-briefcase', 'Carrera y ambición', 'Career and ambition'), op('sport', 'fa-dumbbell', 'Deporte y aire libre', 'Sports and outdoors'),
        op('cinema', 'fa-film', 'Cine y música', 'Movies and music'), op('nightlife', 'fa-champagne-glasses', 'Vida nocturna y diversión', 'Nightlife and fun')] },
    { id: 'dealbreakers', stage: 3, kind: 'multi', pref: 'dealbreakers', title: { es: '¿Algo que no aceptarías?', en: 'Anything you would not accept?' },
      opts: [op('smoke', 'fa-ban-smoking', 'Que fume', 'Smoking'), op('no_relationship', 'fa-heart-crack', 'Que no quiera una relación', 'Not wanting a relationship'),
        op('far', 'fa-location-dot', 'Que viva muy lejos', 'Living too far away'), op('values', 'fa-scale-balanced', 'Valores muy distintos', 'Very different values'),
        op('none', 'fa-xmark', 'Ninguna de estas', 'None of these')] },

    { id: 'location', stage: 4, kind: 'location' },
    { id: 'about', stage: 4, kind: 'about' },
    { id: 'contact', stage: 4, kind: 'contact' },
    { id: 'legal', stage: 4, kind: 'legal' },
  ];
  const WZ_KEY = 'liggacuba_dating_draft_v1';
  let W = null;

  const ageOf = (iso) => {
    const b = new Date(iso + 'T00:00:00'); if (!iso || isNaN(b)) return null;
    const t = new Date(); let n = t.getFullYear() - b.getFullYear();
    if (t.getMonth() < b.getMonth() || (t.getMonth() === b.getMonth() && t.getDate() < b.getDate())) n--;
    return n;
  };
  const tgUser = () => D.me?.profile?.telegram_username || tg?.initDataUnsafe?.user?.username || '';
  const wzSteps = () => STEPS.filter(s => (W.only == null ? true : s.stage === W.only) && (s.kind !== 'legal' || W.creating));
  const wzGet = (s) => s.field ? W.a[s.field] : W.a.prefs[s.pref];
  const wzSet = (s, v) => { if (s.field) W.a[s.field] = v; else if (v == null || (Array.isArray(v) && !v.length)) delete W.a.prefs[s.pref]; else W.a.prefs[s.pref] = v; };
  const wzEmpty = (s) => {
    if (s.kind === 'about') return !(W.a.bio || '').trim() && !(W.a.interests || '').trim();
    if (['single', 'multi'].includes(s.kind)) { const v = wzGet(s); return !v || (Array.isArray(v) && !v.length); }
    return false;
  };
  const wzOptional = (s) => !s.required && ['single', 'multi', 'about'].includes(s.kind) && !(s.field);
  function wzPersist() {
    if (!W.creating) return;
    try {
      const { accept_terms, confirm_adult, ...rest } = W.a;
      localStorage.setItem(WZ_KEY, JSON.stringify({ a: rest, i: W.i }));
    } catch (_) { /* sin almacenamiento: el avance simplemente no se guarda */ }
  }
  const wzClearDraft = () => { try { localStorage.removeItem(WZ_KEY); } catch (_) { /* nada */ } };

  function wzValid(s) {
    const a = W.a;
    switch (s.kind) {
      case 'single': return { ok: s.required ? !!wzGet(s) : true };
      case 'name': { const n = (a.display_name || '').trim(); return /(https?:|www\.|t\.me|wa\.me|@\w{4,})/i.test(n) || n.length < 2 ? { ok: false, msg: n ? X('name_bad') : '' } : { ok: true }; }
      case 'birth': {
        if (W.lockedBirth) return { ok: true };
        const n = ageOf(a.birth_date);
        if (n == null) return { ok: false, msg: a.birth_date ? X('birth_bad') : '' };
        if (n < 18) return { ok: false, msg: X('birth_under') };
        if (n > 99) return { ok: false, msg: X('birth_bad') };
        return { ok: true, msg: X('birth_age', { n }) };
      }
      case 'ages': { const lo = Number(a.min_age), hi = Number(a.max_age); return lo >= 18 && hi <= 99 && lo <= hi ? { ok: true } : { ok: false, msg: X('ages_bad') }; }
      case 'location': return a.province ? { ok: true } : { ok: false, msg: '' };
      case 'contact': { const digits = String(a.whatsapp || '').replace(/\D/g, ''); const abroad = a.province === ABROAD;
        const wa = abroad ? (digits.length >= 8 && digits.length <= 15) : /^535\d{7}$/.test(digits);
        return (a.share_telegram && tgUser()) || wa ? { ok: true } : { ok: false, msg: (a.whatsapp || a.share_telegram) ? X(abroad ? 'contact_bad' : 'contact_bad_cu') : '' }; }
      case 'legal': return a.confirm_adult && a.accept_terms ? { ok: true } : { ok: false, msg: '' };
      default: return { ok: true };
    }
  }
  function wzLabel(s, steps) {
    if (s.kind === 'legal') return X(W.creating ? 'create' : 'save');
    if (W.only != null && s === steps[steps.length - 1]) return X('done_btn');
    return wzOptional(s) && wzEmpty(s) ? X('skip') : X('next');
  }

  function wzBody(s, refresh) {
    const a = W.a;
    if (s.kind === 'single' || s.kind === 'multi') {
      const multi = s.kind === 'multi';
      const wrap = el('div', { class: 'wz-opts' });
      const paint = () => {
        const cur = wzGet(s);
        wrap.querySelectorAll('button').forEach(b => {
          const on = multi ? (cur || []).includes(b.dataset.v) : cur === b.dataset.v;
          b.classList.toggle('on', on); b.setAttribute('aria-pressed', on ? 'true' : 'false');
        });
      };
      s.opts.forEach(o => wrap.append(el('button', { class: 'wz-opt', type: 'button', 'data-v': o.v, onclick: () => {
        if (multi) {
          let cur = [...(wzGet(s) || [])];
          if (cur.includes(o.v)) cur = cur.filter(x => x !== o.v);
          else cur = o.v === 'none' ? ['none'] : [...cur.filter(x => x !== 'none'), o.v];
          wzSet(s, cur); paint(); refresh(); wzPersist();
        } else {
          wzSet(s, o.v); paint(); refresh(); wzPersist();
          const tok = W.tok = (W.tok || 0) + 1;
          setTimeout(() => { if (W && W.tok === tok && W.view === 'steps') wzNext(s); }, 220);   // avanza solo, como en las referencias
        }
      } },
      el('span', { class: 'wz-ico' }, el('i', { class: 'fa-solid ' + o.icon })), el('span', { class: 'wz-lab', text: lab(o) }),
      multi ? el('span', { class: 'wz-mark' }, el('i', { class: 'fa-solid fa-check' })) : null)));
      paint(); return wrap;
    }
    if (s.kind === 'name') {
      const input = el('input', { type: 'text', maxlength: 40, autocomplete: 'given-name', placeholder: T('name_ph'), value: a.display_name || '' });
      input.oninput = () => { a.display_name = input.value; refresh(); wzPersist(); };
      return el('label', { class: 'df-field wz-field' }, input);
    }
    if (s.kind === 'birth') {
      if (W.lockedBirth) return el('div', { class: 'd-notice' }, el('b', { text: ageOf(a.birth_date) + ' ' + T('years') }), el('br'), X('birth_locked'));
      const input = el('input', { type: 'date', value: a.birth_date || '', max: new Date().toISOString().slice(0, 10) });
      input.onchange = input.oninput = () => { a.birth_date = input.value; refresh(); wzPersist(); };
      return el('label', { class: 'df-field wz-field' }, input);
    }
    if (s.kind === 'ages') {
      const lo = el('input', { type: 'number', inputmode: 'numeric', min: 18, max: 99, value: a.min_age, 'aria-label': 'min' });
      const hi = el('input', { type: 'number', inputmode: 'numeric', min: 18, max: 99, value: a.max_age, 'aria-label': 'max' });
      lo.oninput = () => { a.min_age = lo.value; refresh(); wzPersist(); }; hi.oninput = () => { a.max_age = hi.value; refresh(); wzPersist(); };
      return el('div', { class: 'df-field wz-field' }, el('div', { class: 'df-age' }, lo, el('span', { text: T('age_to') }), hi));
    }
    if (s.kind === 'location') {
      const muni = el('input', { type: 'text', maxlength: 60, placeholder: T('municipality_ph'), value: a.municipality || '' });
      muni.oninput = () => { a.municipality = muni.value; wzPersist(); };
      const sel = el('select', { 'aria-label': T('province') }, el('option', { value: '', text: T('province_ph') }));
      D.cfg.provinces.forEach(pv => sel.append(el('option', { value: pv, text: pv })));
      sel.value = a.province || '';
      sel.onchange = () => { a.province = sel.value; refresh(); wzPersist(); };
      return el('div', { class: 'wz-stack' },
        el('label', { class: 'df-field wz-field' }, el('span', { class: 'df-label', text: T('province') }), el('div', { class: 'df-select' }, sel)),
        el('label', { class: 'df-field wz-field' }, el('span', { class: 'df-label', text: T('municipality') }), muni));
    }
    if (s.kind === 'about') {
      const maxBio = D.cfg.max_bio; const counter = el('small', { class: 'df-counter' });
      const bio = el('textarea', { maxlength: maxBio, rows: 4, placeholder: T('bio_ph'), value: a.bio || '' });
      const paintBio = () => { counter.textContent = T('chars_left', { n: Math.max(0, maxBio - bio.value.length) }); };
      bio.oninput = () => { a.bio = bio.value; paintBio(); refresh(); wzPersist(); }; paintBio();
      const box = el('div', { class: 'chips' });
      const ints = el('input', { type: 'text', placeholder: T('interests_ph'), value: a.interests || '' });
      const paintInts = () => box.replaceChildren(...ints.value.split(',').map(x => x.trim()).filter(Boolean).slice(0, 6).map(x => el('span', { class: 'chip', text: x })));
      ints.oninput = () => { a.interests = ints.value; paintInts(); refresh(); wzPersist(); }; paintInts();
      return el('div', { class: 'wz-stack' },
        el('div', { class: 'df-field wz-field' }, el('span', { class: 'df-label', text: T('bio') }), bio, el('div', { class: 'df-meta' }, el('small', { text: T('bio_help') }), counter)),
        el('div', { class: 'df-field wz-field' }, el('span', { class: 'df-label', text: T('interests') }), ints, box));
    }
    if (s.kind === 'contact') {
      const username = tgUser();
      const tgCheck = el('input', { type: 'checkbox', checked: !!(a.share_telegram && username), disabled: !username });
      tgCheck.onchange = () => { a.share_telegram = tgCheck.checked; refresh(); wzPersist(); };
      const abroad = a.province === ABROAD;
      let waField;
      if (abroad) {
        const wa = el('input', { type: 'tel', inputmode: 'tel', placeholder: '+1 305 555 0100', value: a.whatsapp || '' });
        wa.oninput = () => { a.whatsapp = wa.value; refresh(); wzPersist(); };
        waField = el('label', { class: 'df-field wz-field' }, el('span', { class: 'df-label', text: T('whatsapp_abroad') }), wa);
      } else {
        const wa = el('input', { type: 'tel', inputmode: 'numeric', placeholder: '5xxxxxxx', autocomplete: 'tel-national', value: cubaLocal(a.whatsapp) });
        wa.oninput = () => { const local = cubaLocal(wa.value); if (wa.value !== local) wa.value = local; a.whatsapp = local ? '53' + local : ''; refresh(); wzPersist(); };
        waField = el('label', { class: 'df-field wz-field' }, el('span', { class: 'df-label', text: T('whatsapp') }),
          el('div', { class: 'wa-input' }, el('span', { class: 'wa-prefix', text: '🇨🇺 +53' }), wa));
      }
      return el('div', { class: 'wz-stack' },
        el('label', { class: 'd-check wz-card' }, tgCheck, el('span', { text: T('share_tg') + (username ? ' (@' + username + ')' : '') })),
        username ? null : el('small', { class: 'd-muted', text: T('tg_missing') }),
        waField);
    }
    if (s.kind === 'legal') {
      const adult = el('input', { type: 'checkbox', checked: !!a.confirm_adult }); adult.onchange = () => { a.confirm_adult = adult.checked; refresh(); };
      const terms = el('input', { type: 'checkbox', checked: !!a.accept_terms }); terms.onchange = () => { a.accept_terms = terms.checked; refresh(); };
      return el('div', { class: 'wz-stack' },
        el('label', { class: 'd-check wz-card' }, adult, el('span', { text: T('adult') })),
        el('label', { class: 'd-check wz-card' }, terms, el('span', {}, T('terms') + ' ', el('a', { href: '/terms.html', target: '_blank', rel: 'noopener', text: T('terms_link') }))));
    }
    return el('div');
  }

  function wzTitle(s) {
    const map = { name: ['name_t', 'name_s'], birth: ['birth_t', 'birth_s'], ages: ['ages_t', 'ages_s'], location: ['loc_t', 'loc_s'],
      about: ['about_t', 'about_s'], contact: ['contact_t', 'contact_s'], legal: ['legal_t', 'legal_s'] };
    if (map[s.kind]) return { title: X(map[s.kind][0]), sub: X(map[s.kind][1]) };
    return { title: lab(s.title), sub: s.kind === 'multi' ? X('multi_sub') : (wzOptional(s) ? X('opt_sub') : '') };
  }

  function renderWizard() {
    if (W.view === 'summary') return wzSummary();
    if (W.view === 'done') return wzDone();
    const steps = wzSteps();
    W.i = Math.max(0, Math.min(W.i, steps.length - 1));
    const s = steps[W.i];
    const inStage = steps.filter(x => x.stage === s.stage);
    const stagesShown = [...new Set(steps.map(x => x.stage))];
    const msg = el('p', { class: 'wz-msg', role: 'status' });
    const btn = el('button', { class: 'primary', type: 'button', onclick: () => wzNext(s) });
    const refresh = () => { const v = wzValid(s); btn.disabled = !v.ok; msg.textContent = v.msg || ''; msg.classList.toggle('ok', !!v.ok && !!v.msg); btn.textContent = wzLabel(s, steps); };
    const head = wzTitle(s);
    setBody(...[
      el('div', { class: 'wz-top' },
        el('button', { class: 'back-btn', type: 'button', onclick: wzBack }, el('i', { class: 'fa-solid fa-arrow-left' }), el('span', { text: T('back') })),
        el('strong', { text: X('stage_' + s.stage) })),
      el('div', { class: 'wz-progress', 'aria-hidden': 'true' }, stagesShown.map(st => {
        const fill = st < s.stage ? 100 : st === s.stage ? Math.round(((inStage.indexOf(s) + 1) / inStage.length) * 100) : 0;
        const bar = el('b'); bar.style.width = fill + '%';
        return el('i', {}, bar);
      })),
      el('h2', { class: 'wz-title', text: head.title }),
      head.sub ? el('p', { class: 'wz-sub', text: head.sub }) : null,
      wzBody(s, refresh), msg,
      el('div', { class: 'wz-foot' }, btn)].filter(Boolean));
    refresh();
    window.scrollTo(0, 0);
  }
  function wzBack() {
    W.tok = (W.tok || 0) + 1;
    if (W.i > 0) { W.i--; wzPersist(); return renderWizard(); }
    if (W.only != null) { W.view = 'summary'; return renderWizard(); }
    D.tab = D.me?.profile ? 'mine' : 'intro'; render();
  }
  async function wzNext(s) {
    if (!wzValid(s).ok || W.busy) return;
    wzPersist();
    if (s.kind === 'legal') return wzSubmit();
    const steps = wzSteps();
    if (W.i < steps.length - 1) { W.i++; return renderWizard(); }
    W.view = 'summary'; renderWizard();   // fin de la etapa editada
  }
  async function wzSubmit() {
    const a = W.a; W.busy = true;
    const body = {
      display_name: (a.display_name || '').trim(), birth_date: a.birth_date, gender: a.gender, looking_for: a.looking_for,
      province: a.province, municipality: a.municipality || '', bio: a.bio || '',
      interests: (a.interests || '').split(',').map(x => x.trim()).filter(Boolean),
      min_age: Number(a.min_age) || 18, max_age: Number(a.max_age) || 99, whatsapp: a.whatsapp || '',
      share_telegram: !!(a.share_telegram && tgUser()), prefs: a.prefs,
      confirm_adult: W.creating ? !!a.confirm_adult : true, accept_terms: W.creating ? !!a.accept_terms : true,
    };
    try {
      D.me = await jpost('/api/dating/profile', body);
      D.feed = []; toast(T('profile_saved'));
      if (W.creating) { wzClearDraft(); W.view = 'done'; W.busy = false; return renderWizard(); }
      W.busy = false; D.tab = 'mine'; render();
    } catch (e) { W.busy = false; fail(e); }
  }

  const wzStageBrief = (st) => {
    const a = W.a;
    if (st === 0) { const n = ageOf(a.birth_date); return [a.display_name, n != null ? n + ' ' + T('years') : ''].filter(Boolean).join(', '); }
    if (st === 1) return [T(a.looking_for || ''), a.min_age + '–' + a.max_age].filter(Boolean).join(' · ');
    if (st === 4) return [a.province, a.municipality].filter(Boolean).join(' · ');
    const n = STEPS.filter(x => x.stage === st && !wzEmpty(x)).length; return X('n_answers', { n });
  };
  function wzSummary() {
    const save = el('button', { class: 'primary', type: 'button', text: X('save'), onclick: wzSubmit });
    setBody(
      el('h2', { class: 'wz-title', text: X('sum_t') }), el('p', { class: 'wz-sub', text: X('sum_s') }),
      ...[0, 1, 2, 3, 4].map(st => el('div', { class: 'wz-sum' },
        el('div', { class: 'grow' }, el('strong', { text: X('stage_' + st) }), el('small', { text: wzStageBrief(st) })),
        el('button', { class: 'mini-btn', type: 'button', text: X('edit'), onclick: () => { W.only = st; W.i = 0; W.view = 'steps'; renderWizard(); } }))),
      el('div', { class: 'wz-foot' }, save, el('button', { class: 'secondary', type: 'button', text: X('cancel'), onclick: () => { D.tab = 'mine'; render(); } })));
    window.scrollTo(0, 0);
  }
  function wzDone() {
    const a = W.a; const n = ageOf(a.birth_date);
    const picked = [];
    STEPS.filter(s => s.pref && ['intent', 'work', 'weekend'].includes(s.pref)).forEach(s => {
      const v = wzGet(s); (Array.isArray(v) ? v : v ? [v] : []).forEach(x => { const o = s.opts.find(y => y.v === x); if (o) picked.push(lab(o)); });
    });
    setBody(...[
      el('div', { class: 'wz-done' }, el('span', { class: 'wz-ico big' }, el('i', { class: 'fa-solid fa-heart' })),
        el('h2', { class: 'wz-title', text: X('done_t') }), el('p', { class: 'wz-sub', text: X('done_s') })),
      el('div', { class: 'd-card' },
        el('h2', { text: `${a.display_name}${n != null ? ', ' + n : ''}` }),
        el('p', { class: 'd-muted', text: [a.province, a.municipality].filter(Boolean).join(' · ') }),
        el('div', { class: 'chips' }, picked.slice(0, 6).map(x => el('span', { class: 'chip', text: x })))),
      state.premium ? null : el('div', { class: 'd-card soft' }, el('strong', { text: X('prem_t') }), el('p', { class: 'd-muted', text: X('prem_s') }),
        el('button', { class: 'secondary', type: 'button', text: X('see_premium'), onclick: () => goPremium('general') })),
      el('div', { class: 'wz-foot' }, el('button', { class: 'primary', type: 'button', text: X('add_photos'), onclick: () => { D.tab = 'mine'; render(); } }))].filter(Boolean));
    window.scrollTo(0, 0);
  }

  function renderForm() {
    const p = D.me?.profile; const creating = !p;
    const defaults = { display_name: tg?.initDataUnsafe?.user?.first_name || '', birth_date: '', gender: '', looking_for: '', min_age: 18, max_age: 60,
      province: '', municipality: '', bio: '', interests: '', whatsapp: '', share_telegram: false, confirm_adult: false, accept_terms: false, prefs: {} };
    W = { creating, only: null, i: 0, view: 'steps', a: { ...defaults }, lockedBirth: p ? p.birth_date : '', busy: false, tok: 0 };
    if (p) {
      Object.assign(W.a, { display_name: p.display_name, birth_date: p.birth_date, gender: p.gender, looking_for: p.looking_for, min_age: p.min_age, max_age: p.max_age,
        province: p.province, municipality: p.municipality || '', bio: p.bio || '', interests: (p.interests || []).join(', '), whatsapp: p.whatsapp || '',
        share_telegram: !!p.share_telegram, prefs: JSON.parse(JSON.stringify(p.prefs || {})) });
      W.view = 'summary';
    } else {
      try {
        const draft = JSON.parse(localStorage.getItem(WZ_KEY) || 'null');
        if (draft && draft.a) { W.a = { ...defaults, ...draft.a, prefs: { ...(draft.a.prefs || {}) }, confirm_adult: false, accept_terms: false }; W.i = Number(draft.i) || 0; }
      } catch (_) { /* borrador dañado: se ignora */ }
    }
    $('.bottom-nav').classList.add('hidden');       // pantalla completa durante el asistente
    $('#datingTabs').classList.add('hidden');
    $('#datingScreen').classList.add('wz-on');
    renderWizard();
  }

  // ---- mi perfil y fotos -----------------------------------------------
  function renderMine() {
    const p = D.me.profile;
    const badge = (s) => el('span', { class: 'd-badge ' + s, text: T('photo_' + s) });
    const grid = el('div', { class: 'photo-grid' }, D.me.photos.map(ph => el('div', { class: 'photo-tile' },
      el('img', { src: safePhoto(ph.url), alt: '' }), badge(ph.status),
      ph.status === 'rejected' && ph.reject_reason ? el('small', { text: ph.reject_reason }) : null,
      el('button', { class: 'photo-del', type: 'button', 'aria-label': T('photo_delete'), text: '×', onclick: async () => {
        try {
          const r = await fetch('/api/dating/photos/' + Number(ph.id), { method: 'DELETE' });
          if (!r.ok) { const d = await r.json().catch(() => ({})); throw new Error(typeof d.detail === 'string' ? d.detail : T('error')); }
          D.me = await jpost('/api/dating/me'); renderMine();
        } catch (e) { fail(e); } } }))));
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
    setBody(
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
        if (!await datingConfirm(T('delete_confirm'))) return;
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
    let bundle = null;
    if (D.warm && D.warm.feed && Date.now() - D.warm.at < 60000) { bundle = await D.warm.feed; }   // feed precargado (se usa una sola vez)
    if (D.warm) D.warm.feed = null;
    if (!bundle) bundle = await fetchFeedBundle();
    const d = bundle.d;
    D.feed = d.profiles || []; D.photoIdx = 0; D.premium = !!d.premium; D.likesLeft = d.likes_left;
    D.likesInfo = bundle.likes; D.shareEarn = d.share_earn || null;
  }
  async function renderDiscover() {
    if (!D.feed.length) {
      setBody(el('p', { class: 'd-muted', text: T('loading') }));
      try { await loadFeed(); } catch (e) {
        if (e.status === 409) { D.tab = 'mine'; toast(e.message); return render(); }
        return setBody(el('p', { class: 'd-muted', text: e.message }));
      }
    }
    const p = D.feed[0];
    if (!p) {
      return setBody(likesBanner(),
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
    // Share-to-earn banner: solo para free users que aún no ganaron el bonus hoy
    const shareEarnBanner = (!D.premium && D.shareEarn && !D.shareEarn.already_earned)
      ? el('div', { class: 'd-share-earn-banner' },
          el('span', { text: T('share_earn_cta') }),
          el('button', { class: 'd-share-earn-btn', type: 'button', text: T('share_earn_btn'),
            onclick: async (ev) => {
              const btn = ev.currentTarget;
              btn.disabled = true; btn.textContent = T('share_earn_confirm');
              try {
                const r = await jpost('/api/dating/share-earn', {});
                if (r.granted || r.already_granted) {
                  D.shareEarn = { already_earned: true, bonus_today: r.bonus };
                  D.likesLeft = r.likes_left;
                  renderDiscover();
                }
              } catch (_) { btn.disabled = false; btn.textContent = T('share_earn_btn'); }
            }
          }))
      : ((!D.premium && D.shareEarn && D.shareEarn.already_earned)
          ? el('div', { class: 'd-share-earn-banner done' }, el('span', { text: T('share_earn_done') }))
          : null);
    setBody(likesBanner(), shareEarnBanner,
      el('div', { class: 'd-card profile' }, shot,
        el('div', { class: 'd-info' },
          el('h2', { text: `${p.display_name}, ${p.age}` }),
          el('p', { class: 'd-muted', text: [p.province, p.municipality].filter(Boolean).join(' · ') + (p.same_province ? ' · ' + T('same_province') : '') }),
          p.bio ? el('p', { text: p.bio }) : null,
          el('div', { class: 'chips' }, p.in_common ? el('span', { class: 'chip match', text: X(p.in_common === 1 ? 'in_common_one' : 'in_common', { n: p.in_common }) }) : null, (p.interests || []).map(i => el('span', { class: 'chip', text: i }))),
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
    setBody(
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
    const container = el('div', { class: 'd-matches-container' });
    setBody(container);
    if (window.LiggaChat && typeof window.LiggaChat.renderList === 'function') {
      window.LiggaChat.renderList(container);
    } else {
      setBody(el('p', { class: 'd-muted', text: T('matches_empty') }));
    }
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
      el('button', { class: 'primary', type: 'button', text: '💬 Chatear ahora',
        onclick: () => {
          m.close();
          if (match.match_id && window.LiggaChat) window.LiggaChat.open(match.match_id);
          else { D.tab = 'matches'; render(); }
        } }),
      contactButtons(match.contacts),
      el('button', { class: 'secondary', type: 'button', text: T('keep'), onclick: () => m.close() })));
  }
  function manageSheet(match) {
    const m = sheet(el('h3', { text: match.display_name }),
      el('button', { class: 'secondary', type: 'button', text: T('unmatch'), onclick: async () => {
        if (!await datingConfirm(T('unmatch_confirm'))) return;
        try { await jpost('/api/dating/unmatch', { match_id: match.match_id }); toast(T('unmatched')); m.close(); renderMatches(); } catch (e) { fail(e); } } }),
      el('button', { class: 'secondary', type: 'button', text: T('block'), onclick: async () => {
        if (!await datingConfirm(T('block_confirm'))) return;
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
  window.warmDating = warmDating;
})();
