// Where the page sends live questions. Empty = the server that served this page
// (frontend/serve.py locally, or the Hugging Face Space). The GitHub Pages
// workflow overwrites this file with the Space URL from the FLAMESCOPE_API
// repository variable, so the static site gets live answers too.
window.FLAMESCOPE_API = "";
