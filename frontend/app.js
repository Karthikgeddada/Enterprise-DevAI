// DevTeam AI — IDE-style frontend (Explorer / Editor / AI panel)
// API_BASE is set in config.js ("" = same origin; set to the Render URL when hosted on Vercel)
const API = (window.API_BASE || "").replace(/\/$/, "");

let currentRunId = null;
let lastCompletedRunId = null;
let continueMode = false;
let pendingIsContinue = false;
let pollInterval = null;
let allGeneratedFiles = [];
let activeIndex = -1;
// Continue-mode diffing: snapshot of the project files before the last
// update, plus per-path change tags ("new"/"mod") for badges and the diff view.
let previousFilesSnapshot = [];
let fileChangeMap = new Map();

const $ = (id) => document.getElementById(id);

/* Mobile: overlay panels get a scrim; tapping it closes them */
const isNarrow = () => window.innerWidth <= 980;
function syncScrim() {
    const anyOpen = isNarrow() &&
        (!$("sidePanel").classList.contains("collapsed") ||
         !$("aiPanel").classList.contains("collapsed") ||
         !$("historyPanel").classList.contains("collapsed"));
    $("scrim").classList.toggle("show", anyOpen);
}
function closeOverlays() {
    $("sidePanel").classList.add("collapsed");
    $("aiPanel").classList.add("collapsed");
    $("historyPanel").classList.add("collapsed");
    $("actExplorer").classList.remove("active");
    $("actAI").classList.remove("active");
    $("actHistory").classList.remove("active");
    syncScrim();
}

// Map backend pipeline status -> (step key, progress %)
const STATUS_MAP = {
    starting:                { step: null,           pct: 2 },
    analyzing_requirements:  { step: "requirements", pct: 15 },
    designing_architecture: { step: "architecture", pct: 30 },
    generating_code:         { step: "coding",       pct: 50 },
    reviewing:              { step: "review",       pct: 60 },
    debugging:              { step: "review",       pct: 70 },
    testing:                 { step: "testing",      pct: 80 },
    documenting:            { step: "docs",         pct: 90 },
    completed:              { step: null,           pct: 100 },
    failed:                  { step: null,           pct: 100 }
};

/* ---------- Appearance: light & dark, remembers your choice ---------- */
function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    try { localStorage.setItem("dtai-theme", theme); } catch (e) { /* no-op */ }
}
$("themeToggle").addEventListener("click", () => {
    const dark = document.documentElement.getAttribute("data-theme") === "dark";
    applyTheme(dark ? "light" : "dark");
});

/* ---------- Activity-bar panel toggles ---------- */
function bindPanelToggle(btnId, panelId) {
    $(btnId).addEventListener("click", () => {
        const collapsed = $(panelId).classList.toggle("collapsed");
        $(btnId).classList.toggle("active", !collapsed);
        syncScrim();
    });
}
bindPanelToggle("actAI", "aiPanel");
/* Explorer and History share the left rail: opening one closes the other. */
$("actExplorer").addEventListener("click", () => {
    const collapsed = $("sidePanel").classList.toggle("collapsed");
    $("actExplorer").classList.toggle("active", !collapsed);
    if (!collapsed) {
        $("historyPanel").classList.add("collapsed");
        $("actHistory").classList.remove("active");
    }
    syncScrim();
});
$("actHistory").addEventListener("click", () => {
    const collapsed = $("historyPanel").classList.toggle("collapsed");
    $("actHistory").classList.toggle("active", !collapsed);
    if (!collapsed) {
        $("sidePanel").classList.add("collapsed");
        $("actExplorer").classList.remove("active");
        loadRuns();
    }
    syncScrim();
});
if (window.innerWidth <= 980) {
    $("sidePanel").classList.add("collapsed");
    $("aiPanel").classList.add("collapsed");
    $("actExplorer").classList.remove("active");
    $("actAI").classList.remove("active");
}
$("scrim").addEventListener("click", closeOverlays);
window.addEventListener("resize", syncScrim);

/* ---------- Run history (GET /runs) ---------- */
async function loadRuns() {
    try {
        const res = await fetch(`${API}/runs`);
        if (!res.ok) return;
        const data = await res.json();
        const runs = data.runs || [];
        const list = $("runList");
        list.innerHTML = "";
        $("emptyHistory").classList.toggle("hidden", runs.length > 0);
        if (!runs.length) {
            list.classList.add("hidden");
            return;
        }
        runs.forEach((run) => {
            const li = document.createElement("li");
            li.className = "run-item";

            const head = document.createElement("div");
            head.className = "run-head";
            const dot = document.createElement("span");
            dot.className = "run-dot " +
                (run.status === "completed" ? "ok" : run.status === "failed" ? "bad" : "mid");
            const id = document.createElement("span");
            id.className = "run-id";
            id.textContent = run.run_id;
            head.appendChild(dot);
            head.appendChild(id);

            const prompt = document.createElement("div");
            prompt.className = "run-prompt";
            prompt.textContent = (run.prompt || "untitled").slice(0, 90);
            prompt.title = run.prompt || "";

            const meta = document.createElement("div");
            meta.className = "run-meta-line";
            const when = run.updated_at
                ? new Date(run.updated_at * 1000).toLocaleString()
                : "";
            meta.textContent = `${run.status} · ${run.file_count} files · ${when}`;

            li.appendChild(head);
            li.appendChild(prompt);
            li.appendChild(meta);

            if (run.status === "completed") {
                const actions = document.createElement("div");
                actions.className = "run-actions";
                const openBtn = document.createElement("button");
                openBtn.className = "link-btn";
                openBtn.textContent = "Open";
                openBtn.addEventListener("click", () => openHistoryRun(run.run_id));
                actions.appendChild(openBtn);
                li.appendChild(actions);
            }

            list.appendChild(li);
        });
        list.classList.remove("hidden");
    } catch (e) {
        console.error(e);
    }
}

async function openHistoryRun(runId) {
    // Re-open a past run: load its files into the explorer and arm
    // continue mode so "Continue building" iterates on it.
    try {
        const res = await fetch(`${API}/files/${runId}`);
        if (!res.ok) return;
        const data = await res.json();
        const files = data.files || [];
        if (!files.length) return;

        allGeneratedFiles = files;
        currentRunId = runId;
        lastCompletedRunId = runId;
        continueMode = true;
        previousFilesSnapshot = [];
        fileChangeMap = new Map();
        pendingIsContinue = false;

        const lineCount = allGeneratedFiles.reduce(
            (n, f) => n + String(f.content || "").split("\n").length, 0
        );
        $("runMeta").textContent = `${allGeneratedFiles.length} files · ${lineCount.toLocaleString()} lines`;
        $("runMeta").classList.remove("hidden");
        $("downloadBtn").href = `${API}/download/${runId}` +
            (window.API_KEY ? `?api_key=${encodeURIComponent(window.API_KEY)}` : "");
        $("downloadBtn").classList.remove("hidden");
        $("shareBtn").classList.remove("hidden"); // a history run can be shared too
        $("pushBtn").classList.remove("hidden"); // ...and pushed to GitHub
        $("runLabel").textContent = "PROJECT FROM HISTORY";
        loadScorecard(runId); // stats available via the tab, code view stays up
        $("emptyExplorer").classList.add("hidden");
        renderTree(new Map());
        previewCode(0);
        setStatus(`Opened run ${runId}`);
        $("promptInput").placeholder = "Describe the change to make to this project…";
        restoreButton("Continue building");
        $("newProjectBtn").classList.remove("hidden");

        // Swap panels: back to the explorer with the opened project.
        $("historyPanel").classList.add("collapsed");
        $("actHistory").classList.remove("active");
        $("sidePanel").classList.remove("collapsed");
        $("actExplorer").classList.add("active");
        syncScrim();
    } catch (e) {
        console.error(e);
    }
}

/* ---------- Tabs ---------- */
function _deactivateAllTabs() {
    for (const t of ["welcomeTab", "codeTab", "diffTab", "scorecardTab"]) {
        $(t).classList.remove("active");
    }
    for (const v of ["welcomeView", "codeView", "diffView", "scorecardView"]) {
        $(v).classList.add("hidden");
    }
}
function showWelcome() {
    _deactivateAllTabs();
    $("welcomeTab").classList.add("active");
    $("welcomeView").classList.remove("hidden");
}
function showCode() {
    _deactivateAllTabs();
    $("codeTab").classList.add("active");
    $("codeView").classList.remove("hidden");
}
function showDiff() {
    _deactivateAllTabs();
    $("diffTab").classList.add("active");
    $("diffView").classList.remove("hidden");
}
function showScorecard() {
    _deactivateAllTabs();
    $("scorecardTab").classList.add("active");
    $("scorecardView").classList.remove("hidden");
}
$("welcomeTab").addEventListener("click", showWelcome);
$("codeTab").addEventListener("click", () => { if (activeIndex >= 0) showCode(); });
$("diffTab").addEventListener("click", () => { if (activeIndex >= 0) showDiff(); });
$("scorecardTab").addEventListener("click", showScorecard);

/* ---------- Errors & status bar ---------- */
function showError(msg) {
    const el = $("errorMsg");
    el.textContent = msg;
    el.classList.remove("hidden");
}
function clearError() {
    const el = $("errorMsg");
    el.textContent = "";
    el.classList.add("hidden");
}
function setStatus(text) {
    $("statusRight").textContent = text;
}

/* ---------- Prompt input ---------- */
document.querySelectorAll(".chip").forEach((chip) => {
    chip.addEventListener("click", () => {
        $("promptInput").value = chip.dataset.prompt || "";
        $("aiPanel").classList.remove("collapsed");
        $("actAI").classList.add("active");
        syncScrim();
        $("promptInput").focus();
    });
});
$("promptInput").addEventListener("keydown", (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") $("generateBtn").click();
});

/* Start a fresh project (exits continue mode) */
$("newProjectBtn").addEventListener("click", () => {
    currentRunId = null;
    lastCompletedRunId = null;
    continueMode = false;
    clearError();
    // Re-enable the input if we arrived from a shared read-only run.
    $("promptInput").disabled = false;
    $("promptInput").value = "";
    $("promptInput").placeholder = "Describe the project you want to build…";
    $("newProjectBtn").classList.add("hidden");
    restoreButton("Build");
    setStatus("Ready");
    showWelcome();
    // Leave shared-run mode: strip ?run= so refresh starts a clean session.
    if (window.history && window.location.search) {
        window.history.replaceState(null, "", window.location.pathname);
    }
});

/* ---------- Run lifecycle ---------- */
function resetUI(isContinue) {
    clearError();
    $("shareBtn").classList.add("hidden");
    $("pushBtn").classList.add("hidden");
    $("scorecardTab").classList.add("hidden"); // no current run = no scorecard
    document.querySelectorAll("#stepsList li").forEach((li) => (li.className = ""));
    $("logsTerminal").textContent = isContinue
        ? "Applying your change…"
        : "Your team is assembling…";
    $("runLabel").textContent = isContinue ? "UPDATING PROJECT" : "BUILDING PROJECT";
    $("promptInput").placeholder = "Describe the project you want to build…";
    $("newProjectBtn").classList.add("hidden");
    continueMode = false;
    const btn = $("generateBtn");
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span>Building…';
    setStatus("Starting…");
    if (isContinue) {
        // Keep the current codebase visible while the update runs.
        return;
    }
    $("fileTree").innerHTML = "";
    $("fileTree").classList.add("hidden");
    $("emptyExplorer").classList.remove("hidden");
    $("runMeta").classList.add("hidden");
    $("downloadBtn").classList.add("hidden");
    showWelcome();
}
function restoreButton(label) {
    const btn = $("generateBtn");
    btn.disabled = false;
    btn.textContent = label || "Build";
}

$("generateBtn").addEventListener("click", async () => {
    const prompt = $("promptInput").value.trim();
    if (!prompt) {
        showError(continueMode
            ? "Describe the change you want to make first."
            : "Describe the project you want to build first.");
        return;
    }

    const isContinue = continueMode && lastCompletedRunId;
    pendingIsContinue = isContinue;
    resetUI(isContinue);

    try {
        const body = { prompt };
        if (isContinue) body.base_run_id = lastCompletedRunId;
        const model = $("modelSelect").value || "auto";
        if (model && model !== "auto") body.provider = model;
        const headers = { "Content-Type": "application/json" };
        if (window.API_KEY) headers["X-API-Key"] = window.API_KEY;
        const res = await fetch(`${API}/generate`, {
            method: "POST",
            headers,
            body: JSON.stringify(body)
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || `Request failed (${res.status})`);
        }
        const data = await res.json();
        currentRunId = data.run_id;
        // Prefer live SSE updates; 2s polling stays as automatic fallback.
        if (!startStream(currentRunId)) {
            pollInterval = setInterval(pollStatus, 2000);
        }
    } catch (err) {
        showError(err.message || "Could not reach the server. If it was asleep, give it a moment and try again.");
        restoreButton();
        setStatus("Ready");
    }
});

function startStream(runId) {
    // Live updates over Server-Sent Events. Returns false when unavailable,
    // in which case the caller falls back to 2s polling.
    if (!window.EventSource) return false;
    try {
        const es = new EventSource(`${API}/stream/${runId}`);
        es.onmessage = (ev) => {
            try { handleProgress(JSON.parse(ev.data)); } catch (e) { console.error(e); }
        };
        es.onerror = () => {
            // Connection lost or server restarted — fall back to polling.
            es.close();
            if (currentRunId === runId && !pollInterval) {
                pollInterval = setInterval(pollStatus, 2000);
            }
        };
        return true;
    } catch (e) {
        return false;
    }
}

function handleProgress(data) {
    updateLogs(data.logs);
    updateTracker(data.status);
    if (data.status === "completed" || data.status === "failed") {
        finishRun(data);
    }
}

function finishRun(data) {
    if (pollInterval) {
        clearInterval(pollInterval);
        pollInterval = null;
    }
    if (data.status === "completed") {
        fetchFiles();
    } else {
        restoreButton();
        setStatus("Failed");
        const last = (data.logs || []).slice(-1)[0] || "Generation failed.";
        showError(last.replace(/^FAILED:\s*/, ""));
    }
}

async function pollStatus() {
    if (!currentRunId) return;
    try {
        const res = await fetch(`${API}/status/${currentRunId}`);
        if (!res.ok) return;
        const data = await res.json();

        updateLogs(data.logs);
        updateTracker(data.status);

        if (data.status === "completed" || data.status === "failed") {
            finishRun(data);
        }
    } catch (e) {
        console.error(e);
    }
}

function updateLogs(logs) {
    const term = $("logsTerminal");
    if (logs && logs.length > 0) {
        term.textContent = logs.map((l) => `› ${l}`).join("\n");
        term.scrollTop = term.scrollHeight;
    }
}

function updateTracker(status) {
    const stepData = STATUS_MAP[status];
    if (!stepData) return;

    const order = ["requirements", "architecture", "coding", "review", "testing", "docs"];
    const activeIdx = stepData.step ? order.indexOf(stepData.step) : -1;

    document.querySelectorAll("#stepsList li").forEach((li, idx) => {
        li.className = "";
        if (status === "completed") {
            li.className = "done";
        } else if (status !== "failed" && activeIdx !== -1) {
            if (idx < activeIdx) li.className = "done";
            else if (idx === activeIdx) li.className = "active";
        }
    });

    if (status === "completed") setStatus("Complete");
    else if (status === "failed") setStatus("Failed");
    else if (stepData.step) setStatus(`Building · ${stepData.pct}%`);
}

/* ---------- Results: explorer tree + code view ---------- */
async function fetchFiles() {
    try {
        const res = await fetch(`${API}/files/${currentRunId}`);
        if (!res.ok) return;
        const data = await res.json();

        const previousFiles = allGeneratedFiles;
        allGeneratedFiles = data.files || [];
        if (!allGeneratedFiles.length) return;

        // In continue mode, diff the new files against the previous ones so
        // the explorer can badge what was added or changed.
        const changeMap = new Map();
        if (pendingIsContinue) {
            const prevMap = new Map(previousFiles.map((f) => [f.path, f.content]));
            allGeneratedFiles.forEach((f) => {
                if (!prevMap.has(f.path)) changeMap.set(f.path, "new");
                else if (prevMap.get(f.path) !== f.content) changeMap.set(f.path, "mod");
            });
        }
        // Keep the before/after comparison data for the diff view.
        previousFilesSnapshot = previousFiles.slice();
        fileChangeMap = changeMap;
        pendingIsContinue = false;

        const lineCount = allGeneratedFiles.reduce(
            (n, f) => n + String(f.content || "").split("\n").length, 0
        );
        const changedCount = changeMap.size;
        $("runMeta").textContent = changedCount
            ? `${allGeneratedFiles.length} files · ${lineCount.toLocaleString()} lines · ${changedCount} changed`
            : `${allGeneratedFiles.length} files · ${lineCount.toLocaleString()} lines`;
        $("runMeta").classList.remove("hidden");
        $("downloadBtn").href = `${API}/download/${currentRunId}` +
            (window.API_KEY ? `?api_key=${encodeURIComponent(window.API_KEY)}` : "");
        $("downloadBtn").classList.remove("hidden");
        $("shareBtn").classList.remove("hidden");
        $("pushBtn").classList.remove("hidden");
        $("runLabel").textContent = "GENERATED PROJECT"; // fresh build: exportable too
        loadScorecard(currentRunId, { focus: true }); // the wow moment: build summary
        $("emptyExplorer").classList.add("hidden");

        renderTree(changeMap);
        const firstChanged = allGeneratedFiles.findIndex((f) => changeMap.has(f.path));
        previewCode(firstChanged >= 0 ? firstChanged : 0);
        setStatus(`Complete · ${allGeneratedFiles.length} files${changedCount ? ` · ${changedCount} changed` : ""}`);

        // Enter continue mode: the next prompt iterates on this project.
        lastCompletedRunId = currentRunId;
        continueMode = true;
        $("promptInput").placeholder = "Describe the change to make to this project…";
        restoreButton("Continue building");
        $("newProjectBtn").classList.remove("hidden");
    } catch (e) {
        console.error(e);
    }
}

function buildTree(files) {
    const root = { dirs: {}, files: [] };
    files.forEach((f, idx) => {
        const parts = f.path.split("/").filter(Boolean);
        let node = root;
        parts.forEach((p, i) => {
            if (i === parts.length - 1) {
                node.files.push({ name: p, idx });
            } else {
                node.dirs[p] = node.dirs[p] || { dirs: {}, files: [] };
                node = node.dirs[p];
            }
        });
    });
    return root;
}

function renderTree(changeMap) {
    const el = $("fileTree");
    el.innerHTML = "";
    el.appendChild(buildBranch(buildTree(allGeneratedFiles), changeMap || new Map()));
    el.classList.remove("hidden");
}

function buildBranch(node, changeMap) {
    const ul = document.createElement("ul");

    Object.keys(node.dirs).sort().forEach((d) => {
        const li = document.createElement("li");
        li.className = "tree-dir open";

        const row = document.createElement("div");
        row.className = "tree-row";
        const chev = document.createElement("span");
        chev.className = "chev";
        chev.textContent = "▾";
        const label = document.createElement("span");
        label.textContent = d;
        row.appendChild(chev);
        row.appendChild(label);
        row.addEventListener("click", () => li.classList.toggle("open"));

        li.appendChild(row);
        li.appendChild(buildBranch(node.dirs[d], changeMap));
        ul.appendChild(li);
    });

    node.files
        .sort((a, b) => a.name.localeCompare(b.name))
        .forEach((f) => {
            const li = document.createElement("li");
            li.className = "tree-row tree-file";
            li.dataset.idx = f.idx;
            const spacer = document.createElement("span");
            spacer.className = "chev";
            const label = document.createElement("span");
            label.textContent = f.name;
            li.appendChild(spacer);
            li.appendChild(label);
            const tag = changeMap.get(f.path);
            if (tag) {
                li.classList.add(tag === "new" ? "is-new" : "is-mod");
                const badge = document.createElement("span");
                badge.className = "tree-badge";
                badge.textContent = tag === "new" ? "N" : "M";
                li.appendChild(badge);
            }
            li.addEventListener("click", () => previewCode(f.idx));
            ul.appendChild(li);
        });

    return ul;
}

const EXT_LANG = {
    js: "javascript", ts: "typescript", html: "html", css: "css",
    md: "markdown", json: "json", py: "python", sql: "sql", sh: "bash",
    go: "go", rs: "rust", java: "java", yml: "yaml", yaml: "yaml"
};

function previewCode(index) {
    const file = allGeneratedFiles[index];
    if (!file) return;
    activeIndex = index;

    document.querySelectorAll(".tree-file").forEach((el) => {
        el.classList.toggle("selected", Number(el.dataset.idx) === index);
    });

    $("codeTab").textContent = file.path.split("/").pop();
    $("codeTab").classList.remove("hidden");

    // Files modified by a continue-run open in side-by-side diff view;
    // everything else opens as plain code. The code tab still shows the
    // full file content when clicked.
    const hasDiff = fileChangeMap.get(file.path) === "mod" && window.Diff;
    $("diffTab").classList.toggle("hidden", !hasDiff);
    if (hasDiff) {
        renderDiffView(file);
        showDiff();
    } else {
        showCode();
    }

    // On phones the explorer is an overlay: close it so the code is visible.
    if (isNarrow() && !$("sidePanel").classList.contains("collapsed")) closeOverlays();

    const ext = (file.path.split(".").pop() || "").toLowerCase();
    const viewer = $("codeViewer");
    viewer.className = `language-${EXT_LANG[ext] || "text"}`;
    viewer.removeAttribute("data-highlighted");
    viewer.textContent = file.content;

    if (ext === "mmd") {
        renderMermaid(file.content); // raw source stays visible as fallback
    } else if (window.hljs) {
        try { hljs.highlightElement(viewer); } catch (e) { /* non-fatal */ }
    }
}

/* ---------- Mermaid diagram rendering (ARCHITECTURE.mmd files) ---------- */
async function renderMermaid(content) {
    const viewer = $("codeViewer");
    viewer.removeAttribute("data-highlighted");
    if (!window.mermaid) return; // CDN unavailable: raw source remains visible
    try {
        // The editor tile is dark in both themes, so always use the dark theme.
        window.mermaid.initialize({ startOnLoad: false, securityLevel: "strict", theme: "dark" });
        const { svg } = await window.mermaid.render("mermaid-svg-" + Date.now(), content);
        const wrap = document.createElement("div");
        wrap.className = "mermaid-wrap";
        wrap.innerHTML = svg;
        viewer.replaceChildren(wrap);
    } catch (e) {
        console.error(e); // invalid diagram: keep raw source visible
    }
}

/* ---------- Side-by-side diff view (jsdiff, continue mode) ---------- */
function renderDiffView(file) {
    const prev = previousFilesSnapshot.find((f) => f.path === file.path);
    const body = $("diffScroll");
    body.innerHTML = "";

    const splitLines = (s) => {
        const lines = String(s || "").split("\n");
        if (lines.length && lines[lines.length - 1] === "") lines.pop();
        return lines;
    };
    const row = (l, r, cls) => {
        const tr = document.createElement("tr");
        const tdL = document.createElement("td");
        const tdR = document.createElement("td");
        tdL.textContent = l;
        tdR.textContent = r;
        if (cls) { tdL.className = cls; tdR.className = cls; }
        tr.appendChild(tdL);
        tr.appendChild(tdR);
        return tr;
    };

    const tbody = document.createElement("tbody");
    const parts = window.Diff.diffLines(prev ? prev.content : "", file.content);
    for (let i = 0; i < parts.length; i++) {
        const p = parts[i];
        if (!p.added && !p.removed) {
            splitLines(p.value).forEach((line) =>
                tbody.appendChild(row(line, line, ""))
            );
        } else {
            // One change block: gather consecutive removed/added parts.
            const removed = [];
            const added = [];
            while (i < parts.length && (parts[i].removed || parts[i].added)) {
                (parts[i].removed ? removed : added).push(...splitLines(parts[i].value));
                i++;
            }
            i--;
            const n = Math.max(removed.length, added.length);
            for (let k = 0; k < n; k++) {
                const tr = document.createElement("tr");
                const tdL = document.createElement("td");
                const tdR = document.createElement("td");
                tdL.textContent = removed[k] != null ? removed[k] : "";
                tdR.textContent = added[k] != null ? added[k] : "";
                tdL.className = removed[k] != null ? "diff-del" : "diff-gap";
                tdR.className = added[k] != null ? "diff-add" : "diff-gap";
                tr.appendChild(tdL);
                tr.appendChild(tdR);
                tbody.appendChild(tr);
            }
        }
    }

    const table = document.createElement("table");
    table.className = "diff-table";
    table.appendChild(tbody);
    body.appendChild(table);
    body.scrollTop = 0;
}

/* ---------- Shareable run links (?run=<id>) ---------- */
function copyShareLink() {
    if (!currentRunId) return;
    const url = `${location.origin}${location.pathname}?run=${currentRunId}`;
    const done = () => setStatus("Share link copied to clipboard");
    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(url).then(done, () => window.prompt("Copy this link:", url));
    } else {
        window.prompt("Copy this link:", url);
    }
}
$("shareBtn").addEventListener("click", copyShareLink);

async function loadSharedRun() {
    // ?run=<id> opens a finished run read-only: files, diagrams, ZIP —
    // everything a reviewer needs, no editing. "New project" unlocks the app.
    const rid = new URLSearchParams(window.location.search).get("run");
    if (!rid) return;
    try {
        const res = await fetch(`${API}/files/${rid}`);
        const data = res.ok ? await res.json() : null;
        const files = (data && data.files) || [];
        if (!files.length) {
            setStatus("Shared run not found (it may have expired)");
            return;
        }

        allGeneratedFiles = files;
        currentRunId = rid;
        lastCompletedRunId = null; // read-only: continuing is not allowed
        continueMode = false;
        previousFilesSnapshot = [];
        fileChangeMap = new Map();

        const lineCount = allGeneratedFiles.reduce(
            (n, f) => n + String(f.content || "").split("\n").length, 0
        );
        $("runMeta").textContent = `${allGeneratedFiles.length} files · ${lineCount.toLocaleString()} lines`;
        $("runMeta").classList.remove("hidden");
        $("downloadBtn").href = `${API}/download/${rid}` +
            (window.API_KEY ? `?api_key=${encodeURIComponent(window.API_KEY)}` : "");
        $("downloadBtn").classList.remove("hidden");
        $("runLabel").textContent = "SHARED RUN (READ-ONLY)";
        $("emptyExplorer").classList.add("hidden");
        renderTree(new Map());
        previewCode(0);

        // Read-only presentation: lock the input, offer a fresh start instead.
        const input = $("promptInput");
        input.disabled = true;
        input.value = "";
        input.placeholder = "You are viewing a shared read-only run…";
        const btn = $("generateBtn");
        btn.disabled = true;
        btn.textContent = "Read-only";
        $("newProjectBtn").classList.remove("hidden");
        setStatus(`Viewing shared run ${rid}`);
        document.title = "DevTeam AI — shared run";
        loadScorecard(rid, { focus: true }); // reviewers land on the build summary
    } catch (e) {
        console.error(e);
        setStatus("Could not load the shared run");
    }
}
loadSharedRun();

/* ---------- Scorecard (GET /scorecard/<id>) ---------- */
function fmtDuration(sec) {
    if (sec == null) return "—";
    if (sec < 60) return `${Math.round(sec)}s`;
    return `${Math.floor(sec / 60)}m ${Math.round(sec % 60)}s`;
}

async function loadScorecard(runId, opts) {
    if (!runId) return;
    const focus = !!(opts && opts.focus);
    try {
        const res = await fetch(`${API}/scorecard/${runId}`);
        if (!res.ok) {
            $("scorecardTab").classList.add("hidden");
            return;
        }
        renderScorecard(await res.json());
        $("scorecardTab").classList.remove("hidden");
        if (focus) showScorecard();
    } catch (e) {
        console.error(e);
    }
}

function renderScorecard(data) {
    const root = $("scoreScroll");
    root.innerHTML = "";

    const head = document.createElement("div");
    head.className = "score-head";
    const title = document.createElement("h2");
    title.textContent = (data.prompt || "untitled").slice(0, 100);
    const sub = document.createElement("p");
    sub.className = "dim";
    sub.textContent = `run ${data.run_id} · ${data.status} · built in ${fmtDuration(data.duration_seconds)}`;
    head.appendChild(title);
    head.appendChild(sub);
    root.appendChild(head);

    const tiles = document.createElement("div");
    tiles.className = "score-tiles";
    const stats = [
        [`${data.file_count}`, "files"],
        [`${data.total_lines.toLocaleString()}`, "lines of code"],
        [`${fmtDuration(data.duration_seconds)}`, "build time"],
        [`${data.self_heals}`, "self-heals"],
    ];
    for (const [value, label] of stats) {
        const tile = document.createElement("div");
        tile.className = "score-tile";
        const v = document.createElement("strong");
        v.textContent = value;
        const l = document.createElement("span");
        l.textContent = label;
        tile.appendChild(v);
        tile.appendChild(l);
        tiles.appendChild(tile);
    }
    root.appendChild(tiles);

    if (data.largest_file) {
        const big = document.createElement("p");
        big.className = "score-big dim";
        big.textContent = `largest file: ${data.largest_file.path} (${data.largest_file.lines} lines)`;
        root.appendChild(big);
    }

    const checkList = document.createElement("ul");
    checkList.className = "score-checks";
    const checkLabels = {
        readme: "README",
        architecture_doc: "Architecture doc",
        architecture_diagram: "Architecture diagram",
        tests: "Test suite",
    };
    for (const key of Object.keys(checkLabels)) {
        const li = document.createElement("li");
        const mark = document.createElement("span");
        const pass = !!(data.quality_checks && data.quality_checks[key]);
        mark.className = pass ? "check ok" : "check no";
        mark.textContent = pass ? "✓" : "—";
        li.appendChild(mark);
        li.appendChild(document.createTextNode(checkLabels[key]));
        checkList.appendChild(li);
    }
    root.appendChild(checkList);

    const langs = Object.entries(data.languages || {});
    if (langs.length) {
        const wrap = document.createElement("div");
        wrap.className = "score-langs";
        const h3 = document.createElement("h3");
        h3.textContent = "Languages";
        wrap.appendChild(h3);
        const maxLines = Math.max(...langs.map(([, v]) => v.lines), 1);
        for (const [ext, v] of langs) {
            const row = document.createElement("div");
            row.className = "lang-row";
            const name = document.createElement("span");
            name.className = "lang-name";
            name.textContent = `.${ext}`;
            const bar = document.createElement("div");
            bar.className = "lang-bar-track";
            const fill = document.createElement("div");
            fill.className = "lang-bar";
            fill.style.width = `${Math.max((v.lines / maxLines) * 100, 3)}%`;
            bar.appendChild(fill);
            const count = document.createElement("span");
            count.className = "lang-count";
            count.textContent = `${v.files}f · ${v.lines.toLocaleString()} lines`;
            row.appendChild(name);
            row.appendChild(bar);
            row.appendChild(count);
            wrap.appendChild(row);
        }
        root.appendChild(wrap);
    }
}

/* ---------- Model selector (GET /models, per-run provider choice) ---------- */
async function initModelSelect() {
    const sel = $("modelSelect");
    try {
        const res = await fetch(`${API}/models`);
        const data = await res.json();
        const choices = data.choices || [];
        if (!choices.length) return;

        for (const c of choices) {
            const opt = document.createElement("option");
            opt.value = c.id;
            opt.textContent = c.label;
            sel.appendChild(opt);
        }

        const saved = localStorage.getItem("dtai-provider");
        if (saved && choices.some((c) => c.id === saved)) sel.value = saved;
        sel.addEventListener("change", () => {
            localStorage.setItem("dtai-provider", sel.value);
        });

        // Only show the selector when there is a real choice to make.
        if (choices.length > 1) sel.classList.remove("hidden");
    } catch (e) {
        /* selector stays hidden — provider falls back to server default */
    }
}
initModelSelect();

/* ---------- Platform stats (GET /stats) ---------- */
async function openStatsModal() {
    const body = $("statsBody");
    body.textContent = "Loading…";
    $("statsModal").classList.remove("hidden");
    try {
        const res = await fetch(`${API}/stats`);
        const data = await res.json();
        renderStats(data, body);
    } catch (e) {
        body.textContent = "Could not load stats.";
    }
}

function renderStats(data, body) {
    body.innerHTML = "";

    const runs = data.runs || {};
    const builds = data.builds || {};
    // (No ?? here: esprima, the syntax gate, predates ES2020.)
    const totalRuns = runs.total != null ? runs.total : 0;
    const avgFiles = builds.avg_files != null ? builds.avg_files : "—";

    const tiles = document.createElement("div");
    tiles.className = "score-tiles";
    const completed = (runs.by_status || {}).completed || 0;
    const failed = (runs.by_status || {}).failed || 0;
    const stats = [
        [`${totalRuns}`, "runs"],
        [`${completed}`, "completed"],
        [`${failed}`, "failed"],
        [`${fmtDuration(builds.avg_duration_seconds)}`, "avg build"],
        [`${avgFiles}`, "avg files"],
        [`${builds.self_heals_total || 0}`, "self-heals"],
    ];
    for (const [value, label] of stats) {
        const tile = document.createElement("div");
        tile.className = "score-tile";
        const v = document.createElement("strong");
        v.textContent = value;
        const l = document.createElement("span");
        l.textContent = label;
        tile.appendChild(v);
        tile.appendChild(l);
        tiles.appendChild(tile);
    }
    body.appendChild(tiles);

    const causes = runs.failure_causes || {};
    const causeKeys = Object.keys(causes);
    if (causeKeys.length) {
        const p = document.createElement("p");
        p.className = "dim";
        p.style.fontSize = "12px";
        p.textContent = "failure causes: " +
            causeKeys.map((k) => `${k} ×${causes[k]}`).join(", ");
        body.appendChild(p);
    }

    const langs = Object.entries(data.languages || {});
    if (langs.length) {
        const wrap = document.createElement("div");
        wrap.className = "score-langs";
        const h3 = document.createElement("h3");
        h3.textContent = "Top languages";
        wrap.appendChild(h3);
        const maxLines = Math.max(...langs.map(([, v]) => v.lines), 1);
        for (const [ext, v] of langs) {
            const row = document.createElement("div");
            row.className = "lang-row";
            const name = document.createElement("span");
            name.className = "lang-name";
            name.textContent = `.${ext}`;
            const track = document.createElement("div");
            track.className = "lang-bar-track";
            const fill = document.createElement("div");
            fill.className = "lang-bar";
            fill.style.width = `${Math.max((v.lines / maxLines) * 100, 3)}%`;
            track.appendChild(fill);
            const count = document.createElement("span");
            count.className = "lang-count";
            count.textContent = `${v.files}f · ${v.lines.toLocaleString()} lines`;
            row.appendChild(name);
            row.appendChild(track);
            row.appendChild(count);
            wrap.appendChild(row);
        }
        body.appendChild(wrap);
    }
}

$("statsBtn").addEventListener("click", openStatsModal);
$("statsClose").addEventListener("click", () => $("statsModal").classList.add("hidden"));
$("statsModal").addEventListener("click", (e) => {
    if (e.target === $("statsModal")) $("statsModal").classList.add("hidden");
});

/* ---------- Push to GitHub (user's PAT, POST /export/github) ---------- */
let ghDone = false;

function openGhModal() {
    if (!currentRunId) return;
    ghDone = false;
    $("ghRepoName").value = `devteam-ai-${currentRunId}`;
    $("ghToken").value = "";
    const btn = $("ghPush");
    btn.disabled = false;
    btn.textContent = "Push";
    $("ghModalTitle").textContent = "Push to GitHub";
    const desc = $("ghModalDesc");
    desc.textContent = "Creates a public repo under your GitHub account with this project's files. Your token is used once and never stored.";
    $("ghModal").classList.remove("hidden");
    $("ghToken").focus();
}

function closeGhModal() {
    $("ghModal").classList.add("hidden");
}

$("pushBtn").addEventListener("click", openGhModal);
$("ghCancel").addEventListener("click", closeGhModal);
$("ghModal").addEventListener("click", (e) => {
    if (e.target === $("ghModal")) closeGhModal();
});
$("ghToken").addEventListener("keydown", (e) => {
    if (e.key === "Enter") $("ghPush").click();
});

$("ghPush").addEventListener("click", async () => {
    if (ghDone) {
        closeGhModal();
        return;
    }
    const token = $("ghToken").value.trim();
    if (!token) {
        $("ghToken").focus();
        return;
    }
    const btn = $("ghPush");
    btn.disabled = true;
    btn.textContent = "Pushing…";
    try {
        const headers = { "Content-Type": "application/json" };
        if (window.API_KEY) headers["X-API-Key"] = window.API_KEY;
        const res = await fetch(`${API}/export/github`, {
            method: "POST",
            headers,
            body: JSON.stringify({
                run_id: currentRunId,
                repo_name: $("ghRepoName").value.trim() || undefined,
                token,
            }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.detail || `Export failed (${res.status})`);

        // Success: swap the modal body for the repo link.
        ghDone = true;
        $("ghModalTitle").textContent = "Pushed!";
        const desc = $("ghModalDesc");
        desc.textContent = "Your project is live at ";
        const link = document.createElement("a");
        link.href = data.repo_url;
        link.target = "_blank";
        link.rel = "noopener";
        link.textContent = data.repo_url;
        desc.appendChild(link);
        btn.disabled = false;
        btn.textContent = "Close";
        setStatus(`Pushed to GitHub: ${data.repo_name}`);
    } catch (err) {
        btn.disabled = false;
        btn.textContent = "Push";
        showError(err.message || "GitHub export failed.");
    }
});

