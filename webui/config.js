// Backend API base URL.
//
// - Leave as "" when the frontend is served by the same backend
//   (e.g. the FastAPI app deployed on Render, or local dev).
//
// - If you deploy this frontend folder (webui/) on Vercel and the FastAPI
//   backend on Render, set it to your Render URL, e.g.:
//     window.API_BASE = "https://devteam-ai.onrender.com";
//
// Also enable CORS on the backend by setting ALLOWED_ORIGIN to your
// Vercel frontend URL (see docs/DEPLOYMENT.md).
window.API_BASE = "";
