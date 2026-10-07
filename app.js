const tg = window.Telegram && window.Telegram.WebApp;

if (tg) {
  tg.ready();
  tg.expand();
}

const translations = {
  es: {
    brand: "LIGGACUBA",
    welcomeTitle: "Tu asistente para responder mejor",
    welcomeText: "Analiza una conversación, extrae el texto y responde con estilo.",
    start: "Comenzar",
    chatTitle: "Chat",
    chatSubtitle: "Selecciona una captura de pantalla para analizar.",
    heroSelect: "Seleccionar captura",
    fileHint: "JPG, PNG o WEBP",
    changeImage: "Cambiar captura",
    chooseMode: "¿Qué tipo de respuesta buscas?",
    analyze: "Analizar conversación",
    resultTitle: "Resultado",
    resultIntro: "Respuesta sugerida por LiggaCuba:",
    copy: "Copiar respuesta",
    premiumTitle: "Premium",
    premiumPlan1: "Plan semanal: 2500 CUP",
    premiumPlan2: "Plan anual: 15500 CUP",
    premiumButton: "Obtener Premium",
    storyTitle: "Estado / Story",
    storySubtitle: "Sube una captura de la historia a responder.",
    settingsTitle: "Configuración",
    settingsLanguage: "Idioma",
    settingsContact: "Contáctanos",
    settingsOpinion: "Tu opinión",
    settingsBack: "Volver",
    back: "Volver",
    premiumLink: "Premium",
    settingsLink: "Configuración",
    statusNo: "Selecciona una imagen válida.",
    statusReady: "Captura seleccionada. Ahora elige un modo.",
    statusMode: "Modo seleccionado. Ya puedes analizar.",
    copying: "Respuesta copiada.",
    copyFail: "No se pudo copiar automáticamente.",
    modeNatural: "Natural",
    modeCasual: "Casual",
    modeSafe: "Segura",
    modeCurious: "Con curiosidad",
    modeFunny: "Gracioso",
    modeFlirty: "Coquetear",
    modeLove: "Enamorar",
    modeProvocative: "Provocativo",
    modeStoryLabel: "Modo de respuesta",
    limitLabel: "análisis restantes hoy",
    premiumActive: "Premium activo · sin límite",
    limitReached: "Has alcanzado tus 3 análisis gratuitos de hoy. Obtén Premium.",
    premiumActivated: "Premium activado correctamente.",
    premiumError: "Error al activar Premium.",
    analyzing: "Analizando…",
    extracting: "Extrayendo texto de la captura…",
    preparing: "Preparando captura…",
    connected: "Conectado. Preparando imagen…",
    sending: "Enviando captura al OCR…",
  },
  en: {
    brand: "LIGGACUBA",
    welcomeTitle: "Your assistant for better replies",
    welcomeText: "Analyze a conversation, extract the text and reply with style.",
    start: "Start",
    chatTitle: "Chat",
    chatSubtitle: "Select a screenshot to analyze.",
    heroSelect: "Choose capture",
    fileHint: "JPG, PNG or WEBP",
    changeImage: "Change image",
    chooseMode: "What type of response do you want?",
    analyze: "Analyze conversation",
    resultTitle: "Result",
    resultIntro: "Suggested answer by LiggaCuba:",
    copy: "Copy response",
    premiumTitle: "Premium",
    premiumPlan1: "Weekly plan: 2500 CUP",
    premiumPlan2: "Annual plan: 15500 CUP",
    premiumButton: "Get Premium",
    storyTitle: "Status / Story",
    storySubtitle: "Upload a story screenshot to reply.",
    settingsTitle: "Settings",
    settingsLanguage: "Language",
    settingsContact: "Contact us",
    settingsOpinion: "Your opinion",
    settingsBack: "Back",
    back: "Back",
    premiumLink: "Premium",
    settingsLink: "Settings",
    statusNo: "Select a valid image.",
    statusReady: "Capture selected. Now choose a mode.",
    statusMode: "Mode selected. You can analyze now.",
    copying: "Response copied.",
    copyFail: "Could not copy automatically.",
    modeNatural: "Natural",
    modeCasual: "Casual",
    modeSafe: "Safe",
    modeCurious: "Curious",
    modeFunny: "Funny",
    modeFlirty: "Flirty",
    modeLove: "Romantic",
    modeProvocative: "Provocative",
    modeStoryLabel: "Reply mode",
    limitLabel: "analyses left today",
    premiumActive: "Premium active · unlimited",
    limitReached: "You reached your 3 free analyses today. Get Premium.",
    premiumActivated: "Premium activated successfully.",
    premiumError: "Error activating Premium.",
    analyzing: "Analyzing…",
    extracting: "Extracting text from the image…",
    preparing: "Preparing capture…",
    connected: "Connected. Preparing image…",
    sending: "Sending capture to OCR…",
  }
};

const appState = {
  selectedImage: null,
  selectedMode: null,
  userId: "guest-user",
  language: "es",
  activeScreen: "welcome",
  activeModule: "chat",
};

const welcomeScreen = document.getElementById("welcomeScreen");
const analyzeScreen = document.getElementById("analyzeScreen");
const resultScreen = document.getElementById("resultScreen");
const premiumScreen = document.getElementById("premiumScreen");
const storyScreen = document.getElementById("storyScreen");
const settingsScreen = document.getElementById("settingsScreen");

const welcome = document.getElementById("welcome");
const startButton = document.getElementById("startButton");
const status = document.getElementById("status");
const backButton = document.getElementById("backButton");
const imageInput = document.getElementById("imageInput");
const previewContainer = document.getElementById("previewContainer");
const previewImage = document.getElementById("previewImage");
const removeImageButton = document.getElementById("removeImageButton");
const modeSection = document.getElementById("modeSection");
const modeButtons = document.querySelectorAll(".mode-button");
const analyzeButton = document.getElementById("analyzeButton");
const analysisStatus = document.getElementById("analysisStatus");
const limitStatus = document.getElementById("limitStatus");

const resultBackButton = document.getElementById("resultBackButton");
const ocrText = document.getElementById("ocrText");
const resultText = document.getElementById("resultText");
const copyButton = document.getElementById("copyButton");
const copyStatus = document.getElementById("copyStatus");
const openPremiumButton = document.getElementById("openPremiumButton");
const openSettingsButton = document.getElementById("openSettingsButton");
const premiumButton = document.getElementById("premiumButton");
const backButtonPremium = document.getElementById("backButtonPremium");
const storyButton = document.getElementById("storyButton");
const backButtonStory = document.getElementById("backButtonStory");
const storyImageInput = document.getElementById("storyImageInput");
const storyPreviewContainer = document.getElementById("storyPreviewContainer");
const storyPreviewImage = document.getElementById("storyPreviewImage");
const storyRemoveImageButton = document.getElementById("storyRemoveImageButton");
const storyModeSection = document.getElementById("storyModeSection");
const storyModeButtons = document.querySelectorAll(".story-mode-button");
const storyAnalyzeButton = document.getElementById("storyAnalyzeButton");
const storyAnalysisStatus = document.getElementById("storyAnalysisStatus");
const storyLimitStatus = document.getElementById("storyLimitStatus");
const languageToggle = document.getElementById("languageToggle");

const demoResponses = {
  natural: "Puedes responder de forma natural y tranquila, manteniendo la conversación sin forzarla.",
  casual: "Puedes mantener un tono relajado y cercano para que la conversación siga fluyendo.",
  segura: "Una respuesta clara y tranquila puede mantener la conversación sin complicarla.",
  curiosa: "Puedes dejar una pequeña pregunta abierta para mostrar interés y seguir la conversación.",
  gracioso: "Puedes responder con un toque ligero y divertido, sin perder naturalidad.",
  coquetear: "Puedes responder con un tono cálido y atractivo, sin presionar ni forzar.",
  enamorar: "Haz una respuesta amable, cercana y elegante, con intención clara pero respetuosa.",
  provocativo: "Haz una respuesta más intensa, directa y seductora, pero siempre controlada.",
};

const user = tg?.initDataUnsafe?.user;
if (user) {
  appState.userId = String(user.id || "guest-user");
  const name = user.first_name || "usuario";
  welcome.textContent = `Hola, ${name}. LiggaCuba está listo para comenzar.`;
}

function t(key) {
  const dict = translations[appState.language] || translations.es;
  return dict[key] || key;
}

function updateLanguageUI() {
  document.querySelector(".brand").textContent = t("brand");
  document.querySelector("#welcomeTitle").textContent = t("welcomeTitle");
  welcome.textContent = t("welcomeText");
  startButton.textContent = t("start");
  document.querySelector("#chatTitle").textContent = t("chatTitle");
  document.querySelector("#chatSubtitle").textContent = t("chatSubtitle");
  document.querySelector("#storyTitle").textContent = t("storyTitle");
  document.querySelector("#storySubtitle").textContent = t("storySubtitle");
  document.querySelector("#settingsTitle").textContent = t("settingsTitle");
  document.querySelector("#resultTitle").textContent = t("resultTitle");
  document.querySelector("#resultIntro").textContent = t("resultIntro");
  document.querySelector("#copyButton").textContent = t("copy");
  document.querySelector("#premiumTitle").textContent = t("premiumTitle");
  document.querySelector("#premiumPlan1").textContent = t("premiumPlan1");
  document.querySelector("#premiumPlan2").textContent = t("premiumPlan2");
  document.querySelector("#premiumButton").textContent = t("premiumButton");
  document.querySelector("#settingsLanguage").textContent = t("settingsLanguage");
  document.querySelector("#settingsContact").textContent = t("settingsContact");
  document.querySelector("#settingsOpinion").textContent = t("settingsOpinion");
  document.querySelector("#openPremiumButton").textContent = t("premiumLink");
  document.querySelector("#openSettingsButton").textContent = t("settingsLink");
  document.querySelector("#storyButton").textContent = t("storyTitle");
  document.querySelector("#imageLabel").textContent = t("heroSelect");
  document.querySelector("#imageHint").textContent = t("fileHint");
  document.querySelector("#removeImageButton").textContent = t("changeImage");
  document.querySelector("#modeLabel").textContent = t("chooseMode");
  analyzeButton.textContent = t("analyze");
  const modeLabels = {
    natural: t("modeNatural"),
    casual: t("modeCasual"),
    segura: t("modeSafe"),
    curiosa: t("modeCurious"),
    gracioso: t("modeFunny"),
    coquetear: t("modeFlirty"),
    enamorar: t("modeLove"),
    provocativo: t("modeProvocative"),
  };
  modeButtons.forEach((btn) => {
    const key = btn.dataset.mode;
    if (modeLabels[key]) btn.textContent = modeLabels[key];
  });
  storyModeButtons.forEach((btn) => {
    const key = btn.dataset.mode;
    if (modeLabels[key]) btn.textContent = modeLabels[key];
  });
  if (languageToggle) {
    languageToggle.value = appState.language;
  }
}

function showScreen(screenName) {
  appState.activeScreen = screenName;
  [welcomeScreen, analyzeScreen, resultScreen, premiumScreen, storyScreen, settingsScreen].forEach((item) => {
    if (item) item.classList.add("hidden");
  });
  const target = {
    welcome: welcomeScreen,
    chat: analyzeScreen,
    result: resultScreen,
    premium: premiumScreen,
    story: storyScreen,
    settings: settingsScreen,
  }[screenName];
  if (target) target.classList.remove("hidden");
  window.scrollTo({ top: 0, behavior: "instant" });
}

function resetAnalysis() {
  appState.selectedImage = null;
  appState.selectedMode = null;
  imageInput.value = "";
  if (previewImage) previewImage.removeAttribute("src");
  if (previewContainer) previewContainer.classList.add("hidden");
  if (modeSection) modeSection.classList.add("hidden");
  if (analyzeButton) {
    analyzeButton.disabled = true;
    analyzeButton.textContent = t("analyze");
  }
  if (analysisStatus) analysisStatus.textContent = "";
  if (limitStatus) limitStatus.textContent = "";
  modeButtons.forEach((button) => button.classList.remove("selected"));
}

function resetStoryAnalysis() {
  appState.selectedImage = null;
  appState.selectedMode = null;
  storyImageInput.value = "";
  if (storyPreviewImage) storyPreviewImage.removeAttribute("src");
  if (storyPreviewContainer) storyPreviewContainer.classList.add("hidden");
  if (storyModeSection) storyModeSection.classList.add("hidden");
  if (storyAnalyzeButton) {
    storyAnalyzeButton.disabled = true;
    storyAnalyzeButton.textContent = t("analyze");
  }
  if (storyAnalysisStatus) storyAnalysisStatus.textContent = "";
  if (storyLimitStatus) storyLimitStatus.textContent = "";
  storyModeButtons.forEach((button) => button.classList.remove("selected"));
}

function updateUsageStatus(data) {
  if (!limitStatus || !storyLimitStatus) return;
  if (data?.premium) {
    limitStatus.textContent = t("premiumActive");
    storyLimitStatus.textContent = t("premiumActive");
    return;
  }
  const remaining = Math.max(0, data?.remaining ?? 0);
  limitStatus.textContent = `${remaining} ${t("limitLabel")}`;
  storyLimitStatus.textContent = `${remaining} ${t("limitLabel")}`;
}

async function fetchUsageStatus() {
  try {
    const res = await fetch("https://responde-ai-telegram-production.up.railway.app/api/usage", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: appState.userId }),
    });

    if (!res.ok) return;
    const data = await res.json();
    updateUsageStatus(data);
  } catch (err) {
    console.warn("Uso no disponible:", err);
  }
}

startButton.addEventListener("click", async () => {
  status.textContent = "";
  resetAnalysis();
  await fetchUsageStatus();
  showScreen("chat");
});

backButton.addEventListener("click", () => {
  resetAnalysis();
  showScreen("welcome");
});

backButtonPremium.addEventListener("click", () => {
  showScreen("chat");
});

storyButton.addEventListener("click", () => {
  resetStoryAnalysis();
  showScreen("story");
});

backButtonStory.addEventListener("click", () => {
  resetStoryAnalysis();
  showScreen("chat");
});

openSettingsButton.addEventListener("click", () => {
  showScreen("settings");
});

languageToggle.addEventListener("change", (event) => {
  appState.language = event.target.value;
  updateLanguageUI();
});

imageInput.addEventListener("change", () => {
  const file = imageInput.files?.[0];
  if (!file) return;

  if (!file.type.startsWith("image/")) {
    analysisStatus.textContent = t("statusNo");
    imageInput.value = "";
    return;
  }

  appState.selectedImage = file;

  const reader = new FileReader();
  reader.onload = () => {
    previewImage.src = reader.result;
    previewContainer.classList.remove("hidden");
    modeSection.classList.remove("hidden");
    analysisStatus.textContent = t("statusReady");
  };

  reader.readAsDataURL(file);
});

storyImageInput.addEventListener("change", () => {
  const file = storyImageInput.files?.[0];
  if (!file) return;

  if (!file.type.startsWith("image/")) {
    storyAnalysisStatus.textContent = t("statusNo");
    storyImageInput.value = "";
    return;
  }

  appState.selectedImage = file;
  const reader = new FileReader();
  reader.onload = () => {
    storyPreviewImage.src = reader.result;
    storyPreviewContainer.classList.remove("hidden");
    storyModeSection.classList.remove("hidden");
    storyAnalysisStatus.textContent = t("statusReady");
  };
  reader.readAsDataURL(file);
});

removeImageButton.addEventListener("click", () => {
  imageInput.click();
});

storyRemoveImageButton.addEventListener("click", () => {
  storyImageInput.click();
});

modeButtons.forEach((button) => {
  button.addEventListener("click", () => {
    appState.selectedMode = button.dataset.mode;
    modeButtons.forEach((item) => item.classList.remove("selected"));
    button.classList.add("selected");
    analyzeButton.disabled = !appState.selectedImage || !appState.selectedMode;
    analysisStatus.textContent = t("statusMode");
  });
});

storyModeButtons.forEach((button) => {
  button.addEventListener("click", () => {
    appState.selectedMode = button.dataset.mode;
    storyModeButtons.forEach((item) => item.classList.remove("selected"));
    button.classList.add("selected");
    storyAnalyzeButton.disabled = !appState.selectedImage || !appState.selectedMode;
    storyAnalysisStatus.textContent = t("statusMode");
  });
});

const OCR_API_URL = "https://responde-ai-telegram-production.up.railway.app/ocr-base64-simple";

async function prepareImageForOCR(file) {
  return await new Promise((resolve, reject) => {
    const reader = new FileReader();

    reader.onload = () => {
      const img = new Image();

      img.onload = () => {
        const maxSize = 1280;
        let width = img.naturalWidth;
        let height = img.naturalHeight;

        if (width > maxSize || height > maxSize) {
          const scale = Math.min(maxSize / width, maxSize / height);
          width = Math.round(width * scale);
          height = Math.round(height * scale);
        }

        const canvas = document.createElement("canvas");
        canvas.width = width;
        canvas.height = height;
        const ctx = canvas.getContext("2d");

        if (!ctx) {
          reject(new Error("No se pudo preparar la imagen."));
          return;
        }

        ctx.drawImage(img, 0, 0, width, height);

        canvas.toBlob((blob) => {
          if (!blob) {
            reject(new Error("No se pudo comprimir la imagen."));
            return;
          }
          resolve(new File([blob], "captura-ocr.jpg", { type: "image/jpeg" }));
        }, "image/jpeg", 0.7);
      };

      img.onerror = () => reject(new Error("No se pudo cargar la captura."));
      img.src = reader.result;
    };

    reader.onerror = () => reject(new Error("No se pudo leer la captura."));
    reader.readAsDataURL(file);
  });
}

async function runOCR(image) {
  const activeStatus = analysisStatus || storyAnalysisStatus;
  if (activeStatus) activeStatus.textContent = t("preparing");

  try {
    const testResponse = await fetch("https://responde-ai-telegram-production.up.railway.app/health", {
      method: "GET",
      cache: "no-store",
    });

    if (!testResponse.ok) throw new Error("GET backend HTTP " + testResponse.status);

    if (activeStatus) activeStatus.textContent = t("connected");

    const preparedImage = await prepareImageForOCR(image);

    const base64 = await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => {
        if (typeof reader.result !== "string") {
          reject(new Error("No se pudo convertir la imagen."));
          return;
        }
        resolve(reader.result);
      };
      reader.onerror = () => reject(new Error("No se pudo leer la imagen preparada."));
      reader.readAsDataURL(preparedImage);
    });

    if (activeStatus) activeStatus.textContent = t("sending");

    const response = await fetch(OCR_API_URL, {
      method: "POST",
      headers: { "Content-Type": "text/plain" },
      body: base64,
    });

    let data;
    try {
      data = await response.json();
    } catch (error) {
      throw new Error("El backend devolvió una respuesta no válida.");
    }

    if (!response.ok || !data.success) {
      throw new Error(data?.detail || `Error HTTP ${response.status}`);
    }

    return (data.text || "").trim();
  } catch (error) {
    console.error("ERROR OCR REAL:", error);
    if (activeStatus) activeStatus.textContent = "ERROR OCR: " + (error.message || String(error));
    throw error;
  }
}

async function consumeAnalysis() {
  try {
    const res = await fetch("https://responde-ai-telegram-production.up.railway.app/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: appState.userId }),
    });

    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.detail || "No se pudo validar el límite.");
    }

    return await res.json();
  } catch (error) {
    throw error;
  }
}

async function analyzeCurrentImage() {
  if (!appState.selectedImage || !appState.selectedMode) return;

  const currentAnalyzeButton = appState.activeScreen === "story" ? storyAnalyzeButton : analyzeButton;
  const currentStatusEl = appState.activeScreen === "story" ? storyAnalysisStatus : analysisStatus;

  currentAnalyzeButton.disabled = true;
  currentAnalyzeButton.textContent = t("analyzing");
  currentStatusEl.textContent = t("extracting");

  try {
    const limit = await consumeAnalysis();
    if (!limit.allowed) {
      currentStatusEl.textContent = t("limitReached");
      currentAnalyzeButton.disabled = false;
      currentAnalyzeButton.textContent = t("analyze");
      return;
    }

    const text = await runOCR(appState.selectedImage);
    ocrText.textContent = text || "No se pudo detectar texto en la captura.";
    resultText.textContent = demoResponses[appState.selectedMode] || "Puedes responder con naturalidad.";
    copyStatus.textContent = "";
    showScreen("result");
  } catch (error) {
    console.error("ERROR OCR REAL:", error);
    currentStatusEl.textContent = "ERROR OCR: " + (error.message || String(error));
    currentAnalyzeButton.disabled = false;
    currentAnalyzeButton.textContent = t("analyze");
  }
}

analyzeButton.addEventListener("click", analyzeCurrentImage);
storyAnalyzeButton.addEventListener("click", analyzeCurrentImage);

resultBackButton.addEventListener("click", () => {
  if (appState.activeModule === "story") {
    showScreen("story");
  } else {
    showScreen("chat");
  }
});

copyButton.addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(resultText.textContent);
    copyStatus.textContent = t("copying");
  } catch (error) {
    copyStatus.textContent = t("copyFail");
  }
});

openPremiumButton.addEventListener("click", () => {
  showScreen("premium");
});

premiumButton.addEventListener("click", async () => {
  try {
    premiumButton.disabled = true;
    premiumButton.textContent = "Activando…";

    const res = await fetch("https://responde-ai-telegram-production.up.railway.app/api/premium/activate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: appState.userId, plan: "weekly" }),
    });

    if (!res.ok) throw new Error("No se pudo activar Premium");

    const data = await res.json();
    status.textContent = data.success ? t("premiumActivated") : t("premiumError");
    showScreen("welcome");
  } catch (error) {
    status.textContent = t("premiumError");
    showScreen("welcome");
  }
});

updateLanguageUI();
showScreen("welcome");
