// Backend API base URL.
//
// - Leave as "" when the frontend is served by the same backend
//   (e.g. the FastAPI app deployed on Render, or local dev).
//
// - Frontend on Vercel + backend on Render: set it to the Render URL.
window.API_BASE = "https://enterprise-devai-les9.onrender.com";

// Optional API key for the backend (X-API-Key header).
// Leave "" for the open demo. Only set it if you also set API_KEY on the
// Render backend - and note a static frontend cannot truly keep secrets:
// this stops casual quota abuse, not a determined attacker.
window.API_KEY = "";

