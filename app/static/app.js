const els = {
  sourceDir: document.getElementById("sourceDir"),
  compId: document.getElementById("compId"),
  title: document.getElementById("title"),
  outputDir: document.getElementById("outputDir"),
  longformImage: document.getElementById("longformImage"),
  shortsImage: document.getElementById("shortsImage"),
  transitionSeconds: document.getElementById("transitionSeconds"),
  transitionValue: document.getElementById("transitionValue"),
  transitionPreview: document.getElementById("transitionPreview"),
  silenceTrim: document.getElementById("silenceTrim"),
  droneScan: document.getElementById("droneScan"),
  placeholderImages: document.getElementById("placeholderImages"),
  moveSourcesAfterRender: document.getElementById("moveSourcesAfterRender"),
  loadDefaultsBtn: document.getElementById("loadDefaultsBtn"),
  scanBtn: document.getElementById("scanBtn"),
  renderBtn: document.getElementById("renderBtn"),
  statusBadge: document.getElementById("statusBadge"),
  summaryLine: document.getElementById("summaryLine"),
  finalOutputLine: document.getElementById("finalOutputLine"),
  imageRoleLine: document.getElementById("imageRoleLine"),
  blockers: document.getElementById("blockers"),
  warnings: document.getElementById("warnings"),
  tracksBody: document.getElementById("tracksBody"),
  jobStatus: document.getElementById("jobStatus"),
  jobLog: document.getElementById("jobLog"),
  result: document.getElementById("result"),
  pickerOverlay: document.getElementById("pickerOverlay"),
  pickerTitle: document.getElementById("pickerTitle"),
  pickerPath: document.getElementById("pickerPath"),
  pickerParentBtn: document.getElementById("pickerParentBtn"),
  pickerSelectBtn: document.getElementById("pickerSelectBtn"),
  pickerCloseBtn: document.getElementById("pickerCloseBtn"),
  pickerEntries: document.getElementById("pickerEntries"),
  pickerError: document.getElementById("pickerError"),
  mkdirBox: document.getElementById("mkdirBox"),
  newFolderName: document.getElementById("newFolderName"),
  mkdirBtn: document.getElementById("mkdirBtn"),
};

const picker = {
  targetId: null,
  mode: "folder",
  canCreate: false,
  path: "",
  parent: null,
};

const autoImages = {
  sourceDir: "",
  longformImage: "",
  shortsImage: "",
};

let lastScanReady = false;
let currentTracks = [];
let draggedTrackPath = "";

function formPayload() {
  return {
    source_dir: els.sourceDir.value.trim(),
    comp_id: els.compId.value.trim(),
    title: els.title.value.trim(),
    output_dir: els.outputDir.value.trim(),
    longform_image: els.longformImage.value.trim(),
    shorts_image: els.shortsImage.value.trim(),
  };
}

function selectedTransitionMode() {
  return document.querySelector('input[name="transitionMode"]:checked')?.value || "smooth_crossfade";
}

function updateTransitionControl() {
  const mode = selectedTransitionMode();
  const seconds = Number(els.transitionSeconds.value);
  const displaySeconds = mode === "no_crossfade" ? 0 : seconds;
  els.transitionValue.textContent = `${displaySeconds.toFixed(1)}s`;
  els.transitionSeconds.disabled = mode === "no_crossfade";
  els.transitionPreview.dataset.mode = mode;
  const width = mode === "smooth_crossfade" ? Math.max(6, 8 + seconds * 7) : mode === "micro_fade" ? Math.max(3, seconds * 5) : 0;
  els.transitionPreview.style.setProperty("--overlap-width", `${Math.min(width, 28)}%`);
}

async function api(path, body) {
  const response = await fetch(path, {
    method: body ? "POST" : "GET",
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.detail || response.statusText);
  }
  return data;
}

async function apiGet(path, params = {}) {
  const url = new URL(path, window.location.origin);
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") {
      url.searchParams.set(key, value);
    }
  });
  const response = await fetch(url);
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.detail || response.statusText);
  }
  return data;
}

function setStatus(text) {
  els.statusBadge.textContent = text;
}

function setRenderReady(ready) {
  lastScanReady = ready;
  els.renderBtn.disabled = !ready;
}

function invalidateDryRun(reason = "Dry-Run needed") {
  setRenderReady(false);
  if (els.summaryLine.textContent !== "Noch nicht gescannt") {
    setStatus(reason);
  }
}

function showNotice(el, items) {
  if (!items || !items.length) {
    el.style.display = "none";
    el.textContent = "";
    return;
  }
  el.style.display = "block";
  el.innerHTML = items.map((item) => `<div>${escapeHtml(item)}</div>`).join("");
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function renderScan(scan) {
  els.summaryLine.textContent = `${scan.summary.included_count}/${scan.summary.wav_count} WAVs | ${scan.summary.included_duration_label} | ${scan.summary.image_count} Bilder`;
  els.finalOutputLine.innerHTML = `<span>Final output:</span><code>${escapeHtml(scan.output_dir)}</code>`;
  renderImageRoles(scan.image_roles);
  showNotice(els.blockers, scan.blockers);
  showNotice(els.warnings, scan.warnings);
  if (scan.image_roles?.longform?.assignment === "auto") {
    els.longformImage.value = scan.longform_image;
    autoImages.longformImage = scan.longform_image;
    autoImages.sourceDir = scan.source_dir;
  } else if (!els.longformImage.value && scan.longform_image) {
    els.longformImage.value = scan.longform_image;
  }
  if (scan.image_roles?.shorts?.assignment === "auto") {
    els.shortsImage.value = scan.shorts_image;
    autoImages.shortsImage = scan.shorts_image;
    autoImages.sourceDir = scan.source_dir;
  } else if (!els.shortsImage.value && scan.shorts_image) {
    els.shortsImage.value = scan.shorts_image;
  }
  currentTracks = scan.tracks || [];
  renderTrackRows();
}

function renderTrackRows() {
  els.tracksBody.innerHTML = currentTracks
    .map((track, index) => {
      const reason = track.reasons?.length ? ` (${track.reasons.join(", ")})` : "";
      return `<tr draggable="true" data-path="${escapeHtml(track.path)}">
        <td class="drag-col"><span class="drag-handle" title="Track ziehen" aria-hidden="true">&#8942;&#8942;</span></td>
        <td>${index + 1}</td>
        <td>${escapeHtml(track.title)}</td>
        <td>${track.duration_label}</td>
        <td class="status-${track.status}">${track.status}${escapeHtml(reason)}</td>
      </tr>`;
    })
    .join("");
}

function renderImageRoles(imageRoles) {
  const longform = imageRoles?.longform;
  const shorts = imageRoles?.shorts;
  if (!longform && !shorts) {
    els.imageRoleLine.innerHTML = "";
    return;
  }
  els.imageRoleLine.innerHTML = `
    <code>16:9 ${roleLabel(longform)}${imageName(longform)}</code>
    <code>9:16 ${roleLabel(shorts)}${imageName(shorts)}</code>
  `;
}

function roleLabel(role) {
  if (!role) return "nicht gefunden";
  return role.assignment === "manual" ? "manuell" : "auto";
}

function imageName(role) {
  if (!role) return "";
  const size = role.width && role.height ? ` · ${role.width}x${role.height}` : "";
  return ` · ${escapeHtml(role.name)}${size}`;
}

async function loadDefaults() {
  setStatus("Loading");
  setRenderReady(false);
  const defaults = await api("/api/defaults");
  els.sourceDir.value = defaults.source_dir;
  els.compId.value = defaults.comp_id;
  els.title.value = defaults.title;
  els.outputDir.value = defaults.output_dir;
  setStatus("Idle");
}

async function scan() {
  setStatus("Scanning");
  els.scanBtn.disabled = true;
  setRenderReady(false);
  try {
    const data = await api("/api/scan", { ...formPayload(), compute_hashes: true });
    renderScan(data);
    setRenderReady(data.render_ready);
    setStatus(data.render_ready ? "Ready" : "Needs input");
  } catch (error) {
    setStatus("Error");
    showNotice(els.blockers, [error.message]);
  } finally {
    els.scanBtn.disabled = false;
  }
}

async function render() {
  if (!lastScanReady) {
    showNotice(els.blockers, ["Bitte zuerst Dry-Run ohne Probleme ausführen."]);
    setStatus("Dry-Run needed");
    return;
  }
  setStatus("Rendering");
  els.renderBtn.disabled = true;
  els.result.innerHTML = "";
  els.jobLog.textContent = "";
  const body = {
    ...formPayload(),
    silence_trim: els.silenceTrim.checked,
    drone_scan: els.droneScan.checked,
    use_placeholder_images: els.placeholderImages.checked,
    transition_mode: selectedTransitionMode(),
    transition_seconds: Number(els.transitionSeconds.value),
    move_sources_after_render: els.moveSourcesAfterRender.checked,
    track_order: currentTracks.filter((track) => track.status === "included").map((track) => track.path),
    short_count: 5,
    short_duration: 30,
  };
  try {
    const started = await api("/api/render", body);
    pollJob(started.job_id);
  } catch (error) {
    setStatus("Error");
    els.jobStatus.textContent = error.message;
    els.renderBtn.disabled = false;
  }
}

async function pollJob(jobId) {
  const job = await api(`/api/jobs/${jobId}`);
  els.jobStatus.textContent = job.status;
  els.jobLog.textContent = (job.messages || []).join("\n");
  if (job.status === "queued" || job.status === "running") {
    window.setTimeout(() => pollJob(jobId), 1600);
    return;
  }
  els.renderBtn.disabled = false;
  if (job.status === "error") {
    setStatus("Error");
    els.result.innerHTML = `<div class="notice" style="display:block">${escapeHtml(job.error)}</div>`;
    return;
  }
  setStatus("Done");
  const result = job.result;
  els.result.innerHTML = `
    <strong>Fertig</strong>
    <code>Output: ${escapeHtml(result.output_dir)}</code>
    <code>Master WAV: ${escapeHtml(result.master_wav)}</code>
    <code>Longform MP4: ${escapeHtml(result.longform_mp4)}</code>
    <code>Shorts: ${result.shorts.length}</code>
    <code>Dauer: ${escapeHtml(result.master_duration_label)}</code>
    <code>Übergang: ${escapeHtml(result.transition.mode)} / ${result.transition.crossfade_seconds.toFixed(1)}s Crossfade</code>
    ${result.visual_package ? `<code>Bilder: ${result.visual_package.moved_visuals} Dateien nach ${escapeHtml(result.visual_package.visuals_dir)}</code>` : ""}
    ${result.source_package ? `<code>Originals: ${result.source_package.moved_sources} WAVs nach ${escapeHtml(result.source_package.sources_dir)}</code>` : ""}
  `;
}

function pickerStartPath(targetId) {
  const current = els[targetId].value.trim();
  if (current) return current;
  if (targetId === "sourceDir") return els.sourceDir.value.trim();
  if (targetId === "outputDir") return els.outputDir.value.trim();
  return els.sourceDir.value.trim();
}

async function openPicker(button) {
  picker.targetId = button.dataset.target;
  picker.mode = button.dataset.mode || "folder";
  picker.canCreate = button.dataset.create === "true";
  els.pickerTitle.textContent = picker.mode === "image" ? "Bild auswählen" : "Ordner auswählen";
  els.mkdirBox.style.display = picker.canCreate ? "flex" : "none";
  els.pickerSelectBtn.style.display = picker.mode === "folder" ? "inline-flex" : "none";
  els.newFolderName.value = "";
  els.pickerOverlay.hidden = false;
  await loadPicker(pickerStartPath(picker.targetId));
}

async function chooseNativePath(button) {
  const targetId = button.dataset.target;
  const mode = button.dataset.mode || "folder";
  const currentPath = els[targetId].value.trim() || pickerStartPath(targetId);
  const prompt =
    targetId === "sourceDir"
      ? "Source Folder auswählen"
      : targetId === "outputDir"
        ? "Output Folder auswählen oder neu anlegen"
        : "Bild auswählen";
  try {
    setStatus("Browse");
    const result = await api("/api/dialog/choose", {
      current_path: currentPath,
      mode,
      prompt,
    });
    if (result.path) {
      els[targetId].value = result.path;
      invalidateDryRun();
      if (targetId === "longformImage" || targetId === "shortsImage") {
        autoImages[targetId] = "";
      }
      if (targetId === "sourceDir") {
        clearAutoImagesForSourceChange(result.path);
        const last = result.path.split("/").filter(Boolean).pop();
        if (last && !els.title.value.trim()) els.title.value = last;
      }
      setStatus("Idle");
      return;
    }
    setStatus("Idle");
  } catch (error) {
    setStatus("Fallback");
    showNotice(els.warnings, [`Native Finder dialog nicht verfügbar: ${error.message}. Interner Browser geöffnet.`]);
    await openPicker(button);
  }
}

async function loadPicker(path) {
  try {
    showNotice(els.pickerError, []);
    els.pickerEntries.innerHTML = '<div class="picker-entry"><span class="picker-kind">Load</span><span class="picker-name">Loading...</span></div>';
    const data = await apiGet("/api/fs/list", { path, mode: picker.mode });
    picker.path = data.path;
    picker.parent = data.parent;
    els.pickerPath.textContent = data.path;
    els.pickerParentBtn.disabled = !data.parent;
    els.pickerEntries.innerHTML = data.entries.length
      ? data.entries.map((entry) => pickerEntryHtml(entry)).join("")
      : '<div class="picker-entry"><span class="picker-kind">Empty</span><span class="picker-name">Keine passenden Einträge</span></div>';
  } catch (error) {
    els.pickerEntries.innerHTML = "";
    showNotice(els.pickerError, [error.message]);
  }
}

function pickerEntryHtml(entry) {
  return `<button type="button" class="picker-entry" data-kind="${escapeHtml(entry.kind)}" data-path="${escapeHtml(entry.path)}">
    <span class="picker-kind">${entry.kind === "folder" ? "Folder" : "Image"}</span>
    <span class="picker-name">${escapeHtml(entry.name)}</span>
  </button>`;
}

function closePicker() {
  els.pickerOverlay.hidden = true;
}

function selectPickerPath(path) {
  if (!picker.targetId) return;
  els[picker.targetId].value = path;
  invalidateDryRun();
  closePicker();
  if (picker.targetId === "sourceDir") {
    const last = path.split("/").filter(Boolean).pop();
    if (last && !els.title.value.trim()) els.title.value = last;
  }
}

async function createFolder() {
  const name = els.newFolderName.value.trim();
  if (!name) {
    showNotice(els.pickerError, ["Bitte Ordnernamen eingeben"]);
    return;
  }
  try {
    const data = await api("/api/fs/mkdir", { parent: picker.path, name });
    await loadPicker(data.path);
    if (picker.targetId === "outputDir") {
      els.outputDir.value = data.path;
      invalidateDryRun();
    }
    els.newFolderName.value = "";
  } catch (error) {
    showNotice(els.pickerError, [error.message]);
  }
}

els.loadDefaultsBtn.addEventListener("click", loadDefaults);
els.scanBtn.addEventListener("click", scan);
els.renderBtn.addEventListener("click", render);
["sourceDir", "compId", "title", "outputDir", "longformImage", "shortsImage"].forEach((id) => {
  els[id].addEventListener("input", () => invalidateDryRun());
});
["silenceTrim", "droneScan", "placeholderImages", "moveSourcesAfterRender"].forEach((id) => {
  els[id].addEventListener("change", () => invalidateDryRun());
});
els.sourceDir.addEventListener("input", () => {
  clearAutoImagesForSourceChange(els.sourceDir.value.trim());
});
els.transitionSeconds.addEventListener("input", () => {
  updateTransitionControl();
  invalidateDryRun();
});
document.querySelectorAll('input[name="transitionMode"]').forEach((input) => {
  input.addEventListener("change", () => {
    updateTransitionControl();
    invalidateDryRun();
  });
});
document.querySelectorAll(".browse-btn").forEach((button) => {
  button.addEventListener("click", () => chooseNativePath(button));
});
els.pickerCloseBtn.addEventListener("click", closePicker);
els.pickerParentBtn.addEventListener("click", () => {
  if (picker.parent) loadPicker(picker.parent);
});
els.pickerSelectBtn.addEventListener("click", () => selectPickerPath(picker.path));
els.mkdirBtn.addEventListener("click", createFolder);
els.newFolderName.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    createFolder();
  }
});
els.pickerEntries.addEventListener("click", (event) => {
  const entry = event.target.closest(".picker-entry");
  if (!entry || !entry.dataset.path || entry.dataset.kind === "Empty") return;
  if (entry.dataset.kind === "folder") {
    loadPicker(entry.dataset.path);
    return;
  }
  selectPickerPath(entry.dataset.path);
});
els.pickerOverlay.addEventListener("click", (event) => {
  if (event.target === els.pickerOverlay) closePicker();
});

els.tracksBody.addEventListener("dragstart", (event) => {
  const row = event.target.closest("tr[data-path]");
  if (!row) return;
  draggedTrackPath = row.dataset.path;
  event.dataTransfer.effectAllowed = "move";
  event.dataTransfer.setData("text/plain", draggedTrackPath);
  row.classList.add("dragging");
});

els.tracksBody.addEventListener("dragover", (event) => {
  const row = event.target.closest("tr[data-path]");
  if (!row || !draggedTrackPath || row.dataset.path === draggedTrackPath) return;
  event.preventDefault();
  clearDropState();
  const rect = row.getBoundingClientRect();
  row.classList.add(event.clientY > rect.top + rect.height / 2 ? "drop-after" : "drop-before");
});

els.tracksBody.addEventListener("dragleave", (event) => {
  if (!els.tracksBody.contains(event.relatedTarget)) {
    clearDropState();
  }
});

els.tracksBody.addEventListener("drop", (event) => {
  const row = event.target.closest("tr[data-path]");
  if (!row || !draggedTrackPath || row.dataset.path === draggedTrackPath) return;
  event.preventDefault();
  const rect = row.getBoundingClientRect();
  moveTrack(draggedTrackPath, row.dataset.path, event.clientY > rect.top + rect.height / 2);
  draggedTrackPath = "";
  setStatus(lastScanReady ? "Ready" : "Dry-Run needed");
});

els.tracksBody.addEventListener("dragend", () => {
  draggedTrackPath = "";
  clearDropState();
});

updateTransitionControl();
setRenderReady(false);

loadDefaults().catch((error) => {
  setStatus("Error");
  showNotice(els.blockers, [error.message]);
});

function clearAutoImagesForSourceChange(currentSource) {
  if (autoImages.sourceDir && currentSource !== autoImages.sourceDir) {
    if (els.longformImage.value === autoImages.longformImage) els.longformImage.value = "";
    if (els.shortsImage.value === autoImages.shortsImage) els.shortsImage.value = "";
    autoImages.sourceDir = "";
    autoImages.longformImage = "";
    autoImages.shortsImage = "";
  }
}

function clearDropState() {
  els.tracksBody.querySelectorAll(".dragging, .drop-before, .drop-after").forEach((row) => {
    row.classList.remove("dragging", "drop-before", "drop-after");
  });
}

function moveTrack(sourcePath, targetPath, insertAfter) {
  const sourceIndex = currentTracks.findIndex((track) => track.path === sourcePath);
  const targetIndex = currentTracks.findIndex((track) => track.path === targetPath);
  if (sourceIndex < 0 || targetIndex < 0) return;

  const [track] = currentTracks.splice(sourceIndex, 1);
  const adjustedTargetIndex = currentTracks.findIndex((item) => item.path === targetPath);
  currentTracks.splice(adjustedTargetIndex + (insertAfter ? 1 : 0), 0, track);
  renderTrackRows();
}
