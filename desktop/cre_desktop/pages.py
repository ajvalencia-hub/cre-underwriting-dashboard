"""Inline HTML shown in the window before the backend is up, and if it fails.

Self-contained (no network, no backend) so the window is never blank.
"""

import html

from .osutil import FILE_BROWSER_LABEL

_BASE_CSS = """
:root { color-scheme: light dark; }
body { margin: 0; height: 100vh; display: flex; align-items: center; justify-content: center;
  font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  background: #f8fafc; color: #0f172a; }
@media (prefers-color-scheme: dark) { body { background: #0f172a; color: #e2e8f0; }
  .muted { color: #94a3b8 !important; } pre { background: #1e293b !important; } }
.card { max-width: 560px; padding: 32px; }
h1 { font-size: 18px; font-weight: 600; margin: 0 0 6px; }
.muted { color: #64748b; }
.spinner { width: 18px; height: 18px; border: 2px solid #cbd5e1; border-top-color: #0284c7;
  border-radius: 50%; animation: spin .8s linear infinite; display: inline-block;
  vertical-align: -3px; margin-right: 8px; }
@keyframes spin { to { transform: rotate(360deg); } }
pre { background: #f1f5f9; padding: 10px; border-radius: 6px; font-size: 12px;
  white-space: pre-wrap; word-break: break-word; max-height: 220px; overflow: auto; }
button { font: inherit; padding: 5px 12px; border-radius: 5px; border: 1px solid #94a3b8;
  background: transparent; color: inherit; cursor: pointer; margin-right: 6px; }
"""

STARTUP_HTML = f"""<!doctype html><html><head><meta charset="utf-8"><style>{_BASE_CSS}</style></head>
<body><div class="card">
  <h1><span class="spinner"></span>Starting CRE Underwriting…</h1>
  <p id="status" class="muted">Preparing your deal database.</p>
  <p class="muted" style="font-size:12px">The first launch can take up to half a minute.</p>
</div>
<script>window.setStatus = function (t) {{ document.getElementById('status').textContent = t; }};</script>
</body></html>"""


def error_html(summary: str, detail: str, log_path: str) -> str:
    detail_js = html.escape(detail).replace("`", "&#96;")
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>{_BASE_CSS}</style></head>
<body><div class="card">
  <h1>CRE Underwriting couldn't start</h1>
  <p>{html.escape(summary)}</p>
  <p class="muted">Your saved deals are not affected. Quit and reopen the app to try again.
  If it keeps happening, send the details below (and the log file) to whoever supports this app.</p>
  <pre id="detail">{detail_js}</pre>
  <p class="muted" style="font-size:12px">Log file: {html.escape(log_path)}</p>
  <button onclick="navigator.clipboard.writeText(document.getElementById('detail').innerText)">Copy details</button>
  <button onclick="window.pywebview && window.pywebview.api.reveal_logs()">Show log in {FILE_BROWSER_LABEL}</button>
</div></body></html>"""


ALREADY_RUNNING_HTML = f"""<!doctype html><html><head><meta charset="utf-8"><style>{_BASE_CSS}</style></head>
<body><div class="card">
  <h1>CRE Underwriting is already open</h1>
  <p class="muted">Switch to the existing window (it may be behind other windows or on another
  desktop). You can close this one.</p>
</div></body></html>"""
