const dropZone = document.getElementById("drop-zone");
const fileInput = document.getElementById("file-input");
const previewArea = document.getElementById("preview-area");
const originalImg = document.getElementById("original-img");
const resultImg = document.getElementById("result-img");
const resultSpinner = document.getElementById("result-spinner");
const resultMeta = document.getElementById("result-meta");
const downloadBtn = document.getElementById("download-btn");
const canvasSizeSelect = document.getElementById("canvas-size");
const errorMsg = document.getElementById("error-msg");

let lastFile = null;

dropZone.addEventListener("click", () => fileInput.click());

dropZone.addEventListener("dragover", (e) => {
  e.preventDefault();
  dropZone.classList.add("drag-over");
});

dropZone.addEventListener("dragleave", () => {
  dropZone.classList.remove("drag-over");
});

dropZone.addEventListener("drop", (e) => {
  e.preventDefault();
  dropZone.classList.remove("drag-over");
  const file = e.dataTransfer.files[0];
  if (file) handleFile(file);
});

fileInput.addEventListener("change", () => {
  const file = fileInput.files[0];
  if (file) handleFile(file);
});

canvasSizeSelect.addEventListener("change", () => {
  if (lastFile) handleFile(lastFile, /*isReprocess=*/ true);
});

function showError(message) {
  errorMsg.textContent = message;
  errorMsg.hidden = false;
}

function clearError() {
  errorMsg.hidden = true;
  errorMsg.textContent = "";
}

async function handleFile(file, isReprocess = false) {
  clearError();
  lastFile = file;

  if (!isReprocess) {
    originalImg.src = URL.createObjectURL(file);
  }

  previewArea.hidden = false;
  resultImg.src = "";
  resultMeta.textContent = "";
  downloadBtn.hidden = true;
  resultSpinner.hidden = false;

  const canvasSize = canvasSizeSelect.value;
  const formData = new FormData();
  formData.append("file", file);

  try {
    const res = await fetch(`/api/process?canvas_size=${canvasSize}`, {
      method: "POST",
      body: formData,
    });

    if (!res.ok) {
      let detail = "Something went wrong while processing the image.";
      try {
        const body = await res.json();
        if (body.detail) detail = body.detail;
      } catch (_) {
        /* ignore parse errors */
      }
      throw new Error(detail);
    }

    const width = res.headers.get("X-Output-Width");
    const height = res.headers.get("X-Output-Height");
    const bytes = parseInt(res.headers.get("X-Output-Bytes") || "0", 10);

    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    resultImg.src = url;
    resultMeta.textContent = `${width} × ${height}px · ${(bytes / 1024).toFixed(0)} KB · meets Tourplay's requirements`;
    downloadBtn.href = url;
    downloadBtn.hidden = false;
  } catch (err) {
    showError(err.message || String(err));
  } finally {
    resultSpinner.hidden = true;
  }
}
