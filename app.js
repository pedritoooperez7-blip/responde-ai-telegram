const API_BASE = 'https://responde-ai-telegram-production.up.railway.app';

const state = {
  selectedFile: null,
  selectedMode: 'coquetear',
  userId: 'guest-user',
  usage: null,
};

const modeButtons = document.querySelectorAll('.mode-card');
const segments = document.querySelectorAll('.segment');
const tabs = document.querySelectorAll('.tab-home, .tab-profile');
const uploadInput = document.querySelector('#chatImageInput');
const uploadZone = document.querySelector('.upload-zone');
const analyzeButton = document.getElementById('analyzeButton');
const statusMessage = document.getElementById('statusMessage');
const usageText = document.getElementById('usageText');
const refreshUsage = document.getElementById('refreshUsage');
const resultPanel = document.getElementById('resultPanel');
const ocrOutput = document.getElementById('ocrOutput');
const replyOutput = document.getElementById('replyOutput');
const copyResponseButton = document.getElementById('copyResponse');
const copyStatus = document.getElementById('copyStatus');
const uploadText = document.querySelector('.upload-text');

const tg = window.Telegram && window.Telegram.WebApp;
if (tg && tg.initDataUnsafe && tg.initDataUnsafe.user) {
  state.userId = String(tg.initDataUnsafe.user.id || 'guest-user');
}

function setStatus(message, type = '') {
  statusMessage.textContent = message || '';
  statusMessage.className = 'status-message';
  if (type) statusMessage.classList.add(type);
}

function updateUsageUI(data) {
  const remaining = Number(data?.remaining ?? 0);
  if (data?.premium) {
    usageText.textContent = 'Premium activo · sin límite';
    return;
  }
  usageText.textContent = `${Math.max(remaining, 0)} análisis restantes hoy`;
}

async function fetchUsage() {
  try {
    const response = await fetch(`${API_BASE}/api/usage`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: state.userId }),
    });

    if (!response.ok) return;
    const data = await response.json();
    state.usage = data;
    updateUsageUI(data);
  } catch (error) {
    console.warn('No se pudo cargar el uso:', error);
  }
}

async function consumeAnalysis() {
  const response = await fetch(`${API_BASE}/api/analyze`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ user_id: state.userId }),
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.detail || 'No se pudo validar el límite de uso.');
  }

  return response.json();
}

function buildLocalReply(mode, text) {
  const normalized = (text || '').replace(/\s+/g, ' ').trim();
  const lower = normalized.toLowerCase();

  const modes = {
    gracioso: 'Responde con un toque ligero y divertido, sin perder naturalidad.',
    coquetear: 'Usa un tono cálido y atractivo, pero sin presionar ni forzar.',
    provocativo: 'Da un tono más directo e intenso, pero con control y clase.',
    enamorar: 'Haz una respuesta elegante, cercana y romántica, con buena energía y respeto.',
  };

  if (!normalized) {
    return 'No pude detectar texto suficiente para generar una respuesta útil. Intenta otra captura.';
  }

  const base = modes[mode] || modes.coquetear;
  if (lower.includes('hola') || lower.includes('hey')) {
    return `${base} Además, puedes empezar con un saludo amable y seguir la conversación sin hacerla forzada.`;
  }
  if (lower.includes('porque') || lower.includes('por qué')) {
    return `${base} Responde con claridad, evita entrar en defensiva y deja la conversación con una línea amable y directa.`;
  }

  return `${base} Mantén la respuesta breve, auténtica y con buena energía.`;
}

async function callGenerateReply(text, mode) {
  try {
    const response = await fetch(`${API_BASE}/api/generate-reply`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: state.userId, mode, text }),
    });

    if (!response.ok) {
      return buildLocalReply(mode, text);
    }

    const data = await response.json();
    return data.reply || buildLocalReply(mode, text);
  } catch (error) {
    return buildLocalReply(mode, text);
  }
}

function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      if (typeof reader.result !== 'string') {
        reject(new Error('No se pudo convertir la imagen.'));
        return;
      }
      resolve(reader.result);
    };
    reader.onerror = () => reject(new Error('No se pudo leer la imagen.'));
    reader.readAsDataURL(file);
  });
}

async function runOCR(file) {
  const base64 = await fileToBase64(file);
  const response = await fetch(`${API_BASE}/ocr-base64-simple`, {
    method: 'POST',
    headers: { 'Content-Type': 'text/plain' },
    body: base64,
  });

  let data;
  try {
    data = await response.json();
  } catch (error) {
    throw new Error('La respuesta del OCR no es válida.');
  }

  if (!response.ok || !data.success) {
    throw new Error(data?.detail || `Error del OCR (${response.status}).`);
  }

  return (data.text || '').trim();
}

async function handleAnalyze() {
  if (!state.selectedFile) {
    setStatus('Selecciona una imagen antes de analizar.', 'error');
    return;
  }

  if (!state.selectedMode) {
    setStatus('Elige un estilo de respuesta.', 'error');
    return;
  }

  analyzeButton.disabled = true;
  analyzeButton.textContent = 'Analizando...';
  setStatus('Procesando imagen...');

  try {
    const usageResult = await consumeAnalysis();
    if (!usageResult.allowed) {
      setStatus('Has alcanzado tus 3 análisis gratuitos de hoy. Obtén Premium.', 'error');
      analyzeButton.disabled = false;
      analyzeButton.textContent = 'Analizar con Liggo';
      return;
    }

    const text = await runOCR(state.selectedFile);
    const reply = await callGenerateReply(text, state.selectedMode);

    ocrOutput.textContent = text || 'No se detectó texto en la imagen.';
    replyOutput.textContent = reply;
    resultPanel.classList.remove('hidden');
    setStatus('Listo. Tu respuesta está preparada.', 'success');

    if (usageResult.remaining !== undefined) {
      updateUsageUI({ remaining: usageResult.remaining, premium: usageResult.premium });
    }
  } catch (error) {
    console.error(error);
    setStatus(error.message || 'No se pudo completar el análisis.', 'error');
  } finally {
    analyzeButton.disabled = false;
    analyzeButton.textContent = 'Analizar con Liggo';
  }
}

async function handleRefreshUsage() {
  setStatus('Actualizando cuota...');
  await fetchUsage();
  setStatus('');
}

modeButtons.forEach((button) => {
  button.addEventListener('click', () => {
    modeButtons.forEach((card) => card.classList.remove('selected'));
    button.classList.add('selected');
    state.selectedMode = button.dataset.mode || 'coquetear';
    setStatus('Modo listo. Puedes analizar la imagen.', 'success');
  });
});

segments.forEach((button) => {
  button.addEventListener('click', () => {
    segments.forEach((item) => item.classList.remove('active'));
    button.classList.add('active');
  });
});

tabs.forEach((button) => {
  button.addEventListener('click', () => {
    tabs.forEach((item) => item.classList.remove('active'));
    button.classList.add('active');
  });
});

if (uploadInput && uploadZone) {
  uploadZone.addEventListener('click', () => uploadInput.click());
  uploadInput.addEventListener('change', () => {
    const file = uploadInput.files?.[0];
    if (!file) return;
    if (!file.type.startsWith('image/')) {
      setStatus('Selecciona un archivo de imagen válido.', 'error');
      return;
    }
    state.selectedFile = file;
    if (uploadText) {
      uploadText.textContent = file.name.length > 16 ? `${file.name.slice(0, 16)}...` : file.name;
    }
    setStatus('Imagen cargada. Elige un estilo y analiza.', 'success');
  });
}

analyzeButton.addEventListener('click', handleAnalyze);
refreshUsage.addEventListener('click', handleRefreshUsage);

copyResponseButton.addEventListener('click', async () => {
  try {
    await navigator.clipboard.writeText(replyOutput.textContent);
    copyStatus.textContent = 'Respuesta copiada.';
  } catch (error) {
    copyStatus.textContent = 'No se pudo copiar automáticamente.';
  }
});

fetchUsage();
setStatus('');
