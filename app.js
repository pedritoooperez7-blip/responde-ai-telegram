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
const resultText = document.getElementById("resultText");
const copyButton = document.getElementById("copyButton");
const copyStatus = document.getElementById("copyStatus");

let selectedImage = null;
let selectedMode = null;

const demoResponses = {
  natural: "Puedes responder de forma natural y tranquila, manteniendo la conversación sin forzarla.",
  casual: "Jajaja, sí, puede ser 😄 ¿Qué tal si seguimos hablando y vemos qué sale?",
  segura: "Claro. Me parece bien, dime qué tienes pensado y lo hablamos.",
  curiosa: "Eso suena interesante. Ahora me dejaste con curiosidad, ¿qué quieres decir?"
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

  if (!file) {
    return;
  }

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

analyzeButton.addEventListener("click", () => {
  if (!selectedImage || !selectedMode) {
    return;
  }

  analysisStatus.textContent = "Analizando captura...";

  // V0.2: demostración local. El OCR y la IA real se conectarán en el backend.
  window.setTimeout(() => {
    resultText.textContent = demoResponses[selectedMode];
    copyStatus.textContent = "";
    showScreen(resultScreen);
  }, 700);
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
