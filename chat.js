/* LiggaCuba Citas — Chat interno (chat.js)
 *
 * Módulo autocontenido. No tiene dependencias externas salvo las que ya
 * expone app.js: state, $, toast, tg, showPremium, screenStack.
 *
 * API pública:
 *   window.LiggaChat.open(matchId)          → abre el chat de un match
 *   window.LiggaChat.renderList(container)  → pinta la lista en el tab Matches
 *   window.LiggaChat.handleDeepLink(param)  → procesa startapp=chat_<matchId>
 *   window.LiggaChat.destroy()              → limpia timers al salir
 */
(function () {
  'use strict';

  // ── constantes ────────────────────────────────────────────────────────────
  const POLL_MS          = 4500;   // polling mientras el chat está abierto
  const MSG_LIMIT_FREE   = 8;      // mensajes gratuitos por match
  const LOAD_LIMIT       = 40;     // mensajes por carga

  // ── textos ────────────────────────────────────────────────────────────────
  const TX = {
    es: {
      loading: 'Cargando…', error: 'Ocurrió un error', send: 'Enviar',
      placeholder: 'Escribe un mensaje…', empty_chat: 'Aún no hay mensajes. ¡Di hola!',
      empty_list: 'Cuando hagas match con alguien aparecerá aquí para chatear.',
      match_event: '¡Es un match!', read: 'Visto',
      limit_title: 'Límite alcanzado',
      limit_text: 'Con el plan gratuito puedes enviar {n} mensajes por match. Mejora a Premium para escribir sin límite.',
      go_premium: 'Ver Premium', cancel: 'Cancelar',
      view_profile: 'Ver perfil', open_tg: 'Telegram', open_wa: 'WhatsApp',
      mute: 'Silenciar', report: 'Reportar', block: 'Bloquear', unmatch: 'Deshacer match',
      unmatch_confirm: '¿Deshacer este match? Dejarás de chatear con esta persona.',
      block_confirm: '¿Bloquear a esta persona? No volverán a verse.',
      unmatched: 'Match eliminado', blocked: 'Usuario bloqueado',
      report_reason: 'Motivo del reporte', report_send: 'Enviar reporte', report_sent: 'Reporte enviado',
      r_fake: 'Perfil falso', r_inappropriate_photo: 'Foto inapropiada',
      r_harassment: 'Acoso o falta de respeto', r_minor: 'Parece menor de edad',
      r_scam: 'Estafa o spam', r_other: 'Otro motivo',
      back: 'Atrás', unread: '{n} sin leer', chat_closed: 'Este chat ya no está disponible.',
      msg_limit_banner: 'Llevas {n} de {max} mensajes gratuitos en este match.',
    },
    en: {
      loading: 'Loading…', error: 'Something went wrong', send: 'Send',
      placeholder: 'Write a message…', empty_chat: 'No messages yet. Say hi!',
      empty_list: 'When you match with someone they will appear here to chat.',
      match_event: "It's a match!", read: 'Seen',
      limit_title: 'Limit reached',
      limit_text: 'Free users can send {n} messages per match. Upgrade to Premium for unlimited messaging.',
      go_premium: 'See Premium', cancel: 'Cancel',
      view_profile: 'View profile', open_tg: 'Telegram', open_wa: 'WhatsApp',
      mute: 'Mute', report: 'Report', block: 'Block', unmatch: 'Remove match',
      unmatch_confirm: 'Remove this match? You will stop chatting with this person.',
      block_confirm: 'Block this person? You will not see each other again.',
      unmatched: 'Match removed', blocked: 'User blocked',
      report_reason: 'Report reason', report_send: 'Send report', report_sent: 'Report sent',
      r_fake: 'Fake profile', r_inappropriate_photo: 'Inappropriate photo',
      r_harassment: 'Harassment or disrespect', r_minor: 'Looks underage',
      r_scam: 'Scam or spam', r_other: 'Other',
      back: 'Back', unread: '{n} unread', chat_closed: 'This chat is no longer available.',
      msg_limit_banner: 'You have sent {n} of {max} free messages in this match.',
    },
  };
  const C = (k, vars) => {
    const lang = (typeof state !== 'undefined' && state.language === 'en') ? 'en' : 'es';
    let s = TX[lang][k] ?? TX.es[k] ?? k;
    if (vars) for (const [a, b] of Object.entries(vars)) s = s.replaceAll('{' + a + '}', b);
    return s;
  };

  // ── estado del módulo ─────────────────────────────────────────────────────
  const S = {
    matchId:    null,   // match abierto
    messages:   [],     // array de mensajes cargados
    lastId:     0,      // id del último mensaje recibido (para polling incremental)
    pollTimer:  null,
    sending:    false,
    atBottom:   true,   // si el scroll está abajo → auto-scroll
    matchInfo:  null,   // { display_name, photos, contacts, public_id, match_id, … }
    listCache:  null,   // caché de la lista de matches con mensajes
    listStamp:  0,
  };

  // ── utilidades DOM ────────────────────────────────────────────────────────
  const el = (tag, props, ...kids) => {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(props || {})) {
      if (v == null || v === false) continue;
      if (k === 'class') n.className = v;
      else if (k === 'text') n.textContent = v;
      else if (['value', 'checked', 'disabled', 'selected', 'placeholder'].includes(k)) n[k] = v;
      else if (k.startsWith('on')) n[k] = v;
      else n.setAttribute(k, v === true ? '' : v);
    }
    for (const c of kids.flat()) {
      if (c == null || c === false) continue;
      n.append(c.nodeType ? c : document.createTextNode(String(c)));
    }
    return n;
  };

  async function jpost(url, body) {
    const r = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {}),
    });
    const d = await r.json().catch(() => ({ detail: C('error') }));
    if (!r.ok) {
      const e = new Error(typeof d.detail === 'string' ? d.detail : C('error'));
      e.status = r.status;
      throw e;
    }
    return d;
  }

  async function jget(url) {
    const r = await fetch(url);
    const d = await r.json().catch(() => ({ detail: C('error') }));
    if (!r.ok) {
      const e = new Error(typeof d.detail === 'string' ? d.detail : C('error'));
      e.status = r.status;
      throw e;
    }
    return d;
  }

  const safePhoto = (u) =>
    typeof u === 'string' && u.startsWith('/api/dating/photo/') ? u : '';
  const safeContact = (u) =>
    typeof u === 'string' && (u.startsWith('https://t.me/') || u.startsWith('https://wa.me/')) ? u : '';

  function openExternal(url) {
    if (!safeContact(url)) return;
    try {
      if (url.startsWith('https://t.me/') && tg?.openTelegramLink) return tg.openTelegramLink(url);
      if (tg?.openLink) return tg.openLink(url);
    } catch (_) {}
    window.open(url, '_blank', 'noopener');
  }

  function isPremium() {
    return typeof state !== 'undefined' && !!state.premium;
  }

  // ── tiempos relativos ─────────────────────────────────────────────────────
  function relTime(iso) {
    if (!iso) return '';
    const t = new Date(iso).getTime();
    if (!t) return '';
    const sec = Math.max(0, Math.floor((Date.now() - t) / 1000));
    if (sec < 45) return 'ahora';
    if (sec < 3600) return `hace ${Math.floor(sec / 60)} min`;
    if (sec < 86400) return `hace ${Math.floor(sec / 3600)} h`;
    if (sec < 172800) return 'ayer';
    const d = new Date(t);
    return d.toLocaleDateString('es-CU', { day: 'numeric', month: 'short' });
  }

  function dateLabel(iso) {
    const d = new Date(iso + (iso.endsWith('Z') ? '' : 'Z'));
    const now = new Date();
    const isToday = d.toDateString() === now.toDateString();
    const yesterday = new Date(now); yesterday.setDate(now.getDate() - 1);
    const isYesterday = d.toDateString() === yesterday.toDateString();
    if (isToday) return 'Hoy';
    if (isYesterday) return 'Ayer';
    return d.toLocaleDateString('es-CU', { day: 'numeric', month: 'long' });
  }

  function msgTime(iso) {
    const d = new Date(iso + (iso.endsWith('Z') ? '' : 'Z'));
    return d.toLocaleTimeString('es-CU', { hour: '2-digit', minute: '2-digit', timeZone: 'America/Havana' });
  }

  // ── modal / sheet (reutiliza estilos de dating.js) ────────────────────────
  function sheet(...kids) {
    const close = () => m.remove();
    const m = el('div', { class: 'modal dating-modal' },
      el('div', { class: 'crop-backdrop', onclick: close }),
      el('div', { class: 'result-sheet' }, ...kids));
    m.close = close;
    document.getElementById('datingScreen')?.append(m);
    return m;
  }

  function datingConfirm(msg) {
    return new Promise(resolve => {
      if (tg?.showConfirm) {
        try { return tg.showConfirm(msg, ok => resolve(!!ok)); } catch (_) {}
      }
      resolve(window.confirm(msg));
    });
  }

  // ── API de red ────────────────────────────────────────────────────────────
  async function fetchMessages(matchId, afterId = 0) {
    return jget(`/api/dating/matches/${matchId}/messages?after_id=${afterId}&limit=${LOAD_LIMIT}`);
  }

  async function sendMessage(matchId, body) {
    return jpost(`/api/dating/matches/${matchId}/messages`, { body });
  }

  async function markRead(matchId) {
    return jpost(`/api/dating/matches/${matchId}/read`, {}).catch(() => null);
  }

  async function fetchMatchList() {
    return jpost('/api/dating/matches', {});
  }

  // ── renderizado de la lista ───────────────────────────────────────────────
  /**
   * Renderiza la lista de conversaciones dentro del contenedor pasado.
   * Se llama desde dating.js al pintar el tab Matches.
   */
  async function renderList(container) {
    if (!container) return;
    container.replaceChildren(el('p', { class: 'd-muted', text: C('loading') }));
    try {
      const d = await fetchMatchList();
      S.listCache = d.matches || [];
      S.listStamp = Date.now();
      _paintList(container, S.listCache);
    } catch (e) {
      container.replaceChildren(el('p', { class: 'd-muted', text: e.message }));
    }
  }

  function _paintList(container, matches) {
    if (!matches.length) {
      container.replaceChildren(
        el('div', { class: 'd-card center' },
          el('p', { class: 'd-muted', text: C('empty_list') })));
      return;
    }
    // ordenar por last_message.created_at más reciente
    const sorted = [...matches].sort((a, b) => {
      const ta = a.last_message?.created_at || a.matched_at || '';
      const tb = b.last_message?.created_at || b.matched_at || '';
      return tb.localeCompare(ta);
    });
    container.replaceChildren(...sorted.map(m => _matchRow(m)));
  }

  function _matchRow(m) {
    const photo = safePhoto((m.photos || [])[0]);
    const lm = m.last_message;
    const unread = m.unread_count || 0;
    const preview = lm
      ? (lm.is_system ? C('match_event') : _truncate(lm.body, 36))
      : C('match_event');
    const time = lm ? relTime(lm.created_at) : relTime(m.matched_at);

    const row = el('div', { class: 'ch-row', onclick: () => open(m.match_id) },
      el('div', { class: 'ch-avatar' + (photo ? '' : ' ch-avatar-empty') },
        photo ? el('img', { src: photo, alt: '' }) : el('span', { text: (m.display_name || '?')[0].toUpperCase() })),
      el('div', { class: 'ch-row-body' },
        el('div', { class: 'ch-row-top' },
          el('strong', { text: m.display_name || '…' }),
          el('span', { class: 'ch-time', text: time })),
        el('div', { class: 'ch-row-bottom' },
          el('p', { class: 'ch-preview' + (lm?.is_system ? ' ch-preview-system' : ''), text: preview }),
          unread ? el('span', { class: 'ch-unread', text: String(unread > 99 ? '99+' : unread) }) : null)));
    return row;
  }

  function _truncate(s, max) {
    if (!s) return '';
    return s.length > max ? s.slice(0, max - 1) + '…' : s;
  }

  // ── pantalla de chat ──────────────────────────────────────────────────────
  /**
   * Abre la pantalla de chat de un match. Se empuja encima del tab Matches.
   */
  async function open(matchId) {
    if (!matchId) return;
    S.matchId = matchId;
    S.messages = [];
    S.lastId   = 0;

    // Buscar info del match en el caché de la lista o pedirla
    const cached = (S.listCache || []).find(m => m.match_id === matchId);
    S.matchInfo = cached || null;

    _showChatScreen();
    _paintChatLoading();

    try {
      // Si no tenemos info del match, cargamos la lista
      if (!S.matchInfo) {
        const d = await fetchMatchList();
        S.listCache = d.matches || [];
        S.matchInfo = S.listCache.find(m => m.match_id === matchId) || null;
      }
      if (!S.matchInfo) {
        _paintError(C('chat_closed')); return;
      }
      _paintChatHeader();
      const data = await fetchMessages(matchId, 0);
      S.messages  = data.messages || [];
      S.lastId    = data.last_id  || 0;
      _paintMessages();
      _scrollToBottom(true);
      markRead(matchId);
      _startPolling();
    } catch (e) {
      _paintError(e.message);
    }
  }

  function _showChatScreen() {
    // Ocultar el body de citas y mostrar la pantalla de chat
    const datingBody = document.getElementById('datingBody');
    const datingTabs = document.getElementById('datingTabs');
    const chatScreen = _ensureChatScreen();
    if (datingBody) datingBody.style.display = 'none';
    if (datingTabs) datingTabs.classList.add('hidden');
    chatScreen.classList.remove('hidden');
    // Ocultar nav
    document.querySelector('.bottom-nav')?.classList.add('hidden');
  }

  function _hideChatScreen() {
    const chatScreen = document.getElementById('ligga-chat-screen');
    if (chatScreen) chatScreen.classList.add('hidden');
    const datingBody = document.getElementById('datingBody');
    const datingTabs = document.getElementById('datingTabs');
    if (datingBody) datingBody.style.display = '';
    if (datingTabs) datingTabs.classList.remove('hidden');
    document.querySelector('.bottom-nav')?.classList.remove('hidden');
    _stopPolling();
    S.matchId = null;
  }

  function _ensureChatScreen() {
    let s = document.getElementById('ligga-chat-screen');
    if (!s) {
      s = el('div', { id: 'ligga-chat-screen', class: 'ligga-chat-screen hidden' });
      document.getElementById('datingScreen')?.append(s);
    }
    return s;
  }

  function _screen() { return document.getElementById('ligga-chat-screen'); }

  function _paintChatLoading() {
    const s = _screen(); if (!s) return;
    s.replaceChildren(
      _buildHeader(null),
      el('div', { class: 'ch-msgs-wrap' },
        el('p', { class: 'd-muted ch-loading', text: C('loading') })),
      _buildInput(true));
  }

  function _paintError(msg) {
    const s = _screen(); if (!s) return;
    s.replaceChildren(
      _buildHeader(null),
      el('div', { class: 'ch-msgs-wrap' },
        el('p', { class: 'd-muted ch-loading', text: msg })));
  }

  // ── header ────────────────────────────────────────────────────────────────
  function _buildHeader(info) {
    const photo  = info ? safePhoto((info.photos || [])[0]) : '';
    const name   = info?.display_name || '…';
    const avatar = photo
      ? el('img', { src: photo, alt: '', class: 'ch-hdr-photo' })
      : el('div', { class: 'ch-hdr-photo ch-hdr-photo-empty', text: name[0].toUpperCase() });

    const menuBtn = el('button', { class: 'ch-menu-btn icon-btn', type: 'button',
      'aria-label': 'Menú',
      onclick: () => info && _menuSheet(info) },
      el('i', { class: 'fa-solid fa-ellipsis-vertical' }));

    return el('div', { class: 'ch-header' },
      el('button', { class: 'back-btn ch-back', type: 'button', onclick: _hideChatScreen },
        el('i', { class: 'fa-solid fa-arrow-left' })),
      avatar,
      el('div', { class: 'ch-hdr-info' },
        el('strong', { text: name }),
        el('span', { class: 'ch-hdr-sub', text: 'Citas' })),
      menuBtn);
  }

  function _paintChatHeader() {
    const s = _screen(); if (!s || !S.matchInfo) return;
    const hdr = s.querySelector('.ch-header');
    if (hdr) hdr.replaceWith(_buildHeader(S.matchInfo));
  }

  // ── mensajes ──────────────────────────────────────────────────────────────
  function _myId() {
    return typeof state !== 'undefined' ? String(state.userId || '') : '';
  }

  function _paintMessages(opts = {}) {
    const s = _screen(); if (!s) return;
    const wrap = s.querySelector('.ch-msgs-wrap');
    if (!wrap) return _paintFullChat();

    const prevScrollH = wrap.scrollHeight;
    const prevScrollT = wrap.scrollTop;

    const groups = _groupByDate(S.messages);
    const nodes  = [];
    for (const [dateStr, msgs] of groups) {
      nodes.push(el('div', { class: 'ch-date-sep' }, el('span', { text: dateStr })));
      for (const msg of msgs) nodes.push(_msgBubble(msg));
    }
    if (!nodes.length) {
      nodes.push(el('p', { class: 'd-muted ch-empty', text: C('empty_chat') }));
    }

    // banner de límite free
    const myCount = S.messages.filter(m => !m.is_system && m.sender_id === _myId()).length;
    if (!isPremium() && myCount >= MSG_LIMIT_FREE - 2 && myCount < MSG_LIMIT_FREE) {
      nodes.push(_limitBanner(myCount));
    }

    wrap.replaceChildren(...nodes);

    if (S.atBottom || opts.force) {
      wrap.scrollTop = wrap.scrollHeight;
    } else {
      // mantener posición de scroll si el usuario está arriba
      wrap.scrollTop = prevScrollT + (wrap.scrollHeight - prevScrollH);
    }
  }

  function _paintFullChat() {
    const s = _screen(); if (!s) return;
    const myCount = S.messages.filter(m => !m.is_system && m.sender_id === _myId()).length;

    const msgsWrap = el('div', { class: 'ch-msgs-wrap' });
    msgsWrap.onscroll = () => {
      const { scrollTop, scrollHeight, clientHeight } = msgsWrap;
      S.atBottom = scrollHeight - scrollTop - clientHeight < 60;
    };

    s.replaceChildren(
      _buildHeader(S.matchInfo),
      msgsWrap,
      (!isPremium() && myCount >= MSG_LIMIT_FREE) ? _limitWall() : _buildInput(false));

    _paintMessages({ force: true });
  }

  function _groupByDate(msgs) {
    const map = new Map();
    for (const m of msgs) {
      const label = dateLabel(m.created_at);
      if (!map.has(label)) map.set(label, []);
      map.get(label).push(m);
    }
    return map;
  }

  function _msgBubble(msg) {
    if (msg.is_system) {
      return el('div', { class: 'ch-sys' }, el('span', { text: msg.body || C('match_event') }));
    }
    const mine = msg.sender_id === _myId();
    const wrap = el('div', { class: 'ch-bubble-wrap' + (mine ? ' mine' : '') },
      el('div', { class: 'ch-bubble' + (mine ? ' ch-bubble-mine' : ' ch-bubble-theirs') + (msg._optimistic ? ' ch-bubble-sending' : '') + (msg._failed ? ' ch-bubble-failed' : '') },
        el('p', { class: 'ch-body', text: msg.body }),
        el('span', { class: 'ch-ts' }, msgTime(msg.created_at),
          mine && msg.read_at ? el('i', { class: 'ch-read fa-solid fa-check-double', title: C('read') }) : null)));
    return wrap;
  }

  function _limitBanner(count) {
    return el('div', { class: 'ch-limit-banner' },
      el('span', { text: C('msg_limit_banner', { n: count, max: MSG_LIMIT_FREE }) }));
  }

  function _limitWall() {
    return el('div', { class: 'ch-limit-wall' },
      el('div', { class: 'ch-limit-inner' },
        el('i', { class: 'fa-solid fa-lock ch-limit-icon' }),
        el('strong', { text: C('limit_title') }),
        el('p', { text: C('limit_text', { n: MSG_LIMIT_FREE }) }),
        el('button', { class: 'primary', type: 'button', text: C('go_premium'),
          onclick: () => { _stopPolling(); window.showPremium?.('limit'); } })));
  }

  // ── input ─────────────────────────────────────────────────────────────────
  function _buildInput(disabled) {
    const textarea = el('textarea', {
      class: 'ch-input', placeholder: C('placeholder'), rows: 1,
      disabled: !!disabled, maxlength: 1000,
      // Mejor soporte de teclado en Telegram Mini App (iOS/Android)
      inputmode: 'text', enterkeyhint: 'send', autocomplete: 'off',
      autocorrect: 'on', autocapitalize: 'sentences',
    });

    // auto-resize
    textarea.oninput = () => {
      textarea.style.height = 'auto';
      textarea.style.height = Math.min(textarea.scrollHeight, 120) + 'px';
    };

    textarea.onkeydown = (e) => {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); _doSend(textarea, sendBtn); }
    };

    // Forzar apertura del teclado en dispositivos móviles / Telegram WebApp
    const forceFocus = (e) => {
      if (disabled) return;
      // Evitar que el evento se trague en contenedores fixed
      e.stopPropagation();
      setTimeout(() => {
        try { textarea.focus({ preventScroll: false }); } catch (_) { textarea.focus(); }
      }, 10);
    };
    textarea.addEventListener('touchstart', forceFocus, { passive: true });
    textarea.addEventListener('pointerdown', forceFocus);

    const sendBtn = el('button', { class: 'ch-send-btn', type: 'button',
      'aria-label': C('send'), disabled: !!disabled,
      onclick: () => _doSend(textarea, sendBtn) },
      el('i', { class: 'fa-solid fa-paper-plane' }));

    return el('div', { class: 'ch-input-bar' }, textarea, sendBtn);
  }

  async function _doSend(textarea, sendBtn) {
    const body = textarea.value.trim();
    if (!body || S.sending || !S.matchId) return;

    // comprobar límite free
    if (!isPremium()) {
      const myCount = S.messages.filter(m => !m.is_system && m.sender_id === _myId()).length;
      if (myCount >= MSG_LIMIT_FREE) {
        _showLimitModal(); return;
      }
    }

    S.sending = true;
    sendBtn.disabled = true;
    textarea.disabled = true;
    textarea.value = '';
    textarea.style.height = 'auto';

    // envío optimista
    const tempId = Date.now();
    const optimistic = {
      id: tempId, _optimistic: true, sender_id: _myId(),
      body, created_at: new Date().toISOString(), read_at: null, is_system: false,
    };
    S.messages.push(optimistic);
    S.atBottom = true;
    _paintMessages({ force: true });

    try {
      const data = await sendMessage(S.matchId, body);
      const real = data.message || data;
      const idx = S.messages.findIndex(m => m.id === tempId);
      if (idx !== -1) S.messages[idx] = { ...real, _optimistic: false, _failed: false };
      S.lastId = Math.max(S.lastId, real.id || 0);
      // Actualizar caché de lista para el preview al volver atrás
      if (Array.isArray(S.listCache)) {
        const row = S.listCache.find(m => m.match_id === S.matchId);
        if (row) {
          row.last_message = {
            id: real.id, body: real.body, created_at: real.created_at,
            sender_id: real.sender_id, is_system: false,
          };
          row.unread_count = 0;
        }
      }
      _paintMessages({ force: true });
    } catch (e) {
      const idx = S.messages.findIndex(m => m.id === tempId);
      if (idx !== -1) {
        S.messages[idx]._optimistic = false;
        S.messages[idx]._failed = true;
      }
      _paintMessages({ force: true });
      toast(e?.message || C('error'));
    } finally {
      S.sending = false;
      sendBtn.disabled = false;
      textarea.disabled = false;
      textarea.focus();
    }
  }

  function _showLimitModal() {
    const m = sheet(
      el('div', { class: 'ch-limit-modal' },
        el('i', { class: 'fa-solid fa-lock ch-limit-icon' }),
        el('strong', { text: C('limit_title') }),
        el('p', { text: C('limit_text', { n: MSG_LIMIT_FREE }) })),
      el('button', { class: 'primary', type: 'button', text: C('go_premium'),
        onclick: () => { m.close(); _stopPolling(); window.showPremium?.('limit'); } }),
      el('button', { class: 'secondary', type: 'button', text: C('cancel'),
        onclick: () => m.close() }));
  }

  // ── polling ───────────────────────────────────────────────────────────────
  function _startPolling() {
    _stopPolling();
    S.pollTimer = setInterval(_poll, POLL_MS);
  }

  function _stopPolling() {
    if (S.pollTimer) { clearInterval(S.pollTimer); S.pollTimer = null; }
  }

  async function _poll() {
    if (!S.matchId) return;
    try {
      const data = await fetchMessages(S.matchId, S.lastId);
      const newMsgs = data.messages || [];
      if (!newMsgs.length) return;
      S.messages.push(...newMsgs);
      S.lastId = data.last_id || S.lastId;
      _paintMessages();
      markRead(S.matchId);
      // actualizar lista en segundo plano (badge de no leídos)
      _refreshListBadge();
    } catch (_) { /* red inestable: se ignora */ }
  }

  function _scrollToBottom(force = false) {
    const s = _screen();
    const wrap = s?.querySelector('.ch-msgs-wrap');
    if (wrap && (force || S.atBottom)) wrap.scrollTop = wrap.scrollHeight;
  }

  // ── menú del chat ─────────────────────────────────────────────────────────
  function _menuSheet(info) {
    const contacts = (info.contacts || []).filter(c => safeContact(c.url));
    const m = sheet(
      el('h3', { text: info.display_name }),
      el('button', { class: 'secondary', type: 'button', text: C('view_profile'),
        onclick: () => { m.close(); toast('Perfil disponible desde Matches'); } }),
      ...contacts.map(c =>
        el('button', { class: 'secondary contact-btn ' + (c.type === 'whatsapp' ? 'wa' : 'tg'), type: 'button',
          text: C(c.type === 'whatsapp' ? 'open_wa' : 'open_tg'),
          onclick: () => { m.close(); openExternal(c.url); } })),
      el('button', { class: 'secondary', type: 'button', text: C('report'),
        onclick: () => { m.close(); _reportSheet(info.public_id); } }),
      el('button', { class: 'secondary', type: 'button', text: C('unmatch'),
        onclick: async () => {
          if (!await datingConfirm(C('unmatch_confirm'))) return;
          try {
            await jpost('/api/dating/unmatch', { match_id: info.match_id });
            toast(C('unmatched')); m.close(); _hideChatScreen();
          } catch (e) { toast(e?.message || C('error')); }
        } }),
      el('button', { class: 'secondary danger-btn', type: 'button', text: C('block'),
        onclick: async () => {
          if (!await datingConfirm(C('block_confirm'))) return;
          try {
            await jpost('/api/dating/block', { target: info.public_id });
            toast(C('blocked')); m.close(); _hideChatScreen();
          } catch (e) { toast(e?.message || C('error')); }
        } }),
      el('button', { class: 'cancel-btn', type: 'button', text: C('cancel'),
        onclick: () => m.close() }));
  }

  function _openProfile(publicId) {
    // La función de ver perfil de otra persona no existe aún en dating.js,
    // pero la dejamos preparada para cuando se añada.
    // Por ahora simplemente va de vuelta.
  }

  function _reportSheet(publicId) {
    const reasons = ['fake', 'inappropriate_photo', 'harassment', 'minor', 'scam', 'other'];
    const sel = el('select', { class: 'd-field' },
      ...reasons.map(r => el('option', { value: r, text: C('r_' + r) })));
    const details = el('textarea', { class: 'd-field', maxlength: 500, rows: 3, placeholder: '…' });
    const m = sheet(
      el('h3', { text: C('report_reason') }), sel, details,
      el('button', { class: 'primary', type: 'button', text: C('report_send'),
        onclick: async () => {
          try {
            await jpost('/api/dating/report', { target: publicId, reason: sel.value, details: details.value });
            toast(C('report_sent')); m.close();
          } catch (e) { toast(e?.message || C('error')); }
        } }),
      el('button', { class: 'cancel-btn', type: 'button', text: C('cancel'), onclick: () => m.close() }));
  }

  // ── actualizar badge de la lista ──────────────────────────────────────────
  async function _refreshListBadge() {
    // Llama al endpoint de matches en segundo plano para refrescar contadores
    // Solo si han pasado > 10s desde la última vez
    if (Date.now() - S.listStamp < 10000) return;
    try {
      const d = await fetchMatchList();
      S.listCache = d.matches || [];
      S.listStamp = Date.now();
    } catch (_) {}
  }

  // ── deep link ─────────────────────────────────────────────────────────────
  /**
   * Procesa tg.initDataUnsafe.start_param si empieza por "chat_"
   * Debe llamarse tras auth() y warmDating().
   */
  function handleDeepLink(param) {
    if (!param || !String(param).startsWith('chat_')) return;
    const matchId = parseInt(String(param).replace('chat_', ''), 10);
    if (!matchId) return;
    let attempts = 0;
    const maxAttempts = 20; // ~6s con internet lento
    const tick = () => {
      attempts += 1;
      const hidden = document.getElementById('datingScreen')?.classList.contains('hidden');
      if (hidden) {
        window.openDating?.();
        if (attempts < maxAttempts) setTimeout(tick, 300);
        return;
      }
      // Citas visible: abrir chat
      open(matchId);
    };
    tick();
  }

  // ── destroy ───────────────────────────────────────────────────────────────
  function destroy() {
    _stopPolling();
    S.matchId = null;
    S.messages = [];
    S.lastId = 0;
    S.sending = false;
    document.getElementById('ligga-chat-screen')?.remove();
  }

  /** Llamar al salir de la sección Citas (home/profile/more). */
  function leaveDating() {
    _stopPolling();
    S.matchId = null;
    const chatScreen = document.getElementById('ligga-chat-screen');
    if (chatScreen) {
      chatScreen.classList.add('hidden');
      chatScreen.replaceChildren();
    }
    const datingBody = document.getElementById('datingBody');
    const datingTabs = document.getElementById('datingTabs');
    if (datingBody) datingBody.style.display = '';
    if (datingTabs) datingTabs.classList.remove('hidden');
  }

  // ── inyección de estilos ──────────────────────────────────────────────────
  function _injectStyles() {
    if (document.getElementById('ligga-chat-css')) return;
    const style = document.createElement('style');
    style.id = 'ligga-chat-css';
    // Colores y tokens reutilizados de style.css para coherencia visual
    style.textContent = `
/* ── LiggaCuba Chat ── */
.ligga-chat-screen {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  width: 100%;
  height: 100%;
  height: 100dvh;
  height: var(--tg-viewport-stable-height, 100dvh);
  display: flex;
  flex-direction: column;
  background: var(--bg, #f6f4ff);
  z-index: 50;
  overflow: hidden;
  max-width: 520px;
  margin: 0 auto;
}

/* header */
.ch-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: calc(10px + env(safe-area-inset-top, 0px)) 14px 10px;
  background: var(--surface, #fff);
  border-bottom: 1px solid var(--line, #e9e5f5);
  flex-shrink: 0;
  box-shadow: 0 2px 10px rgba(57,39,130,.06);
}
.ch-back {
  margin: 0;
  padding: 8px 10px 8px 0;
  color: var(--purple, #4d35ff);
  font-weight: 800;
  flex-shrink: 0;
}
.ch-hdr-photo {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  object-fit: cover;
  flex-shrink: 0;
  background: #e4defd;
}
.ch-hdr-photo-empty {
  display: grid;
  place-items: center;
  background: linear-gradient(135deg, var(--purple, #4d35ff), #816fff);
  color: #fff;
  font-weight: 800;
  font-size: 16px;
}
.ch-hdr-info {
  flex: 1;
  min-width: 0;
  overflow: hidden;
}
.ch-hdr-info strong {
  display: block;
  font-size: 15px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.ch-hdr-sub {
  display: block;
  font-size: 11px;
  color: var(--muted, #777282);
}
.ch-menu-btn {
  flex-shrink: 0;
  color: var(--muted, #777282);
}

/* área de mensajes */
.ch-msgs-wrap {
  flex: 1;
  overflow-y: auto;
  padding: 14px 14px 8px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  overscroll-behavior: contain;
  -webkit-overflow-scrolling: touch;
}
.ch-loading, .ch-empty {
  text-align: center;
  margin: auto;
  padding: 24px 0;
}

/* separadores de fecha */
.ch-date-sep {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 10px 0 6px;
}
.ch-date-sep::before,
.ch-date-sep::after {
  content: '';
  flex: 1;
  height: 1px;
  background: var(--line, #e9e5f5);
}
.ch-date-sep span {
  font-size: 11px;
  color: var(--muted, #777282);
  font-weight: 700;
  white-space: nowrap;
}

/* burbujas */
.ch-bubble-wrap {
  display: flex;
  margin-bottom: 2px;
}
.ch-bubble-wrap.mine {
  justify-content: flex-end;
}
.ch-bubble {
  max-width: 76%;
  padding: 10px 13px 7px;
  border-radius: 18px;
  position: relative;
  word-break: break-word;
}
.ch-bubble-theirs {
  background: var(--surface, #fff);
  border-bottom-left-radius: 4px;
  box-shadow: 0 2px 8px rgba(57,39,130,.08);
  color: var(--text, #17151d);
}
.ch-bubble-mine {
  background: linear-gradient(135deg, var(--purple, #4d35ff), #694fff);
  border-bottom-right-radius: 4px;
  color: #fff;
  box-shadow: 0 4px 12px rgba(77,53,255,.22);
}
.ch-bubble-sending {
  opacity: 0.7;
}
.ch-body {
  margin: 0;
  font-size: 14px;
  line-height: 1.45;
  white-space: pre-wrap;
}
.ch-ts {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 10px;
  margin-top: 4px;
  opacity: 0.7;
  justify-content: flex-end;
}
.ch-read {
  font-size: 11px;
  opacity: 0.9;
}
.ch-bubble-mine .ch-ts { color: rgba(255,255,255,.85); }

/* mensajes de sistema */
.ch-sys {
  display: flex;
  justify-content: center;
  margin: 10px 0;
}
.ch-sys span {
  background: #ece8ff;
  color: #3a28c9;
  font-size: 12px;
  font-weight: 700;
  padding: 5px 14px;
  border-radius: 99px;
}

/* input */
.ch-input-bar {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  padding: 10px 14px calc(10px + env(safe-area-inset-bottom, 0px));
  background: var(--surface, #fff);
  border-top: 1px solid var(--line, #e9e5f5);
  flex-shrink: 0;
  position: relative;
  z-index: 5;
  pointer-events: auto;
  -webkit-user-select: text;
  user-select: text;
}
.ch-input {
  flex: 1;
  min-height: 42px;
  max-height: 120px;
  border: 1.5px solid var(--line, #e9e5f5);
  border-radius: 21px;
  padding: 10px 14px;
  font: inherit;
  font-size: 14px;
  resize: none;
  background: #faf9ff;
  color: var(--text, #17151d);
  overflow-y: auto;
  transition: border-color .15s;
  line-height: 1.4;
  -webkit-user-select: text;
  user-select: text;
  pointer-events: auto;
  -webkit-appearance: none;
  appearance: none;
  touch-action: manipulation;
}
.ch-input:focus {
  outline: none;
  border-color: var(--purple, #4d35ff);
  background: #fff;
}
.ch-send-btn {
  width: 42px;
  height: 42px;
  flex-shrink: 0;
  border-radius: 50%;
  background: linear-gradient(135deg, var(--purple, #4d35ff), #694fff);
  color: #fff;
  font-size: 16px;
  display: grid;
  place-items: center;
  box-shadow: 0 4px 12px rgba(77,53,255,.3);
  transition: opacity .15s, transform .1s;
}
.ch-send-btn:disabled { opacity: .45; }
.ch-send-btn:active:not(:disabled) { transform: scale(.92); }

/* límite free */
.ch-limit-banner {
  background: #fff5d8;
  color: #6b4700;
  font-size: 12px;
  font-weight: 700;
  border-radius: 12px;
  padding: 10px 13px;
  margin: 6px 0;
  text-align: center;
}
.ch-limit-wall {
  padding: 16px 14px calc(14px + env(safe-area-inset-bottom, 0px));
  background: var(--surface, #fff);
  border-top: 1px solid var(--line, #e9e5f5);
  flex-shrink: 0;
}
.ch-limit-inner {
  background: #f3f0ff;
  border-radius: 18px;
  padding: 18px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  text-align: center;
}
.ch-limit-modal {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  text-align: center;
  padding: 8px 0 4px;
}
.ch-limit-icon {
  font-size: 28px;
  color: var(--purple, #4d35ff);
  margin-bottom: 4px;
}
.ch-limit-inner p, .ch-limit-modal p {
  font-size: 13px;
  color: var(--muted, #777282);
  line-height: 1.5;
  margin: 0;
}

/* ── lista de conversaciones ── */
.ch-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 13px 0;
  border-bottom: 1px solid var(--line, #e9e5f5);
  cursor: pointer;
  -webkit-tap-highlight-color: transparent;
}
.ch-row:last-child { border-bottom: none; }
.ch-row:active { background: #f7f5fd; border-radius: 14px; }
.ch-avatar {
  width: 52px;
  height: 52px;
  border-radius: 50%;
  overflow: hidden;
  flex-shrink: 0;
  background: #e4defd;
}
.ch-avatar img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.ch-avatar-empty {
  display: grid;
  place-items: center;
  background: linear-gradient(135deg, var(--purple, #4d35ff), #816fff);
  color: #fff;
  font-weight: 800;
  font-size: 20px;
}
.ch-row-body { flex: 1; min-width: 0; }
.ch-row-top {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 3px;
}
.ch-row-top strong {
  font-size: 14px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex: 1;
}
.ch-time {
  font-size: 11px;
  color: var(--muted, #777282);
  flex-shrink: 0;
}
.ch-row-bottom {
  display: flex;
  align-items: center;
  gap: 6px;
}
.ch-preview {
  flex: 1;
  margin: 0;
  font-size: 12px;
  color: var(--muted, #777282);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.ch-preview-system {
  font-style: italic;
  color: #9b8fc0;
}
.ch-unread {
  flex-shrink: 0;
  min-width: 20px;
  height: 20px;
  border-radius: 10px;
  background: var(--purple, #4d35ff);
  color: #fff;
  font-size: 11px;
  font-weight: 800;
  display: grid;
  place-items: center;
  padding: 0 5px;
}
`;
    document.head.append(style);
  }

  // ── inicialización ────────────────────────────────────────────────────────
  _injectStyles();

  // ── API pública ───────────────────────────────────────────────────────────
  window.LiggaChat = { open, renderList, handleDeepLink, destroy, leaveDating };

})();
