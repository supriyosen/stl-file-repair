const MAX_PREVIEW_TRIANGLES = 14000;
const VERCEL_SAFE_UPLOAD_BYTES = 4 * 1024 * 1024;

const state = {
  file: null,
  preview: null,
  rotation: 0,
  animationId: null,
  progressTimer: null,
  progressValue: 0,
  apiBase: "",
  hasExternalBackend: false,
};

const fileInput = document.querySelector("#fileInput");
const dropzone = document.querySelector("#dropzone");
const fileName = document.querySelector("#fileName");
const analyzeBtn = document.querySelector("#analyzeBtn");
const repairBtn = document.querySelector("#repairBtn");
const downloadLink = document.querySelector("#downloadLink");
const beforeStats = document.querySelector("#beforeStats");
const afterStats = document.querySelector("#afterStats");
const beforeStatus = document.querySelector("#beforeStatus");
const afterStatus = document.querySelector("#afterStatus");
const successStatus = document.querySelector("#successStatus");
const statusBadge = document.querySelector("#statusBadge");
const stepsEl = document.querySelector("#steps");
const viewerTitle = document.querySelector("#viewerTitle");
const viewerFallback = document.querySelector("#viewerFallback");
const useMeshfix = document.querySelector("#useMeshfix");
const joinComponents = document.querySelector("#joinComponents");
const removeSmall = document.querySelector("#removeSmall");
const canvas = document.querySelector("#viewerCanvas");
const progressWrap = document.querySelector("#progressWrap");
const progressLabel = document.querySelector("#progressLabel");
const progressValue = document.querySelector("#progressValue");
const progressFill = document.querySelector("#progressFill");
const ctx = canvas.getContext("2d");

function setBusy(isBusy) {
  const blocked = isHostedUploadBlocked();
  analyzeBtn.disabled = isBusy || blocked;
  repairBtn.disabled = isBusy || blocked;
  if (isBusy) {
    statusBadge.classList.remove("good", "bad");
    statusBadge.textContent = "Working";
  } else if (statusBadge.textContent === "Working") {
    statusBadge.textContent = "Ready";
  }
}

function isHostedVercelApp() {
  return window.location.hostname.endsWith(".vercel.app");
}

function isHostedUploadBlocked() {
  return Boolean(
    state.file &&
      isHostedVercelApp() &&
      !state.hasExternalBackend &&
      state.file.size > VERCEL_SAFE_UPLOAD_BYTES,
  );
}

function hostedLimitMessage() {
  const sizeMb = (state.file.size / 1024 / 1024).toFixed(2);
  return `This Vercel-hosted repair backend can accept files up to 4 MB. ${state.file.name} is ${sizeMb} MB, so preview works here but Analyze/Repair must run in the local app or on a container backend.`;
}

function apiUrl(path) {
  return `${state.apiBase}${path}`;
}

function normalizeDownloadUrl(url) {
  if (!url || !state.apiBase || url.startsWith("http")) return url;
  return `${state.apiBase}${url}`;
}

function showHostedLimit() {
  analyzeBtn.disabled = true;
  repairBtn.disabled = true;
  progressWrap.classList.remove("hidden");
  progressLabel.textContent = "Cloud upload limit";
  progressValue.textContent = "4 MB max";
  progressFill.style.width = "100%";
  statusBadge.classList.remove("good");
  statusBadge.classList.add("bad");
  statusBadge.textContent = "Cloud limit";
  successStatus.classList.remove("good");
  successStatus.classList.add("bad");
  successStatus.textContent = "Local only";
  renderSteps([hostedLimitMessage()]);
}

function showProgress(label) {
  clearInterval(state.progressTimer);
  state.progressValue = 8;
  progressLabel.textContent = label;
  progressWrap.classList.remove("hidden");
  updateProgress(8);
  state.progressTimer = setInterval(() => {
    const next = state.progressValue + Math.max(1, Math.round((92 - state.progressValue) * 0.08));
    updateProgress(Math.min(next, 92));
  }, 260);
}

function updateProgress(value) {
  state.progressValue = value;
  progressValue.textContent = `${Math.round(value)}%`;
  progressFill.style.width = `${value}%`;
}

function finishProgress(label) {
  clearInterval(state.progressTimer);
  progressLabel.textContent = label;
  updateProgress(100);
  setTimeout(() => {
    progressWrap.classList.add("hidden");
    updateProgress(0);
  }, 650);
}

function failProgress(label) {
  clearInterval(state.progressTimer);
  progressLabel.textContent = label;
  progressValue.textContent = "Error";
  progressFill.style.width = "100%";
}

function setBadge(el, ok, waitingText = "Waiting") {
  el.classList.remove("good", "bad");
  if (ok === null) {
    el.textContent = waitingText;
    return;
  }
  el.textContent = ok ? "Clean" : "Issues";
  el.classList.add(ok ? "good" : "bad");
}

function formatNumber(value) {
  if (value === null || value === undefined) return "n/a";
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (Array.isArray(value)) return value.map((item) => Number(item).toFixed(3)).join(" x ");
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(3);
  return String(value);
}

function renderStats(target, report) {
  target.innerHTML = "";
  if (!report) return;
  const rows = [
    ["Size, mm", report.size_mm],
    ["Volume, mm3", report.volume_mm3],
    ["Triangles", report.triangles],
    ["Vertices", report.vertices],
    ["Watertight", report.watertight],
    ["Non-manifold edges", report.non_manifold_edges],
    ["Boundary edges", report.boundary_edges],
    ["Overused edges", report.overused_edges],
    ["Duplicate triangles", report.duplicate_faces],
    ["Degenerate triangles", report.degenerate_faces],
    ["Components", report.components],
  ];

  for (const [label, value] of rows) {
    const row = document.createElement("div");
    row.className = "stat";
    row.innerHTML = `<span>${label}</span><strong>${formatNumber(value)}</strong>`;
    target.append(row);
  }
}

function renderSteps(steps = []) {
  stepsEl.innerHTML = "";
  for (const step of steps) {
    const item = document.createElement("li");
    item.textContent = step;
    stepsEl.append(item);
  }
}

function cleanReport(report) {
  return report.watertight && report.non_manifold_edges === 0;
}

function applyReport(payload) {
  const report = payload.report;
  renderStats(beforeStats, report.before ?? report);
  renderStats(afterStats, report.after);
  setBadge(beforeStatus, cleanReport(report.before ?? report));
  setBadge(afterStatus, report.after ? cleanReport(report.after) : null);
  renderSteps(report.steps);

  successStatus.classList.remove("good", "bad");
  statusBadge.classList.remove("good", "bad");
  if (report.success === undefined) {
    successStatus.textContent = "Analyzed";
    statusBadge.textContent = "Analyzed";
    statusBadge.classList.add("good");
  } else {
    successStatus.textContent = report.success ? "Printable" : "Review";
    successStatus.classList.add(report.success ? "good" : "bad");
    statusBadge.textContent = report.success ? "Clean" : "Review";
    statusBadge.classList.add(report.success ? "good" : "bad");
  }
}

function formData() {
  if (!state.file) throw new Error("Choose a mesh file first.");
  const data = new FormData();
  data.append("file", state.file);
  data.append("use_meshfix", useMeshfix.checked ? "true" : "false");
  data.append("join_components", joinComponents.checked ? "true" : "false");
  data.append("remove_small_components", removeSmall.checked ? "true" : "false");
  return data;
}

async function postMesh(url, label) {
  if (isHostedUploadBlocked()) {
    showHostedLimit();
    return;
  }
  setBusy(true);
  showProgress(label);
  downloadLink.classList.add("hidden");
  try {
    const response = await fetch(apiUrl(url), { method: "POST", body: formData() });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "Repair failed.");
    applyReport(payload);
    if (payload.download_url) {
      downloadLink.href = normalizeDownloadUrl(payload.download_url);
      downloadLink.classList.remove("hidden");
    }
    finishProgress(url.includes("repair") ? "Repair complete" : "Analysis complete");
  } catch (error) {
    statusBadge.textContent = "Error";
    statusBadge.classList.add("bad");
    renderSteps([error.message]);
    failProgress("Could not complete");
  } finally {
    setBusy(false);
  }
}

function chooseFile(file) {
  if (!file) return;
  state.file = file;
  fileName.textContent = `${file.name} (${(file.size / 1024 / 1024).toFixed(2)} MB)`;
  viewerTitle.textContent = file.name;
  statusBadge.classList.remove("good", "bad");
  statusBadge.textContent = "Loading";
  downloadLink.classList.add("hidden");
  setBadge(beforeStatus, null);
  setBadge(afterStatus, null);
  renderStats(beforeStats, null);
  renderStats(afterStats, null);
  renderSteps([]);
  successStatus.classList.remove("good", "bad");
  successStatus.textContent = "Not run";
  analyzeBtn.disabled = false;
  repairBtn.disabled = false;
  progressWrap.classList.add("hidden");
  if (isHostedUploadBlocked()) {
    showHostedLimit();
  }
  previewFile(file);
}

dropzone.addEventListener("dragover", (event) => {
  event.preventDefault();
  dropzone.classList.add("dragging");
});

dropzone.addEventListener("dragleave", () => dropzone.classList.remove("dragging"));

dropzone.addEventListener("drop", (event) => {
  event.preventDefault();
  dropzone.classList.remove("dragging");
  chooseFile(event.dataTransfer.files[0]);
});

fileInput.addEventListener("change", () => chooseFile(fileInput.files[0]));
analyzeBtn.addEventListener("click", () => postMesh("/api/analyze", "Analyzing mesh"));
repairBtn.addEventListener("click", () => postMesh("/api/repair", "Repairing mesh"));
window.addEventListener("resize", renderPreview);
window.addEventListener("DOMContentLoaded", initializeApp);

async function initializeApp() {
  await loadRuntimeConfig();
  loadSamplePreview();
}

async function loadRuntimeConfig() {
  try {
    const response = await fetch("/api/config", { cache: "no-store" });
    if (!response.ok) return;
    const config = await response.json();
    if (config.external_repair_api_url) {
      state.apiBase = config.external_repair_api_url.replace(/\/$/, "");
      state.hasExternalBackend = true;
    }
  } catch {
    state.apiBase = "";
    state.hasExternalBackend = false;
  }
}

function isBinaryStl(buffer) {
  if (buffer.byteLength < 84) return false;
  const view = new DataView(buffer);
  const faceCount = view.getUint32(80, true);
  return 84 + faceCount * 50 === buffer.byteLength;
}

function parseBinaryStl(buffer) {
  const view = new DataView(buffer);
  const faceCount = view.getUint32(80, true);
  const stride = Math.max(1, Math.ceil(faceCount / MAX_PREVIEW_TRIANGLES));
  const triangles = [];
  const bounds = {
    minX: Infinity,
    minY: Infinity,
    minZ: Infinity,
    maxX: -Infinity,
    maxY: -Infinity,
    maxZ: -Infinity,
  };

  for (let face = 0; face < faceCount; face += stride) {
    const offset = 84 + face * 50;
    const triangle = [];
    for (let vertex = 0; vertex < 3; vertex += 1) {
      const cursor = offset + 12 + vertex * 12;
      const point = {
        x: view.getFloat32(cursor, true),
        y: view.getFloat32(cursor + 4, true),
        z: view.getFloat32(cursor + 8, true),
      };
      bounds.minX = Math.min(bounds.minX, point.x);
      bounds.minY = Math.min(bounds.minY, point.y);
      bounds.minZ = Math.min(bounds.minZ, point.z);
      bounds.maxX = Math.max(bounds.maxX, point.x);
      bounds.maxY = Math.max(bounds.maxY, point.y);
      bounds.maxZ = Math.max(bounds.maxZ, point.z);
      triangle.push(point);
    }
    triangles.push(triangle);
  }
  return { triangles, bounds, originalTriangles: faceCount };
}

function parseAsciiStl(text) {
  const matches = text.matchAll(/vertex\s+([+-]?\d*\.?\d+(?:e[+-]?\d+)?)\s+([+-]?\d*\.?\d+(?:e[+-]?\d+)?)\s+([+-]?\d*\.?\d+(?:e[+-]?\d+)?)/gi);
  const points = [];
  const bounds = {
    minX: Infinity,
    minY: Infinity,
    minZ: Infinity,
    maxX: -Infinity,
    maxY: -Infinity,
    maxZ: -Infinity,
  };

  for (const match of matches) {
    const point = { x: Number(match[1]), y: Number(match[2]), z: Number(match[3]) };
    if (!Number.isFinite(point.x) || !Number.isFinite(point.y) || !Number.isFinite(point.z)) continue;
    points.push(point);
    bounds.minX = Math.min(bounds.minX, point.x);
    bounds.minY = Math.min(bounds.minY, point.y);
    bounds.minZ = Math.min(bounds.minZ, point.z);
    bounds.maxX = Math.max(bounds.maxX, point.x);
    bounds.maxY = Math.max(bounds.maxY, point.y);
    bounds.maxZ = Math.max(bounds.maxZ, point.z);
  }

  const totalTriangles = Math.floor(points.length / 3);
  const stride = Math.max(1, Math.ceil(totalTriangles / MAX_PREVIEW_TRIANGLES));
  const triangles = [];
  for (let face = 0; face < totalTriangles; face += stride) {
    triangles.push([points[face * 3], points[face * 3 + 1], points[face * 3 + 2]]);
  }
  return { triangles, bounds, originalTriangles: totalTriangles };
}

function normalizePreview(parsed) {
  const { bounds } = parsed;
  if (!parsed.triangles.length || !Number.isFinite(bounds.minX)) {
    throw new Error("No previewable triangles found.");
  }

  const center = {
    x: (bounds.minX + bounds.maxX) / 2,
    y: (bounds.minY + bounds.maxY) / 2,
    z: (bounds.minZ + bounds.maxZ) / 2,
  };
  const size = Math.max(bounds.maxX - bounds.minX, bounds.maxY - bounds.minY, bounds.maxZ - bounds.minZ) || 1;
  const triangles = parsed.triangles.map((triangle) =>
    triangle.map((point) => ({
      x: (point.x - center.x) / size,
      y: (point.y - center.y) / size,
      z: (point.z - center.z) / size,
    })),
  );

  return { triangles, originalTriangles: parsed.originalTriangles };
}

async function previewFile(file) {
  if (!file.name.toLowerCase().endsWith(".stl")) {
    viewerFallback.textContent = "Preview supports STL files. Repair still supports STL, OBJ, and PLY.";
    if (!isHostedUploadBlocked()) statusBadge.textContent = "Ready";
    clearCanvas();
    return;
  }

  viewerFallback.textContent = "Loading local preview...";
  await new Promise((resolve) => setTimeout(resolve, 40));

  try {
    const buffer = await file.arrayBuffer();
    const parsed = isBinaryStl(buffer)
      ? parseBinaryStl(buffer)
      : parseAsciiStl(new TextDecoder("utf-8").decode(buffer));
    state.preview = normalizePreview(parsed);
    viewerFallback.textContent =
      state.preview.originalTriangles > state.preview.triangles.length
        ? `Previewing ${state.preview.triangles.length.toLocaleString()} of ${state.preview.originalTriangles.toLocaleString()} triangles.`
        : "";
    if (!isHostedUploadBlocked()) statusBadge.textContent = "Ready";
    startPreview();
  } catch (error) {
    state.preview = null;
    statusBadge.textContent = "Preview";
    viewerFallback.textContent = `Preview could not parse this STL: ${error.message}`;
    clearCanvas();
  }
}

async function loadSamplePreview() {
  const sample = new URLSearchParams(window.location.search).get("sample");
  if (!sample) return;
  try {
    const response = await fetch(sample);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const blob = await response.blob();
    const name = sample.split("/").pop() || "sample.stl";
    const file = new File([blob], name, { type: "model/stl" });
    chooseFile(file);
  } catch (error) {
    viewerFallback.textContent = `Sample preview could not load: ${error.message}`;
  }
}

function resizeCanvas() {
  const rect = canvas.getBoundingClientRect();
  const pixelRatio = Math.min(window.devicePixelRatio || 1, 2);
  const width = Math.max(1, Math.floor(rect.width * pixelRatio));
  const height = Math.max(1, Math.floor(rect.height * pixelRatio));
  if (canvas.width !== width || canvas.height !== height) {
    canvas.width = width;
    canvas.height = height;
  }
  ctx.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
  return { width: rect.width, height: rect.height };
}

function clearCanvas() {
  const { width, height } = resizeCanvas();
  ctx.clearRect(0, 0, width, height);
}

function rotatePoint(point, angle) {
  const cosTurntable = Math.cos(angle);
  const sinTurntable = Math.sin(angle);

  const x = point.x * cosTurntable - point.y * sinTurntable;
  const depth = point.x * sinTurntable + point.y * cosTurntable;

  return { x, y: point.z, z: depth };
}

function triangleNormal(a, b, c) {
  const ux = b.x - a.x;
  const uy = b.y - a.y;
  const uz = b.z - a.z;
  const vx = c.x - a.x;
  const vy = c.y - a.y;
  const vz = c.z - a.z;
  return {
    x: uy * vz - uz * vy,
    y: uz * vx - ux * vz,
    z: ux * vy - uy * vx,
  };
}

function renderPreview() {
  const { width, height } = resizeCanvas();
  ctx.clearRect(0, 0, width, height);
  if (!state.preview) return;

  const scale = Math.min(width, height) * 0.74;
  const centerX = width / 2;
  const centerY = height / 2 + 18;
  const faces = [];

  for (const triangle of state.preview.triangles) {
    const rotated = triangle.map((point) => rotatePoint(point, state.rotation));
    const normal = triangleNormal(rotated[0], rotated[1], rotated[2]);
    if (normal.z <= -0.0001) continue;
    const projected = rotated.map((point) => {
      const depth = 2.8 + point.z;
      const perspective = 1.7 / depth;
      return {
        x: centerX + point.x * scale * perspective,
        y: centerY - point.y * scale * perspective,
        z: point.z,
      };
    });
    faces.push({
      points: projected,
      depth: (rotated[0].z + rotated[1].z + rotated[2].z) / 3,
      shade: Math.max(0.22, Math.min(1, 0.38 + normal.z * 2.4)),
    });
  }

  faces.sort((a, b) => a.depth - b.depth);
  ctx.lineWidth = 0.45;
  for (const face of faces) {
    const [a, b, c] = face.points;
    const gold = Math.round(120 + face.shade * 95);
    const green = Math.round(120 + face.shade * 70);
    ctx.beginPath();
    ctx.moveTo(a.x, a.y);
    ctx.lineTo(b.x, b.y);
    ctx.lineTo(c.x, c.y);
    ctx.closePath();
    ctx.fillStyle = `rgb(${gold}, ${green}, ${Math.round(70 + face.shade * 42)})`;
    ctx.strokeStyle = "rgba(255, 236, 180, 0.08)";
    ctx.fill();
    ctx.stroke();
  }
}

function startPreview() {
  if (state.animationId) cancelAnimationFrame(state.animationId);
  const animate = () => {
    state.rotation += 0.008;
    renderPreview();
    state.animationId = requestAnimationFrame(animate);
  };
  animate();
}
