"use strict";

/* ----------------------------------------------------------------- utils -- */
const $ = (id) => document.getElementById(id);
const el = {};
[
  "panelToggle", "refreshHistoryBtn", "connPill", "protoTag", "modelTag", "historyMetricNum",
  "runStats", "shownCount", "okCount", "failCount", "selectToggle", "selectToggleLabel",
  "downloadShownBtn", "downloadLabel", "historyGrid",
  "composer", "composerRefs", "uploadBtn", "referenceInput", "promptInput", "paramsPopover",
  "countSeg", "ratioSeg", "summaryChip", "summaryChipText", "sendBtn", "footProvider", "charCount",
  "config", "shell", "protocolSelect", "protocolInfo", "baseUrlSelect", "baseUrlInput", "baseUrlLabel", "apiKeyInput",
  "rememberKey", "fetchModelsBtn", "keyStatus", "modelSearch", "modelList",
  "countInput", "concurrencyInput", "sizeInput", "aspectRatioInput", "imageSizeInput",
  "qualityInput", "formatInput", "seedInput", "timeoutInput", "temperatureInput", "maxTokensInput",
  "retryInput", "negativePromptInput",
  "progressCard", "pcMsg", "pcPct", "pcFill", "pcSubs", "pcSpin", "overlay", "toast", "toastText",
].forEach((id) => (el[id] = $(id)));

const LS = {
  apiKey: "imageStudio.apiKey",
  baseSelect: "imageStudio.baseSelect",
  baseCustom: "imageStudio.baseCustom",
  remember: "imageStudio.remember",
  selectedModel: "imageStudio.selectedModel",
};

const RATIO_TO_SIZE = { "1:1": "1024x1024", "9:16": "1024x1792", "16:9": "1792x1024", "2:3": "1024x1536", "3:2": "1536x1024" };
const SIZE_TO_RATIO = { "1024x1024": "1:1", "1024x1792": "9:16", "1792x1024": "16:9", "1024x1536": "2:3", "1536x1024": "3:2" };

const PROTOCOL_INFO = {
  "openai-images": {
    title: "OpenAI Images",
    desc: "OpenAI 风格 /v1/images/generations，宽高比会转换为 size 参数。",
    caps: ["支持质量", "支持格式", "支持多张"],
  },
  "chat-completions": {
    title: "Chat Completions",
    desc: "Gemini / Nano Banana 风格 /v1/chat/completions，imageConfig 控制比例与分辨率。",
    caps: ["支持参考图", "支持比例", "支持分辨率"],
  },
};

const PROTOCOL_SHORT = { "openai-images": "OpenAI", "chat-completions": "Gemini" };

const state = {
  config: null,
  presets: [],
  catalog: [], // [{id, protocol, label, source}]
  selected: null, // {id, protocol}
  history: [],
  references: [],
  selectMode: false,
  selectedKeys: new Set(),
  pollTimer: null,
  modelStatus: null, // {ok, count, time} | {error}
};

function icon(id, cls = "icon") {
  return `<svg class="${cls}"><use href="#${id}" /></svg>`;
}
function esc(v) {
  return String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" }[c]));
}
function clampInt(v, fallback, min, max) {
  const n = Number.parseInt(v, 10);
  if (!Number.isFinite(n)) return fallback;
  return Math.max(min, Math.min(max, n));
}
function delay(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

let toastTimer;
function toast(message, kind = "ok") {
  el.toastText.textContent = message;
  el.toast.classList.toggle("bad", kind === "bad");
  el.toast.querySelector("use").setAttribute("href", kind === "bad" ? "#i-alert" : "#i-check");
  el.toast.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.toast.classList.remove("show"), 2600);
}

async function apiGet(path) {
  const res = await fetch(path);
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}
async function apiPost(path, body) {
  const res = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}
async function readError(res) {
  try {
    const d = await res.json();
    return d.detail || d.message || res.statusText;
  } catch {
    return res.statusText;
  }
}

/* ------------------------------------------------------------- connection -- */
function effectiveBaseUrl() {
  const custom = el.baseUrlInput.value.trim();
  if (custom) return custom;
  const sel = el.baseUrlSelect.value;
  return sel === "__custom__" ? "" : sel;
}

function syncBaseUrlField() {
  const isCustom = el.baseUrlSelect.value === "__custom__";
  el.baseUrlLabel.textContent = isCustom ? "自定义 API URL" : "备用服务地址（可选）";
  el.baseUrlInput.placeholder = isCustom ? "https://your-endpoint.com" : "留空则使用上面所选";
  el.baseUrlInput.classList.toggle("input-required", isCustom && !el.baseUrlInput.value.trim());
}

function hasKey() {
  return Boolean(el.apiKeyInput.value.trim()) || Boolean(state.config && state.config.api_key_present);
}

function updateConnPill() {
  const ok = hasKey();
  el.connPill.classList.toggle("warn", !ok);
  el.connPill.innerHTML = `<span class="dot"></span>${ok ? "已连接" : "未配置"}`;
}

/* ------------------------------------------------------------- protocol --- */
function currentProtocol() {
  return el.protocolSelect.value;
}

function renderProtocolInfo() {
  const info = PROTOCOL_INFO[currentProtocol()] || PROTOCOL_INFO["openai-images"];
  el.protocolInfo.innerHTML = `
    <div class="ic-title">${esc(info.title)}</div>
    <div class="ic-desc">${esc(info.desc)}</div>
    <div class="cap-row">${info.caps.map((c) => `<span class="cap">${icon("i-check", "icon icon-sm")}${esc(c)}</span>`).join("")}</div>`;
  document.querySelectorAll("[data-proto]").forEach((node) => {
    node.hidden = node.dataset.proto !== currentProtocol();
  });
}

/* --------------------------------------------------------------- models --- */
function buildPresetCards() {
  return state.presets.map((p) => ({ id: p.upstream_model, protocol: p.protocol, label: p.label, source: "preset" }));
}

function rebuildCatalog(upstream = []) {
  const seen = new Set();
  const cards = [];
  for (const c of [...buildPresetCards(), ...upstream]) {
    if (seen.has(c.id)) continue;
    seen.add(c.id);
    cards.push(c);
  }
  state.catalog = cards;
}

function selectModel(model, { remember = true } = {}) {
  state.selected = { id: model.id, protocol: model.protocol };
  el.protocolSelect.value = model.protocol;
  renderProtocolInfo();
  el.protoTag.textContent = (PROTOCOL_INFO[model.protocol] || {}).title || model.protocol;
  el.modelTag.textContent = model.id;
  if (remember) localStorage.setItem(LS.selectedModel, JSON.stringify(state.selected));
  renderModelList();
  updateSummary();
}

function renderModelList() {
  const q = el.modelSearch.value.trim().toLowerCase();
  const items = state.catalog.filter((m) => !q || m.id.toLowerCase().includes(q));
  if (items.length === 0) {
    el.modelList.innerHTML = q
      ? `<button class="model-empty" id="useCustomModel" type="button">使用 “${esc(el.modelSearch.value.trim())}” · ${esc((PROTOCOL_INFO[currentProtocol()] || {}).title || "")}</button>`
      : `<div class="model-empty">暂无模型，请先读取上游模型</div>`;
    const custom = $("useCustomModel");
    if (custom) custom.onclick = () => selectModel({ id: el.modelSearch.value.trim(), protocol: currentProtocol() });
    return;
  }
  el.modelList.innerHTML = items
    .map((m) => {
      const active = state.selected && state.selected.id === m.id;
      const proto = (PROTOCOL_INFO[m.protocol] || {}).title || m.protocol;
      const tag = m.source === "preset" ? "内置" : "上游";
      return `
        <button class="model-card ${active ? "active" : ""}" type="button" data-model-id="${esc(m.id)}" data-model-proto="${esc(m.protocol)}">
          <div class="mc-text">
            <div class="mc-id">${esc(m.id)}</div>
            <div class="mc-proto">${esc(proto)} · ${tag}</div>
          </div>
          ${icon("i-check", "icon mc-tick")}
        </button>`;
    })
    .join("");
}

async function fetchUpstreamModels() {
  const apiKey = el.apiKeyInput.value.trim();
  if (!apiKey && !(state.config && state.config.api_key_present)) {
    toast("请先填写 API Key", "bad");
    el.apiKeyInput.focus();
    return;
  }
  el.fetchModelsBtn.disabled = true;
  el.keyStatus.className = "key-status";
  el.keyStatus.innerHTML = `${icon("i-refresh", "icon")}<span>正在读取上游模型…</span>`;
  try {
    const data = await apiPost("/api/models/upstream", { api_key: apiKey || null, base_url: effectiveBaseUrl() || null });
    rebuildCatalog(data.image_models.map((m) => ({ ...m, source: "upstream" })));
    state.modelStatus = { ok: true, count: data.image_models.length, total: data.total, time: data.fetched_at };
    const time = new Date(data.fetched_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    el.keyStatus.className = "key-status ok";
    el.keyStatus.innerHTML = `${icon("i-check", "icon")}<span>API Key 有效 · ${data.image_models.length} 个图片模型 · ${esc(time)}</span>`;
    renderModelList();
    updateConnPill();
    toast(`读取到 ${data.image_models.length} 个图片模型`);
  } catch (error) {
    state.modelStatus = { error: error.message };
    el.keyStatus.className = "key-status bad";
    el.keyStatus.innerHTML = `${icon("i-alert", "icon")}<span>${esc(error.message)}</span>`;
    toast(error.message, "bad");
  } finally {
    el.fetchModelsBtn.disabled = false;
  }
}

/* ---------------------------------------------------------------- params --- */
function paramsFromForm() {
  const count = clampInt(el.countInput.value, 1, 1, 16);
  const concurrency = clampInt(el.concurrencyInput.value, 1, 1, Math.min(8, count));
  el.countInput.value = String(count);
  el.concurrencyInput.value = String(concurrency);
  return {
    count,
    concurrency,
    size: el.sizeInput.value,
    quality: el.qualityInput.value,
    output_format: el.formatInput.value,
    aspect_ratio: el.aspectRatioInput.value,
    image_size: el.imageSizeInput.value,
    resolution: el.imageSizeInput.value,
    seed: el.seedInput.value.trim(),
    negative_prompt: el.negativePromptInput.value.trim(),
    temperature: Number.parseFloat(el.temperatureInput.value || "0.8"),
    max_tokens: clampInt(el.maxTokensInput.value, 4096, 256, 32768),
    timeout: clampInt(el.timeoutInput.value, 180, 10, 1200),
    retry_limit: clampInt(el.retryInput.value, 1, 0, 5),
  };
}

function displayRatio(p) {
  return currentProtocol() === "chat-completions" ? p.aspect_ratio : SIZE_TO_RATIO[p.size] || "自定义";
}
function displayRes(p) {
  return currentProtocol() === "chat-completions" ? p.image_size : "1K";
}
function displayDims(p) {
  return currentProtocol() === "chat-completions" ? `${p.aspect_ratio} · ${p.image_size}` : p.size.replace("x", "×");
}

function updateSummary() {
  const p = paramsFromForm();
  el.summaryChipText.textContent = `${p.count} 张 · ${displayRatio(p)} · ${displayRes(p)}`;
  el.footProvider.textContent = `${PROTOCOL_SHORT[currentProtocol()] || "API"} · ${displayDims(p)}`;
  el.charCount.textContent = String(el.promptInput.value.trim().length);
  syncSegs(p);
}

function syncSegs(p) {
  el.countSeg.querySelectorAll("button").forEach((b) => b.classList.toggle("active", Number(b.dataset.count) === p.count));
  const ratio = displayRatio(p);
  el.ratioSeg.querySelectorAll("button").forEach((b) => b.classList.toggle("active", b.dataset.ratio === ratio));
}

function applyRatio(ratio) {
  if (RATIO_TO_SIZE[ratio]) el.sizeInput.value = RATIO_TO_SIZE[ratio];
  el.aspectRatioInput.value = ratio;
  updateSummary();
}

/* -------------------------------------------------------------- composer --- */
function autoGrowPrompt() {
  el.promptInput.style.height = "auto";
  el.promptInput.style.height = Math.min(220, el.promptInput.scrollHeight) + "px";
}

function renderReferences() {
  el.composerRefs.innerHTML = state.references
    .map(
      (r, i) => `<div class="ref-thumb" title="${esc(r.filename)}"><img src="${esc(r.url)}" alt="" /><button type="button" data-ref="${i}" aria-label="移除">✕</button></div>`
    )
    .join("");
}

async function uploadReferences(files) {
  const images = Array.from(files || []).filter((f) => f.type.startsWith("image/"));
  if (!images.length) return;
  for (const file of images) {
    const form = new FormData();
    form.append("file", file);
    const res = await fetch("/api/upload", { method: "POST", body: form });
    if (!res.ok) throw new Error(await readError(res));
    state.references.push(await res.json());
  }
  renderReferences();
  toast(`已添加 ${images.length} 张参考图`);
}

/* --------------------------------------------------------------- generate -- */
function requestBody() {
  return {
    prompt: el.promptInput.value.trim(),
    api_key: el.apiKeyInput.value.trim() || null,
    base_url: effectiveBaseUrl() || null,
    model_key: state.selected ? state.selected.id : "gpt-image2",
    upstream_model: state.selected ? state.selected.id : null,
    protocol: currentProtocol(),
    params: paramsFromForm(),
    reference_images: state.references.map((r) => r.url),
  };
}

async function generate() {
  const body = requestBody();
  if (!body.prompt) {
    toast("请先输入提示词", "bad");
    el.promptInput.focus();
    return;
  }
  persistConnection();

  setSending(true);
  showProgress({ status: "queued", progress: 5, message: "任务已提交", subtasks: [] });
  try {
    const { task_id } = await apiPost("/api/generate", body);
    startPolling(task_id);
  } catch (error) {
    setSending(false);
    hideProgress();
    toast(error.message, "bad");
  }
}

function setSending(on) {
  el.sendBtn.disabled = on;
  el.sendBtn.innerHTML = on ? `<span class="spinner"></span>` : icon("i-send");
}

function startPolling(taskId) {
  clearInterval(state.pollTimer);
  state.pollTimer = setInterval(() => pollTask(taskId), 900);
  pollTask(taskId);
}

async function pollTask(taskId) {
  try {
    const task = await apiGet(`/api/tasks/${taskId}`);
    showProgress(task);
    if (["completed", "success", "partial", "failed"].includes(task.status)) {
      clearInterval(state.pollTimer);
      setSending(false);
      await loadHistory();
      setTimeout(hideProgress, 1600);
      if (task.status === "failed") toast(task.error?.message || "生成失败", "bad");
      else if (task.status === "partial") toast("部分图片生成成功");
      else toast("生成完成");
    }
  } catch (error) {
    clearInterval(state.pollTimer);
    setSending(false);
    hideProgress();
    toast(error.message, "bad");
  }
}

const SUB_LABEL = { queued: "排队", running: "生成中", completed: "完成", failed: "失败" };
function showProgress(task) {
  const pct = Math.max(0, Math.min(100, Math.round(Number(task.progress || 0))));
  const done = ["completed", "success", "partial", "failed"].includes(task.status);
  const failed = task.status === "failed";
  el.progressCard.classList.add("show");
  el.progressCard.classList.toggle("done", done && !failed);
  el.progressCard.classList.toggle("failed", failed);
  el.pcSpin.style.display = done ? "none" : "inline-block";
  el.pcPct.textContent = `${pct}%`;
  el.pcFill.style.width = `${pct}%`;
  el.pcMsg.textContent = task.message || task.stage || "任务进行中";
  const subs = Array.isArray(task.subtasks) ? task.subtasks : [];
  el.pcSubs.innerHTML = subs
    .map((s) => `<span class="pc-sub ${esc(s.status)}">#${esc(s.index)} ${esc(SUB_LABEL[s.status] || s.status)}</span>`)
    .join("");
}
function hideProgress() {
  el.progressCard.classList.remove("show");
}

/* ---------------------------------------------------------------- history -- */
function cardItems() {
  const items = [];
  for (const record of state.history) {
    const results = Array.isArray(record.results) ? record.results : [];
    if (results.length) results.forEach((result, i) => items.push({ record, result, i }));
    else items.push({ record, result: null, i: 0 });
  }
  return items;
}

function renderHistory() {
  const items = cardItems();
  const counts = state.history.reduce(
    (acc, r) => {
      acc.total += 1;
      if (r.status === "success" || r.status === "completed") acc.ok += 1;
      else if (r.status === "failed") acc.fail += 1;
      else if (r.status === "partial") acc.ok += 1;
      return acc;
    },
    { total: 0, ok: 0, fail: 0 }
  );
  el.historyMetricNum.textContent = String(counts.total);
  el.shownCount.textContent = String(items.length);
  el.okCount.textContent = String(counts.ok);
  el.failCount.textContent = String(counts.fail);

  if (!items.length) {
    el.historyGrid.innerHTML = `
      <div class="empty-state">
        <div class="es-mark">${icon("i-sparkle", "icon")}</div>
        <strong>还没有生成记录</strong>
        <span>在下方输入提示词，选择模型后点击生成，结果会留在这里。</span>
      </div>`;
    return;
  }
  el.historyGrid.innerHTML = items.map((item, idx) => renderCard(item, idx)).join("");
}

function renderCard({ record, result, i }, idx) {
  const model = record.model || {};
  const p = record.params || {};
  const created = record.created_at ? new Date(record.created_at).toLocaleString([], { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }) : "";
  const dur = record.duration_ms ? `${(record.duration_ms / 1000).toFixed(record.duration_ms < 10000 ? 1 : 0)}s` : "—";
  const isFail = !result;
  const key = result ? result.relative_path : `${record.id}::fail`;
  const ratio = p.aspect_ratio && record.model?.protocol === "chat-completions" ? p.aspect_ratio : (p.size ? p.size.replace("x", "×") : "");
  const chips = [
    ratio,
    p.output_format ? String(p.output_format).toUpperCase() : "",
    p.count ? `${p.count} 张` : "",
  ].filter(Boolean);

  const figure = isFail
    ? `<div class="card-figure"><div class="card-fail">
         <div class="fail-mark">${icon("i-alert", "icon")}</div>
         <div class="fail-label">生成失败</div>
         <button class="detail-link" type="button" data-detail="${esc(record.id)}">${icon("i-info", "icon icon-sm")}查看详情</button>
       </div></div>`
    : `<div class="card-figure">
         <span class="card-index">#${i + 1}</span>
         <span class="card-check">${icon("i-check", "icon icon-sm")}</span>
         <img src="${esc(result.url)}" alt="${esc((record.prompt || "").slice(0, 60))}" loading="lazy" />
       </div>`;

  const actions = isFail
    ? `<button class="icon-btn" type="button" data-copy="${esc(record.id)}" title="复制提示词">${icon("i-copy", "icon icon-sm")}</button>
       <button class="icon-btn" type="button" data-detail="${esc(record.id)}" title="查看详情">${icon("i-info", "icon icon-sm")}</button>
       <span class="grow"></span>
       <button class="icon-btn" type="button" data-retry="${esc(record.id)}" title="重试">${icon("i-retry", "icon icon-sm")}</button>`
    : `<button class="icon-btn" type="button" data-copy="${esc(record.id)}" title="复制提示词">${icon("i-copy", "icon icon-sm")}</button>
       <button class="icon-btn" type="button" data-detail="${esc(record.id)}" title="查看完整参数与提示词">${icon("i-info", "icon icon-sm")}</button>
       <span class="grow"></span>
       <button class="icon-btn" type="button" data-retry="${esc(record.id)}" title="重试">${icon("i-retry", "icon icon-sm")}</button>
       <a class="icon-btn" href="${esc(result.url)}" download="${esc(result.filename || "image.png")}" title="下载">${icon("i-download", "icon icon-sm")}</a>`;

  const selected = state.selectedKeys.has(key);
  return `
    <article class="card ${!isFail && state.selectMode ? "selectable" : ""} ${selected ? "selected" : ""}" data-card-key="${esc(key)}" data-record="${esc(record.id)}" style="animation-delay:${Math.min(idx * 24, 280)}ms">
      ${figure}
      <div class="card-body">
        <div class="card-row">
          <span class="dur-badge ${isFail ? "bad" : ""}">${isFail ? icon("i-alert", "icon icon-sm") : icon("i-check", "icon icon-sm")}${esc(dur)}</span>
          <span class="card-model">${esc(model.upstream_model || model.label || "model")}</span>
        </div>
        ${chips.length ? `<div class="chip-row">${chips.map((c) => `<span class="chip">${esc(c)}</span>`).join("")}<span class="chip">${esc(created)}</span></div>` : ""}
        ${isFail
          ? `<div class="card-error-line">${esc(record.error?.message || "未知错误")}</div>`
          : `<p class="card-prompt">${esc(record.prompt || "")}</p>`}
        <div class="card-actions">${actions}</div>
      </div>
    </article>`;
}

function recordById(id) {
  return state.history.find((r) => r.id === id);
}

async function loadHistory() {
  state.history = await apiGet("/api/history");
  state.selectedKeys.clear();
  renderHistory();
  updateSelectionUI();
}

/* ------------------------------------------------------------- selection -- */
function setSelectMode(on) {
  state.selectMode = on;
  state.selectedKeys.clear();
  el.selectToggle.classList.toggle("is-active", on);
  el.selectToggleLabel.textContent = on ? "退出选择" : "选择";
  renderHistory();
  updateSelectionUI();
}

function updateSelectionUI() {
  if (state.selectMode) {
    el.downloadLabel.textContent = `下载所选 (${state.selectedKeys.size})`;
  } else {
    el.downloadLabel.textContent = "下载成功图片";
  }
}

function successUrls(onlySelected) {
  const urls = [];
  for (const { result } of cardItems()) {
    if (!result) continue;
    const key = result.relative_path;
    if (onlySelected && !state.selectedKeys.has(key)) continue;
    urls.push({ url: result.url, name: result.filename });
  }
  return urls;
}

async function downloadAll() {
  const list = successUrls(state.selectMode);
  if (!list.length) {
    toast(state.selectMode ? "未选择任何图片" : "暂无成功图片", "bad");
    return;
  }
  toast(`开始下载 ${list.length} 张图片`);
  for (const item of list) {
    const a = document.createElement("a");
    a.href = item.url;
    a.download = item.name || "image.png";
    document.body.appendChild(a);
    a.click();
    a.remove();
    await delay(220);
  }
}

/* ----------------------------------------------------------- overlay / UI -- */
function openOverlay(html) {
  el.overlay.innerHTML = html;
  el.overlay.classList.add("show");
}
function closeOverlay() {
  el.overlay.classList.remove("show");
  el.overlay.innerHTML = "";
}

function openLightbox(url) {
  openOverlay(`<img class="lightbox-img" src="${esc(url)}" alt="预览" />`);
}

function kv(label, value) {
  if (value == null || value === "" || value === "—") return "";
  return `<div class="kv"><span>${esc(label)}</span><b>${esc(value)}</b></div>`;
}

function dsec(label, inner, copyText, cls = "") {
  const btn = copyText
    ? `<button class="ds-copy" type="button" data-copy-text="${esc(copyText)}" title="复制到剪贴板">${icon("i-copy", "icon icon-sm")}<span>复制</span></button>`
    : "";
  return `<div class="detail-section ${cls}"><div class="ds-head"><span class="ds-label">${esc(label)}</span>${btn}</div>${inner}</div>`;
}

function openDetail(record) {
  const req = record.request || {};
  const m = record.model || {};
  const p = record.params || {};
  const isChat = m.protocol === "chat-completions";
  const created = record.created_at ? new Date(record.created_at).toLocaleString() : "";
  const dur = record.duration_ms ? `${(record.duration_ms / 1000).toFixed(1)}s` : "";
  const body = req.body ? JSON.stringify(req.body, null, 2) : "";

  const kvs = [
    kv("模型", m.upstream_model || m.label),
    kv("协议", m.protocol),
    kv("张数", p.count),
    kv("并发", p.concurrency),
    isChat ? kv("宽高比", p.aspect_ratio) : kv("尺寸", p.size),
    isChat ? kv("分辨率", p.image_size) : kv("质量", p.quality),
    kv("格式", p.output_format ? String(p.output_format).toUpperCase() : ""),
    kv("Seed", p.seed),
    isChat ? kv("温度", p.temperature) : "",
    kv("耗时", dur),
    kv("时间", created),
    kv("服务", record.provider?.base_url),
  ].filter(Boolean).join("");

  const requestText = `${req.endpoint || ""}${body ? "\n\n" + body : ""}`.trim();
  const errorText = record.error ? (record.error.message || JSON.stringify(record.error, null, 2)) : "";
  const sections = [];
  sections.push(dsec("提示词", `<div class="ds-text">${esc(record.prompt || "—")}</div>`, record.prompt || ""));
  if (p.negative_prompt) {
    sections.push(dsec("负面提示词", `<div class="ds-text">${esc(p.negative_prompt)}</div>`, p.negative_prompt));
  }
  sections.push(dsec("参数", `<div class="kv-grid">${kvs}</div>`));
  if (requestText) {
    sections.push(dsec("实际请求", `<pre>${esc(requestText)}</pre>`, requestText));
  }
  if (record.error) {
    sections.push(dsec("错误", `<pre>${esc(errorText)}</pre>`, errorText, "error"));
  }

  openOverlay(`
    <div class="detail-panel" data-stop>
      <div class="detail-head">
        <h3>${record.error ? "失败详情" : "生成详情"}</h3>
        <button class="icon-btn" type="button" data-close title="关闭">${icon("i-x", "icon icon-sm")}</button>
      </div>
      <div class="detail-body">${sections.join("")}</div>
    </div>`);
}

/* ----------------------------------------------------------------- retry --- */
function retryRecord(record) {
  el.promptInput.value = record.prompt || "";
  autoGrowPrompt();
  const p = record.params || {};
  if (p.count) el.countInput.value = p.count;
  if (p.concurrency) el.concurrencyInput.value = p.concurrency;
  if (p.size) el.sizeInput.value = p.size;
  if (p.aspect_ratio) el.aspectRatioInput.value = p.aspect_ratio;
  if (p.image_size) el.imageSizeInput.value = p.image_size;
  if (p.quality) el.qualityInput.value = p.quality;
  if (p.output_format) el.formatInput.value = p.output_format;
  if (p.seed != null) el.seedInput.value = p.seed;
  if (p.negative_prompt != null) el.negativePromptInput.value = p.negative_prompt;
  const m = record.model || {};
  if (m.upstream_model) selectModel({ id: m.upstream_model, protocol: m.protocol || currentProtocol() });
  updateSummary();
  el.promptInput.scrollIntoView({ behavior: "smooth", block: "center" });
  generate();
}

/* --------------------------------------------------------------- persist --- */
function persistConnection() {
  localStorage.setItem(LS.remember, String(el.rememberKey.checked));
  if (el.rememberKey.checked && el.apiKeyInput.value.trim()) localStorage.setItem(LS.apiKey, el.apiKeyInput.value.trim());
  if (!el.rememberKey.checked) localStorage.removeItem(LS.apiKey);
  localStorage.setItem(LS.baseSelect, el.baseUrlSelect.value);
  localStorage.setItem(LS.baseCustom, el.baseUrlInput.value.trim());
}

/* ------------------------------------------------------------------ init --- */
async function loadConfig() {
  state.config = await apiGet("/api/config");
  state.presets = state.config.models || [];
  rebuildCatalog();

  // restore connection
  el.baseUrlSelect.value = localStorage.getItem(LS.baseSelect) || state.config.default_base_url || "https://api.openai.com";
  if (![...el.baseUrlSelect.options].some((o) => o.value === el.baseUrlSelect.value)) el.baseUrlSelect.value = "__custom__";
  el.baseUrlInput.value = localStorage.getItem(LS.baseCustom) || "";
  syncBaseUrlField();
  el.rememberKey.checked = localStorage.getItem(LS.remember) === "true";
  if (el.rememberKey.checked) el.apiKeyInput.value = localStorage.getItem(LS.apiKey) || "";

  // restore selected model (or default to first preset)
  let restored = null;
  try {
    restored = JSON.parse(localStorage.getItem(LS.selectedModel) || "null");
  } catch {}
  const match = restored && state.catalog.find((m) => m.id === restored.id);
  selectModel(match || state.catalog[0], { remember: false });
  renderProtocolInfo();
  updateConnPill();
}

function bindEvents() {
  el.refreshHistoryBtn.addEventListener("click", () => loadHistory().then(() => toast("历史已刷新")).catch((e) => toast(e.message, "bad")));
  el.panelToggle.addEventListener("click", () => el.shell.classList.toggle("config-collapsed"));
  el.sendBtn.addEventListener("click", generate);
  el.fetchModelsBtn.addEventListener("click", fetchUpstreamModels);

  // prompt
  el.promptInput.addEventListener("input", () => {
    autoGrowPrompt();
    updateSummary();
  });
  el.promptInput.addEventListener("keydown", (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") generate();
  });

  // upload
  el.uploadBtn.addEventListener("click", () => el.referenceInput.click());
  el.referenceInput.addEventListener("change", async (e) => {
    try {
      await uploadReferences(e.target.files);
    } catch (err) {
      toast(err.message, "bad");
    } finally {
      e.target.value = "";
    }
  });
  el.composerRefs.addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-ref]");
    if (!btn) return;
    state.references.splice(Number(btn.dataset.ref), 1);
    renderReferences();
  });

  // params popover
  el.summaryChip.addEventListener("click", (e) => {
    e.stopPropagation();
    el.paramsPopover.classList.toggle("open");
  });
  document.addEventListener("click", (e) => {
    if (!el.paramsPopover.contains(e.target) && e.target !== el.summaryChip && !el.summaryChip.contains(e.target)) {
      el.paramsPopover.classList.remove("open");
    }
  });
  el.countSeg.addEventListener("click", (e) => {
    const b = e.target.closest("button[data-count]");
    if (!b) return;
    el.countInput.value = b.dataset.count;
    updateSummary();
  });
  el.ratioSeg.addEventListener("click", (e) => {
    const b = e.target.closest("button[data-ratio]");
    if (!b) return;
    applyRatio(b.dataset.ratio);
  });

  // config inputs
  el.protocolSelect.addEventListener("change", () => {
    renderProtocolInfo();
    if (state.selected) state.selected.protocol = currentProtocol();
    el.protoTag.textContent = (PROTOCOL_INFO[currentProtocol()] || {}).title || currentProtocol();
    updateSummary();
  });
  el.baseUrlSelect.addEventListener("change", () => {
    if (el.baseUrlSelect.value !== "__custom__") el.baseUrlInput.value = "";
    syncBaseUrlField();
    if (el.baseUrlSelect.value === "__custom__") el.baseUrlInput.focus();
  });
  el.baseUrlInput.addEventListener("input", syncBaseUrlField);
  el.apiKeyInput.addEventListener("input", updateConnPill);
  el.modelSearch.addEventListener("input", renderModelList);
  el.modelList.addEventListener("click", (e) => {
    const card = e.target.closest("button[data-model-id]");
    if (!card) return;
    selectModel({ id: card.dataset.modelId, protocol: card.dataset.modelProto });
  });
  [el.countInput, el.concurrencyInput, el.sizeInput, el.aspectRatioInput, el.imageSizeInput, el.qualityInput, el.formatInput].forEach((node) =>
    node.addEventListener("change", updateSummary)
  );

  // header actions
  el.selectToggle.addEventListener("click", () => setSelectMode(!state.selectMode));
  el.downloadShownBtn.addEventListener("click", downloadAll);

  // history grid (event delegation)
  el.historyGrid.addEventListener("click", (e) => {
    const card = e.target.closest(".card");
    const actionBtn = e.target.closest("[data-copy],[data-zoom],[data-detail],[data-retry]");
    if (actionBtn) {
      e.stopPropagation();
      if (actionBtn.dataset.copy != null) {
        const rec = recordById(actionBtn.dataset.copy);
        if (rec) navigator.clipboard.writeText(rec.prompt || "").then(() => toast("已复制提示词"));
        return;
      }
      if (actionBtn.dataset.zoom != null) return openLightbox(actionBtn.getAttribute("data-zoom"));
      if (actionBtn.dataset.detail != null) {
        const rec = recordById(actionBtn.dataset.detail);
        if (rec) openDetail(rec);
        return;
      }
      if (actionBtn.dataset.retry != null) {
        const rec = recordById(actionBtn.dataset.retry);
        if (rec) retryRecord(rec);
        return;
      }
    }
    // selection toggle (in select mode) — otherwise click image to preview
    if (state.selectMode) {
      if (card && card.classList.contains("selectable")) {
        const key = card.dataset.cardKey;
        if (state.selectedKeys.has(key)) state.selectedKeys.delete(key);
        else state.selectedKeys.add(key);
        card.classList.toggle("selected");
        updateSelectionUI();
      }
      return;
    }
    const fig = e.target.closest(".card-figure");
    if (fig) {
      const img = fig.querySelector("img");
      if (img) openLightbox(img.getAttribute("src"));
    }
  });
  // download links inside cards shouldn't trigger selection
  el.historyGrid.addEventListener("click", (e) => {
    if (e.target.closest("a[download]")) e.stopPropagation();
  });

  // overlay
  el.overlay.addEventListener("click", (e) => {
    const copyBtn = e.target.closest("[data-copy-text]");
    if (copyBtn) {
      navigator.clipboard.writeText(copyBtn.getAttribute("data-copy-text") || "").then(() => toast("已复制"));
      return;
    }
    if (e.target.closest("[data-close]") || !e.target.closest("[data-stop]")) closeOverlay();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      closeOverlay();
      el.paramsPopover.classList.remove("open");
    }
  });
}

async function init() {
  bindEvents();
  autoGrowPrompt();
  try {
    await loadConfig();
    await loadHistory();
    updateSummary();
  } catch (error) {
    toast(error.message, "bad");
  }
}

init();
