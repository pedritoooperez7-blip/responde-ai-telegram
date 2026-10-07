const tg = window.Telegram && window.Telegram.WebApp;

if (tg) {
  tg.ready();
  tg.expand();
}

const welcomeScreen = document.getElementById("welcomeScreen");
const analyzeScreen = document.getElementById("analyzeScreen");
const resultScreen = document.getElementById("resultScreen");
const premiumScreen = document.getElementById("premiumScreen");

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
const premiumButton = document.getElementById("premiumButton");

let selectedImage = null;
let selectedMode = null;
let userId = "guest-user";

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
  userId = String(user.id || "guest-user");
  const name = user.first_name || "usuario";
  welcome.textContent = `Hola, ${name}. LiggaCuba está listo para comenzar.`;
}

function showScreen(screen) {
  [welcomeScreen, analyzeScreen, resultScreen, premiumScreen].forEach((item) => {
    if (item) item.classList.add("hidden");
  });
  if (screen) screen.classList.remove("hidden");
  window.scrollTo({ top: 0, behavior: "instant" });
}

function resetAnalysis() {
  selectedImage = null;
  selectedMode = null;
  imageInput.value = "";
  if (previewImage) previewImage.removeAttribute("src");
  if (previewContainer) previewContainer.classList.add("hidden");
  if (modeSection) modeSection.classList.add("hidden");
  if (analyzeButton) {
    analyzeButton.disabled = true;
    analyzeButton.textContent = "Analizar conversación";
  }
  if (analysisStatus) analysisStatus.textContent = "";
  if (limitStatus) limitStatus.textContent = "";
  modeButtons.forEach((button) => button.classList.remove("selected"));
}

function updateUsageStatus(data) {
  if (!limitStatus) return;
  if (data?.premium) {
    limitStatus.textContent = "Premium activo · sin límite";
    return;
  }
  limitStatus.textContent = `${Math.max(0, data?.remaining ?? 0)} análisis restantes hoy`;
}

async function fetchUsageStatus() {
  try {
    const res = await fetch("https://responde-ai-telegram-production.up.railway.app/api/usage", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: userId }),
    });

    if (!res.ok) {
      console.warn("No se pudo consultar uso");
      return;
    }

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
  showScreen(analyzeScreen);
});

backButton.addEventListener("click", () => {
  resetAnalysis();
  showScreen(welcomeScreen);
});

imageInput.addEventListener("change", () => {
  const file = imageInput.files?.[0];
  if (!file) return;

  if (!file.type.startsWith("image/")) {
    analysisStatus.textContent = "Selecciona una imagen válida.";
    imageInput.value = "";
    return;
  }

  selectedImage = file;

  const reader = new FileReader();
  reader.onload = () => {
    previewImage.src = reader.result;
    previewContainer.classList.remove("hidden");
    modeSection.classList.remove("hidden");
    analysisStatus.textContent = "Captura seleccionada. Ahora elige un modo.";
  };

  reader.readAsDataURL(file);
});

removeImageButton.addEventListener("click", () => {
  imageInput.click();
});

modeButtons.forEach((button) => {
  button.addEventListener("click", () => {
    selectedMode = button.dataset.mode;
    modeButtons.forEach((item) => item.classList.remove("selected"));
    button.classList.add("selected");
    analyzeButton.disabled = !selectedImage || !selectedMode;
    analysisStatus.textContent = "Modo seleccionado. Ya puedes analizar.";
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
  analysisStatus.textContent = "Preparando captura…";

  try {
    const testResponse = await fetch("https://responde-ai-telegram-production.up.railway.app/health", {
      method: "GET",
      cache: "no-store",
    });

    if (!testResponse.ok) {
      throw new Error("GET backend HTTP " + testResponse.status);
    }

    analysisStatus.textContent = "Conectado. Preparando imagen…";

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

    analysisStatus.textContent = "Enviando captura al OCR…";

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
    analysisStatus.textContent = "ERROR OCR: " + (error.message || String(error));
    throw error;
  }
}

async function consumeAnalysis() {
  try {
    const res = await fetch("https://responde-ai-telegram-production.up.railway.app/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: userId }),
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

analyzeButton.addEventListener("click", async () => {
  if (!selectedImage || !selectedMode) return;

  analyzeButton.disabled = true;
  analyzeButton.textContent = "Analizando…";
  analysisStatus.textContent = "Extrayendo texto de la captura…";

  try {
    const limit = await consumeAnalysis();
    if (!limit.allowed) {
      analysisStatus.textContent = "Has alcanzado tus 3 análisis gratuitos de hoy. Obtén Premium.";
      analyzeButton.disabled = false;
      analyzeButton.textContent = "Analizar conversación";
      return;
    }

    const text = await runOCR(selectedImage);

    ocrText.textContent = text || "No se pudo detectar texto en la captura.";
    resultText.textContent = demoResponses[selectedMode] || "Puedes responder con naturalidad.";
    copyStatus.textContent = "";
    showScreen(resultScreen);
  } catch (error) {
    console.error("ERROR OCR REAL:", error);
    analysisStatus.textContent = "ERROR OCR: " + (error.message || String(error));
    analyzeButton.disabled = false;
    analyzeButton.textContent = "Analizar conversación";
  }
});

resultBackButton.addEventListener("click", () => {
  showScreen(analyzeScreen);
});

copyButton.addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(resultText.textContent);
    copyStatus.textContent = "Respuesta copiada.";
  } catch (error) {
    copyStatus.textContent = "No se pudo copiar automáticamente.";
  }
});

openPremiumButton.addEventListener("click", () => {
  showScreen(premiumScreen);
});

premiumButton.addEventListener("click", async () => {
  try {
    premiumButton.disabled = true;
    premiumButton.textContent = "Activando…";

    const res = await fetch("https://responde-ai-telegram-production.up.railway.app/api/premium/activate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: userId, plan: "weekly" }),
    });

    if (!res.ok) {
      throw new Error("No se pudo activar Premium");
    }

    const data = await res.json();
    status.textContent = data.success ? "Premium activado correctamente." : "No se pudo activar Premium.";
    showScreen(welcomeScreen);
  } catch (error) {
    status.textContent = "Error al activar Premium.";
    showScreen(welcomeScreen);
  }
});
