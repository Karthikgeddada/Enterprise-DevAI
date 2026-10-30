// DevTeam AI — IDE-style frontend (Explorer / Editor / AI panel)
// API_BASE is set in config.js ("" = same origin; set to the Render URL when hosted on Vercel)
const API = (window.API_BASE || "").replace(/\/$/, "");

let currentRunId = null;
let lastCompletedRunId = null;
let continueMode = false;
let pollInterval = null;
let allGeneratedFiles = [];
let activeIndex = -1;

const $ = (id) => document.getElementById(id);

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
    });
}
bindPanelToggle("actExplorer", "sidePanel");
bindPanelToggle("actAI", "aiPanel");
if (window.innerWidth <= 980) {
    $("sidePanel").classList.add("collapsed");
    $("aiPanel").classList.add("collapsed");
    $("actExplorer").classList.remove("active");
    $("actAI").classList.remove("active");
}

/* ---------- Tabs ---------- */
function showWelcome() {
    $("welcomeTab").classList.add("active");
    $("codeTab").classList.remove("active");
    $("welcomeView").classList.remove("hidden");
    $("codeView").classList.add("hidden");
}
function showCode() {
    $("welcomeTab").classList.remove("active");
    $("codeTab").classList.add("active");
    $("welcomeView").classList.add("hidden");
    $("codeView").classList.remove("hidden");
}
$("welcomeTab").addEventListener("click", showWelcome);
$("codeTab").addEventListener("click", () => { if (activeIndex >= 0) showCode(); });

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
    $("promptInput").value = "";
    $("promptInput").placeholder = "Describe the project you want to build…";
    $("newProjectBtn").classList.add("hidden");
    restoreButton("Build");
    setStatus("Ready");
    showWelcome();
});

/* ---------- Run lifecycle ---------- */
function resetUI(isContinue) {
    clearError();
    document.querySelectorAll("#stepsList li").forEach((li) => (li.className = ""));
    $("logsTerminal").textContent = isContinue
        ? "Applying your change…"
        : "Your team is assembling…";
    $("runLabel").textContent = isContinue ? "UPDATING PROJECT" : "BUILDING PROJECT";
    $("fileTree").innerHTML = "";
    $("fileTree").classList.add("hidden");
    $("emptyExplorer").classList.remove("hidden");
    $("runMeta").classList.add("hidden");
    $("downloadBtn").classList.add("hidden");
    $("promptInput").placeholder = "Describe the project you want to build…";
    $("newProjectBtn").classList.add("hidden");
    continueMode = false;
    showWelcome();
    const btn = $("generateBtn");
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span>Building…';
    setStatus("Starting…");
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
    resetUI(isContinue);

    try {
        const body = { prompt };
        if (isContinue) body.base_run_id = lastCompletedRunId;
        const res = await fetch(`${API}/generate`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body)
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || `Request failed (${res.status})`);
        }
        const data = await res.json();
        currentRunId = data.run_id;
        pollInterval = setInterval(pollStatus, 2000);
    } catch (err) {
        showError(err.message || "Could not reach the server. If it was asleep, give it a moment and try again.");
        restoreButton();
        setStatus("Ready");
    }
});

async function pollStatus() {
    if (!currentRunId) return;
    try {
        const res = await fetch(`${API}/status/${currentRunId}`);
        if (!res.ok) return;
        const data = await res.json();

        updateLogs(data.logs);
        updateTracker(data.status);

        if (data.status === "completed" || data.status === "failed") {
            clearInterval(pollInterval);
            if (data.status === "completed") {
                fetchFiles();
            } else {
                restoreButton();
                setStatus("Failed");
                const last = (data.logs || []).slice(-1)[0] || "Generation failed.";
                showError(last.replace(/^FAILED:\s*/, ""));
            }
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

        allGeneratedFiles = data.files || [];
        if (!allGeneratedFiles.length) return;

        const lineCount = allGeneratedFiles.reduce(
            (n, f) => n + String(f.content || "").split("\n").length, 0
        );
        $("runMeta").textContent = `${allGeneratedFiles.length} files · ${lineCount.toLocaleString()} lines`;
        $("runMeta").classList.remove("hidden");
        $("downloadBtn").href = `${API}/download/${currentRunId}`;
        $("downloadBtn").classList.remove("hidden");
        $("runLabel").textContent = "GENERATED PROJECT";
        $("emptyExplorer").classList.add("hidden");

        renderTree();
        previewCode(0);
        setStatus(`Complete · ${allGeneratedFiles.length} files`);

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

function renderTree() {
    const el = $("fileTree");
    el.innerHTML = "";
    el.appendChild(buildBranch(buildTree(allGeneratedFiles)));
    el.classList.remove("hidden");
}

function buildBranch(node) {
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
        li.appendChild(buildBranch(node.dirs[d]));
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
    showCode();

    const ext = (file.path.split(".").pop() || "").toLowerCase();
    const viewer = $("codeViewer");
    viewer.className = `language-${EXT_LANG[ext] || "text"}`;
    viewer.removeAttribute("data-highlighted");
    viewer.textContent = file.content;

    if (window.hljs) {
        try { hljs.highlightElement(viewer); } catch (e) { /* non-fatal */ }
    }
}

