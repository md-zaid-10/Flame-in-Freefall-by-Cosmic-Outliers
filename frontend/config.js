// Where the page sends live questions.
// - On GitHub Pages: the answer server on Render (render.yaml).
// - Anywhere else (frontend/serve.py locally, or Render itself): "" = the server
//   that served this page.
// The Pages workflow can override this with the FLAMESCOPE_API repository variable.
window.FLAMESCOPE_API = location.hostname.endsWith("github.io") ? "https://flamescope.onrender.com" : "";
