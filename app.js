const modeButtons = document.querySelectorAll('.mode-card');
const segments = document.querySelectorAll('.segment');
const tabs = document.querySelectorAll('.tab-home, .tab-profile');
const uploadInput = document.querySelector('#chatImageInput');
const uploadZone = document.querySelector('.upload-zone');

modeButtons.forEach((button) => {
  button.addEventListener('click', () => {
    modeButtons.forEach((card) => card.classList.remove('selected'));
    button.classList.add('selected');
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
    const label = uploadZone.querySelector('.upload-text');
    if (label) {
      label.textContent = file.name.length > 18 ? `${file.name.slice(0, 18)}...` : file.name;
    }
  });
}
