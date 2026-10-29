// DevTeam AI frontend logic
// API_BASE is set in config.js ("" = same origin; set to the Render URL when hosted on Vercel)
const API = (window.API_BASE || "").replace(/\/$/, "");

let currentRunId = null;
let pollInterval = null;
let allGeneratedFiles = [];

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

function resetUI() {
    clearError();
    ["statusCard", "logsCard"].forEach((id) => $(id).classList.remove("hidden"));
    $("resultsSection").classList.add("hidden");
    document.querySelectorAll(".steps li").forEach((li) => (li.className = ""));
    $("progressBarFill").style.width = "0%";
    $("progressText").textContent = "0%";
    $("logsTerminal").textContent = "Starting...";
    const btn = $("generateBtn");
    btn.disabled = true;
    btn.textContent = "Generating…";
}

function restoreButton() {
    const btn = $("generateBtn");
    btn.disabled = false;
    btn.textContent = "Generate";
}

$("generateBtn").addEventListener("click", async () => {
    const prompt = $("promptInput").value.trim();
    if (!prompt) {
        showError("Please describe the project you want first.");
        return;
    }

    resetUI();

    try {
        const res = await fetch(`${API}/generate`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ prompt })
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || `Request failed (${res.status})`);
        }
        const data = await res.json();
        currentRunId = data.run_id;
        pollInterval = setInterval(pollStatus, 2000);
    } catch (err) {
        showError(err.message || "Could not reach the server.");
        restoreButton();
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
            restoreButton();
            if (data.status === "completed") {
                fetchFiles();
            } else {
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
        term.textContent = logs.map((l) => `> ${l}`).join("\n");
        term.scrollTop = term.scrollHeight;
    }
}

function updateTracker(status) {
    const stepData = STATUS_MAP[status];
    if (!stepData) return;

    $("progressBarFill").style.width = `${stepData.pct}%`;
    $("progressText").textContent = `${stepData.pct}%`;

    const order = ["requirements", "architecture", "coding", "review", "testing", "docs"];
    const activeIdx = stepData.step ? order.indexOf(stepData.step) : -1;

    document.querySelectorAll(".steps li").forEach((li, idx) => {
        li.className = "";
        if (status === "completed" || activeIdx === -1) {
            if (status === "completed") li.className = "done";
        } else if (idx < activeIdx) {
            li.className = "done";
        } else if (idx === activeIdx) {
            li.className = "active";
        }
    });
}

async function fetchFiles() {
    try {
        const res = await fetch(`${API}/files/${currentRunId}`);
        if (!res.ok) return;
        const data = await res.json();

        allGeneratedFiles = data.files || [];
        $("resultsSection").classList.remove("hidden");
        $("downloadBtn").href = `${API}/download/${currentRunId}`;

        renderFileList();
    } catch (e) {
        console.error(e);
    }
}

function renderFileList() {
    const list = $("fileList");
    list.innerHTML = "";
    allGeneratedFiles.forEach((f, idx) => {
        const li = document.createElement("li");
        li.textContent = f.path;
        li.onclick = () => previewCode(idx);
        list.appendChild(li);
    });
    if (allGeneratedFiles.length > 0) {
        previewCode(0);
    }
}

function previewCode(index) {
    document.querySelectorAll(".file-list li").forEach((li, i) => {
        li.classList.toggle("selected", i === index);
    });

    const file = allGeneratedFiles[index];
    const viewer = $("codeViewer");

    const extMap = {
        js: "javascript", ts: "typescript", html: "html", css: "css",
        md: "markdown", json: "json", py: "python", sql: "sql", sh: "bash",
        go: "go", rs: "rust", java: "java", yml: "yaml", yaml: "yaml"
    };
    const ext = (file.path.split(".").pop() || "").toLowerCase();
    const lang = extMap[ext] || "text";

    viewer.className = `language-${lang}`;
    viewer.textContent = file.content;

    if (window.hljs) {
        try { hljs.highlightElement(viewer); } catch (e) { /* non-fatal */ }
    }
}
