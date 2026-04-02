const state = {
  sessions: [],
  selectedSessionId: null,
  touchTimer: null,
  resizeObserver: null,
};

const sessionList = document.querySelector("#sessionList");
const sessionCount = document.querySelector("#sessionCount");
const dependencyList = document.querySelector("#dependencyList");
const createForm = document.querySelector("#createForm");
const refreshButton = document.querySelector("#refreshButton");
const stopButton = document.querySelector("#stopButton");
const previewContainer = document.querySelector("#previewContainer");
const previewFrame = document.querySelector("#previewFrame");
const previewEmpty = document.querySelector("#previewEmpty");
const previewLink = document.querySelector("#previewLink");
const template = document.querySelector("#sessionItemTemplate");

async function requestJson(url, options) {
  const response = await fetch(url, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = data.detail || `Request failed: ${response.status}`;
    throw new Error(detail);
  }
  return data;
}

function byId(id) {
  return document.getElementById(id);
}

function setText(id, value) {
  byId(id).textContent = value || "";
}

function scalePreview() {
  const session = state.sessions.find(
    (item) => item.session_id === state.selectedSessionId,
  );
  if (!session || !previewFrame.classList.contains("visible")) {
    return;
  }
  const containerW = previewContainer.clientWidth;
  const containerH = previewContainer.clientHeight;
  const nativeW = session.viewport_width;
  const nativeH = session.viewport_height;
  if (!containerW || !containerH || !nativeW || !nativeH) {
    return;
  }
  const scale = Math.min(containerW / nativeW, containerH / nativeH, 1);
  previewFrame.style.width = `${nativeW}px`;
  previewFrame.style.height = `${nativeH}px`;
  previewFrame.style.transform = `scale(${scale})`;
}

function clearSelectionView() {
  byId("detailTitle").textContent = "No Session Selected";
  byId("detailSubtitle").textContent =
    "Create or select a session to inspect its CDP and preview endpoints.";
  byId("detailGrid").classList.add("hidden");
  stopButton.disabled = true;
  previewFrame.classList.remove("visible");
  previewFrame.src = "about:blank";
  previewFrame.style.width = "";
  previewFrame.style.height = "";
  previewFrame.style.transform = "";
  previewEmpty.style.display = "grid";
  previewLink.href = "#";
}

function renderDependencies(items) {
  dependencyList.innerHTML = "";
  for (const item of items) {
    const row = document.createElement("div");
    row.className = "dependency-item";
    const name = document.createElement("strong");
    name.textContent = item.name;
    const path = document.createElement("code");
    path.textContent = item.path || "not found";
    const status = document.createElement("span");
    status.className = `status-pill ${item.available ? "ok" : "bad"}`;
    status.textContent = item.available ? "ready" : "missing";
    row.append(name, path, status);
    dependencyList.appendChild(row);
  }
}

function renderSessions() {
  sessionList.innerHTML = "";
  sessionCount.textContent = String(state.sessions.length);

  if (state.sessions.length === 0) {
    const empty = document.createElement("div");
    empty.className = "dependency-item";
    empty.textContent = "No sessions yet.";
    sessionList.appendChild(empty);
    clearSelectionView();
    return;
  }

  for (const session of state.sessions) {
    const node = template.content.firstElementChild.cloneNode(true);
    node.querySelector(".session-item-title").textContent = session.session_id;
    node.querySelector(".session-item-meta").textContent =
      `${session.owner_id} • ${session.status} • ${session.viewport_width}x${session.viewport_height}`;
    if (session.session_id === state.selectedSessionId) {
      node.classList.add("active");
    }
    node.addEventListener("click", () => {
      state.selectedSessionId = session.session_id;
      renderSessions();
      renderSelectedSession();
      scheduleTouch();
    });
    sessionList.appendChild(node);
  }

  if (
    !state.selectedSessionId ||
    !state.sessions.some((item) => item.session_id === state.selectedSessionId)
  ) {
    state.selectedSessionId = state.sessions[0].session_id;
  }
  renderSelectedSession();
}

function renderSelectedSession() {
  const session = state.sessions.find(
    (item) => item.session_id === state.selectedSessionId,
  );
  if (!session) {
    clearSelectionView();
    return;
  }

  byId("detailTitle").textContent = session.session_id;
  byId("detailSubtitle").textContent =
    `${session.status} session owned by ${session.owner_id}`;
  byId("detailGrid").classList.remove("hidden");
  stopButton.disabled = false;

  setText("detailOwner", session.owner_id);
  setText("detailStatus", session.status);
  setText("detailCdpHttp", session.cdp_http_endpoint);
  setText("detailCdpWs", session.cdp_ws_endpoint || "pending");
  setText("detailPreviewUrl", session.preview_url);
  setText("detailWorkingDir", session.working_dir);

  previewLink.href = session.preview_url;
  previewFrame.src = session.preview_url;
  previewFrame.classList.add("visible");
  previewEmpty.style.display = "none";
  scalePreview();
}

async function loadDependencies() {
  const data = await requestJson("/api/dependencies");
  renderDependencies(data.dependencies || []);
}

async function loadSessions() {
  const data = await requestJson("/api/sessions");
  state.sessions = data.sessions || [];
  renderSessions();
}

async function createSession(event) {
  event.preventDefault();
  const payload = {
    owner_id: byId("ownerId").value.trim() || "anonymous",
    start_url: byId("startUrl").value.trim() || null,
    viewport_width: byId("viewportWidth").value
      ? Number(byId("viewportWidth").value)
      : null,
    viewport_height: byId("viewportHeight").value
      ? Number(byId("viewportHeight").value)
      : null,
    persist_profile: byId("persistProfile").checked,
    kiosk: byId("kioskMode").checked,
  };

  const data = await requestJson("/api/sessions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  state.selectedSessionId = data.session.session_id;
  await loadSessions();
}

async function stopSelectedSession() {
  const sessionId = state.selectedSessionId;
  if (!sessionId) {
    return;
  }

  stopButton.disabled = true;
  try {
    await requestJson(`/api/sessions/${sessionId}`, { method: "DELETE" });
    if (state.selectedSessionId === sessionId) {
      state.selectedSessionId = null;
    }
    await loadSessions();
  } finally {
    stopButton.disabled = false;
  }
}

function scheduleTouch() {
  if (state.touchTimer) {
    window.clearInterval(state.touchTimer);
    state.touchTimer = null;
  }
  if (!state.selectedSessionId) {
    return;
  }
  state.touchTimer = window.setInterval(async () => {
    try {
      await requestJson(`/api/sessions/${state.selectedSessionId}/touch`, {
        method: "POST",
      });
    } catch (error) {
      console.warn("Failed to touch session", error);
    }
  }, 20000);
}

async function bootstrap() {
  await Promise.all([loadDependencies(), loadSessions()]);
  scheduleTouch();
  state.resizeObserver = new ResizeObserver(() => scalePreview());
  state.resizeObserver.observe(previewContainer);
}

createForm.addEventListener("submit", async (event) => {
  const createButton = byId("createButton");
  createButton.disabled = true;
  try {
    await createSession(event);
  } catch (error) {
    alert(error.message);
  } finally {
    createButton.disabled = false;
  }
});

refreshButton.addEventListener("click", async () => {
  try {
    await Promise.all([loadDependencies(), loadSessions()]);
    scheduleTouch();
  } catch (error) {
    alert(error.message);
  }
});

stopButton.addEventListener("click", async () => {
  try {
    await stopSelectedSession();
  } catch (error) {
    alert(error.message);
  }
});

window.addEventListener("beforeunload", () => {
  if (state.touchTimer) {
    window.clearInterval(state.touchTimer);
  }
});

bootstrap().catch((error) => {
  console.error(error);
  alert(error.message);
});
