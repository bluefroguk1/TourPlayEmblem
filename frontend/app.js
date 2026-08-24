const dropZone = document.getElementById("drop-zone");
const fileInput = document.getElementById("file-input");
const previewArea = document.getElementById("preview-area");
const originalImg = document.getElementById("original-img");
const resultImg = document.getElementById("result-img");
const resultSpinner = document.getElementById("result-spinner");
const resultMeta = document.getElementById("result-meta");
const downloadBtn = document.getElementById("download-btn");
const errorMsg = document.getElementById("error-msg");

const cropArea = document.getElementById("crop-area");
const cropStage = document.getElementById("crop-stage");
const cropImg = document.getElementById("crop-img");
const cropBox = document.getElementById("crop-box");
const cropConfirmBtn = document.getElementById("crop-confirm");
const cropCancelBtn = document.getElementById("crop-cancel");

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

function showError(message) {
  errorMsg.textContent = message;
  errorMsg.hidden = false;
}

function clearError() {
  errorMsg.hidden = true;
  errorMsg.textContent = "";
}

async function handleFile(file) {
  clearError();
  cropArea.hidden = true;
  lastFile = file;
  originalImg.src = URL.createObjectURL(file);
  await processBlob(file);
}

// Shared by both a fresh upload and a confirmed manual crop: POST the image
// data, render the result, or fall back to the crop tool on a specific
// "no subject detected" failure.
async function processBlob(blob) {
  previewArea.hidden = false;
  resultImg.src = "";
  resultMeta.textContent = "";
  downloadBtn.hidden = true;
  resultSpinner.hidden = false;

  const formData = new FormData();
  formData.append("file", blob, "upload.png");

  try {
    const res = await fetch("/api/process", {
      method: "POST",
      body: formData,
    });

    if (!res.ok) {
      const errorCode = res.headers.get("X-Error-Code");
      let detail = "Something went wrong while processing the image.";
      try {
        const body = await res.json();
        if (body.detail) detail = body.detail;
      } catch (_) {
        /* ignore parse errors */
      }

      if (errorCode === "no_subject_detected" && lastFile) {
        showError(`${detail} Crop to the part you want to keep below, then confirm.`);
        openCropTool(lastFile);
        return;
      }

      throw new Error(detail);
    }

    const width = res.headers.get("X-Output-Width");
    const height = res.headers.get("X-Output-Height");
    const bytes = parseInt(res.headers.get("X-Output-Bytes") || "0", 10);

    const outBlob = await res.blob();
    const url = URL.createObjectURL(outBlob);
    resultImg.src = url;
    resultMeta.textContent = `${width} × ${height}px (auto-sized) · ${(bytes / 1024).toFixed(0)} KB · meets Tourplay's requirements`;
    downloadBtn.href = url;
    downloadBtn.hidden = false;
  } catch (err) {
    showError(err.message || String(err));
  } finally {
    resultSpinner.hidden = true;
  }
}

// ---------------------------------------------------------------------
// Manual crop tool (fallback shown only when auto-detection fails)
// ---------------------------------------------------------------------

const MIN_CROP_SIZE = 30; // in displayed (CSS) pixels

let boxRect = { left: 0, top: 0, width: 0, height: 0 };
let dragMode = null; // null | "move" | "nw" | "ne" | "sw" | "se"
let dragStart = { x: 0, y: 0 };
let boxStart = { left: 0, top: 0, width: 0, height: 0 };

function openCropTool(file) {
  previewArea.hidden = true;
  const url = URL.createObjectURL(file);
  cropImg.onload = () => requestAnimationFrame(initCropBox);
  cropImg.src = url;
  cropArea.hidden = false;
}

function initCropBox() {
  const w = cropImg.clientWidth;
  const h = cropImg.clientHeight;
  const side = Math.round(Math.min(w, h) * 0.9);
  setBoxRect({
    left: Math.round((w - side) / 2),
    top: Math.round((h - side) / 2),
    width: side,
    height: side,
  });
}

function setBoxRect(rect) {
  boxRect = rect;
  cropBox.style.left = `${rect.left}px`;
  cropBox.style.top = `${rect.top}px`;
  cropBox.style.width = `${rect.width}px`;
  cropBox.style.height = `${rect.height}px`;
}

function clamp(value, min, max) {
  return Math.min(Math.max(value, min), max);
}

function startDrag(mode, e) {
  dragMode = mode;
  dragStart = { x: e.clientX, y: e.clientY };
  boxStart = { ...boxRect };
  e.target.setPointerCapture(e.pointerId);
  e.preventDefault();
  e.stopPropagation();
}

cropBox.addEventListener("pointerdown", (e) => startDrag("move", e));
cropBox.querySelectorAll(".crop-handle").forEach((handle) => {
  handle.addEventListener("pointerdown", (e) =>
    startDrag(handle.dataset.handle, e)
  );
});

document.addEventListener("pointermove", (e) => {
  if (!dragMode) return;

  const stageW = cropImg.clientWidth;
  const stageH = cropImg.clientHeight;
  const dx = e.clientX - dragStart.x;
  const dy = e.clientY - dragStart.y;

  let { left, top, width, height } = boxStart;

  if (dragMode === "move") {
    left = clamp(boxStart.left + dx, 0, stageW - boxStart.width);
    top = clamp(boxStart.top + dy, 0, stageH - boxStart.height);
  } else {
    if (dragMode.includes("w")) {
      const newLeft = clamp(
        boxStart.left + dx,
        0,
        boxStart.left + boxStart.width - MIN_CROP_SIZE
      );
      width = boxStart.width - (newLeft - boxStart.left);
      left = newLeft;
    } else if (dragMode.includes("e")) {
      width = clamp(boxStart.width + dx, MIN_CROP_SIZE, stageW - boxStart.left);
    }

    if (dragMode.includes("n")) {
      const newTop = clamp(
        boxStart.top + dy,
        0,
        boxStart.top + boxStart.height - MIN_CROP_SIZE
      );
      height = boxStart.height - (newTop - boxStart.top);
      top = newTop;
    } else if (dragMode.includes("s")) {
      height = clamp(boxStart.height + dy, MIN_CROP_SIZE, stageH - boxStart.top);
    }
  }

  setBoxRect({ left, top, width, height });
});

document.addEventListener("pointerup", () => {
  dragMode = null;
});

cropCancelBtn.addEventListener("click", () => {
  cropArea.hidden = true;
  clearError();
  previewArea.hidden = true;
});

cropConfirmBtn.addEventListener("click", () => {
  const scaleX = cropImg.naturalWidth / cropImg.clientWidth;
  const scaleY = cropImg.naturalHeight / cropImg.clientHeight;

  const nx = Math.round(boxRect.left * scaleX);
  const ny = Math.round(boxRect.top * scaleY);
  const nw = Math.round(boxRect.width * scaleX);
  const nh = Math.round(boxRect.height * scaleY);

  const canvas = document.createElement("canvas");
  canvas.width = nw;
  canvas.height = nh;
  const ctx = canvas.getContext("2d");
  ctx.drawImage(cropImg, nx, ny, nw, nh, 0, 0, nw, nh);

  canvas.toBlob((blob) => {
    cropArea.hidden = true;
    clearError();
    processBlob(blob);
  }, "image/png");
});
