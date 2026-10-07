const tg = window.Telegram && window.Telegram.WebApp;

if (tg) {
  tg.ready();
  tg.expand();
}

const welcomeScreen = document.getElementById("welcomeScreen");
const analyzeScreen = document.getElementById("analyzeScreen");
const resultScreen = document.getElementById("resultScreen");

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

const resultBackButton = document.getElementById("resultBackButton");
const ocrText = document.getElementById("ocrText");
const resultText = document.getElementById("resultText");
const copyButton = document.getElementById("copyButton");
const copyStatus = document.getElementById("copyStatus");

let selectedImage = null;
let selectedMode = null;
let ocrWorker = null;

const demoResponses = {
  natural: "Puedes responder de forma natural y tranquila, manteniendo la conversación sin forzarla.",
  casual: "Puedes mantener un tono relajado y cercano para que la conversación siga fluyendo.",
  segura: "Una respuesta clara y tranquila puede mantener la conversación sin complicarla.",
  curiosa: "Puedes dejar una pequeña pregunta abierta para mostrar interés y seguir la conversación."
};

const user = tg?.initDataUnsafe?.user;
if (user) {
  const name = user.first_name || "usuario";
  welcome.textContent = `Hola, ${name}. Responde AI está listo para comenzar.`;
}

function showScreen(screen) {
  [welcomeScreen, analyzeScreen, resultScreen].forEach((item) => {
    item.classList.add("hidden");
  });
  screen.classList.remove("hidden");
  window.scrollTo({ top: 0, behavior: "instant" });
}

function resetAnalysis() {
  selectedImage = null;
  selectedMode = null;
  imageInput.value = "";
  previewImage.removeAttribute("src");
  previewContainer.classList.add("hidden");
  modeSection.classList.add("hidden");
  analyzeButton.disabled = true;
  analyzeButton.textContent = "Analizar conversación";
  analysisStatus.textContent = "";
  modeButtons.forEach((button) => button.classList.remove("selected"));
}

startButton.addEventListener("click", () => {
  status.textContent = "";
  resetAnalysis();
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

const OCR_API_URL = "https://responde-ai-telegram-production.up.railway.app/ocr";

async function runOCR(image) {
  const formData = new FormData();
  formData.append("file", image, image.name || "captura.jpg");

  const response = await fetch(OCR_API_URL, {
    method: "POST",
    body: formData
  });

  let data;

  try {
    data = await response.json();
  } catch (error) {
    throw new Error("El backend devolvió una respuesta no válida.");
  }

  if (!response.ok || !data.success) {
    throw new Error(data.detail || `Error HTTP ${response.status}`);
  }

  return (data.text || "").trim();
}

analyzeButton.addEventListener("click", async () => {
  if (!selectedImage || !selectedMode) return;

  analyzeButton.disabled = true;
  analyzeButton.textContent = "Analizando…";
  analysisStatus.textContent = "Extrayendo texto de la captura…";

  try {
    const text = await runOCR(selectedImage);

    ocrText.textContent = text || "No se pudo detectar texto en la captura.";
    resultText.textContent = demoResponses[selectedMode];
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
