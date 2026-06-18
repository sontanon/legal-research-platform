"""Server-rendered MCP Apps widget HTML with a hand-rolled postMessage client.

Single recipe for all UI-capable clients (Claude Desktop, Copilot, ChatGPT, etc.):
the widget polls get_status via tools/call (callServerTool) at a fixed interval,
renders progress, and on terminal status calls get_result, then pushes the
structured report into the model context via ui/update-model-context, triggers a
follow-up via ui/message, and displays the final report inline.

No external assets (no CDN, no external JS) — fully self-contained inline HTML.
This is required for Copilot (which drops connectDomains/resourceDomains from
the widget CSP) and works everywhere else too.

The postMessage JSON-RPC protocol is implemented directly per the MCP Apps spec
(SEP-1865, 2026-01-26). No @modelcontextprotocol/ext-apps SDK dependency.
"""

from __future__ import annotations

from .config import settings
from .profiles import ClientProfile

_WIDGET_URI = "ui://legal/progress.html"

_WIDGET_JS = r"""
(function() {
  'use strict';

  var nextId = 1;
  var pending = {};
  var notifHandlers = {};
  var jobId = null;
  var pollTimer = null;
  var done = false;

  function log(msg) {
    var el = document.getElementById('log');
    if (el) el.textContent = msg;
  }

  window.addEventListener('message', function(event) {
    var msg = event.data;
    if (!msg || msg.jsonrpc !== '2.0') return;
    if (msg.id != null && (msg.result !== undefined || msg.error !== undefined)) {
      var p = pending[msg.id];
      if (p) {
        delete pending[msg.id];
        if (msg.error) p.reject(msg.error);
        else p.resolve(msg.result);
      }
    } else if (msg.method) {
      var hs = notifHandlers[msg.method];
      if (hs) hs.forEach(function(h) { h(msg.params, msg); });
    }
  });

  function sendRequest(method, params) {
    var id = nextId++;
    return new Promise(function(resolve, reject) {
      pending[id] = {resolve: resolve, reject: reject};
      window.parent.postMessage({jsonrpc: '2.0', id: id, method: method, params: params}, '*');
    });
  }

  function sendNotification(method, params) {
    window.parent.postMessage({jsonrpc: '2.0', method: method, params: params || {}}, '*');
  }

  function onMessage(method, handler) {
    if (!notifHandlers[method]) notifHandlers[method] = [];
    notifHandlers[method].push(handler);
  }

  function extractJobId(result) {
    if (!result) return null;
    if (result.structuredContent && result.structuredContent.job_id)
      return result.structuredContent.job_id;
    if (result.content && result.content.length > 0) {
      try {
        var parsed = JSON.parse(result.content[0].text);
        if (parsed.job_id) return parsed.job_id;
      } catch(e) {}
    }
    return null;
  }

  function parseResultBody(result) {
    if (!result) return null;
    if (result.structuredContent) return result.structuredContent;
    if (result.content && result.content.length > 0) {
      try { return JSON.parse(result.content[0].text); } catch(e) {}
    }
    return null;
  }

  function setProgress(pct, phase, message) {
    var bar = document.getElementById('bar');
    var pctEl = document.getElementById('pct');
    var phaseEl = document.getElementById('phase');
    var msgEl = document.getElementById('msg');
    if (bar) bar.style.width = Math.max(0, Math.min(100, pct)) + '%';
    if (pctEl) pctEl.textContent = pct.toFixed(1) + '%';
    if (phaseEl) phaseEl.textContent = phase || '';
    if (msgEl) msgEl.textContent = message || '';
  }

  function showView(id) {
    ['view-progress', 'view-done', 'view-error', 'view-wait'].forEach(function(v) {
      var el = document.getElementById(v);
      if (el) el.style.display = (v === id) ? '' : 'none';
    });
  }

  async function poll() {
    if (!jobId || done) return;
    try {
      var result = await sendRequest('tools/call', {name: 'get_status', arguments: {job_id: jobId}});
      var st = parseResultBody(result);
      if (!st) { log('Could not parse status response'); return; }
      setProgress(st.progress_pct || 0, st.phase, st.message);
      if (st.status === 'completed' || st.status === 'failed' || st.status === 'canceled') {
        finish(st);
      }
    } catch(e) {
      log('Poll error: ' + (e.message || JSON.stringify(e)));
    }
  }

  async function finish(status) {
    if (done) return;
    done = true;
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }

    try {
      var result = await sendRequest('tools/call', {name: 'get_result', arguments: {job_id: jobId}});
      var body = parseResultBody(result);

      if (status.status === 'completed' && body && body.report) {
        renderReport(body.report);
        showView('view-done');
        var summary = body.report.summary_markdown || 'Legal research complete.';
        await sendRequest('ui/update-model-context', {
          content: [{type: 'text', text: JSON.stringify(body)}],
          structuredContent: body
        });
        await sendRequest('ui/message', {
          role: 'user',
          content: {type: 'text', text: 'The legal research job ' + jobId + ' is complete. Please present the results to the user.'}
        });
      } else {
        var errMsg = (body && body.error) || status.status || 'unknown error';
        var errEl = document.getElementById('err-text');
        if (errEl) errEl.textContent = errMsg;
        showView('view-error');
        await sendRequest('ui/update-model-context', {
          content: [{type: 'text', text: 'Legal research job ' + jobId + ' ended with status: ' + status.status + '. Error: ' + errMsg}],
          structuredContent: {job_id: jobId, status: status.status, error: errMsg}
        });
        await sendRequest('ui/message', {
          role: 'user',
          content: {type: 'text', text: 'The legal research job ' + jobId + ' failed with: ' + errMsg + '. Please inform the user.'}
        });
      }
    } catch(e) {
      log('Finish error: ' + (e.message || JSON.stringify(e)));
    }
  }

  function renderReport(report) {
    var el = document.getElementById('report-summary');
    if (el && report.summary_markdown) el.textContent = report.summary_markdown;
    var riskEl = document.getElementById('report-risk');
    if (riskEl && report.risk_score != null) riskEl.textContent = report.risk_score;
    var jurEl = document.getElementById('report-jur');
    if (jurEl) jurEl.textContent = report.jurisdiction || '';
    var citeEl = document.getElementById('report-citations');
    if (citeEl && report.citations) {
      citeEl.innerHTML = report.citations.map(function(c) {
        return '<div><strong>' + escapeHtml(c.title) + '</strong> — <a href="' + escapeHtml(c.url) + '" target="_blank">' + escapeHtml(c.type) + '</a></div>';
      }).join('');
    }
    var secEl = document.getElementById('report-sections');
    if (secEl && report.sections) {
      secEl.innerHTML = report.sections.map(function(s) {
        return '<h4>' + escapeHtml(s.title) + '</h4><div class="md">' + escapeHtml(s.body_markdown) + '</div>';
      }).join('');
    }
    var disEl = document.getElementById('report-disclaimer');
    if (disEl) disEl.textContent = report.disclaimer || '';
  }

  function escapeHtml(s) {
    if (!s) return '';
    return String(s).replace(/[&<>"']/g, function(c) {
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];
    });
  }

  onMessage('ui/notifications/tool-result', function(params) {
    jobId = extractJobId(params);
    if (jobId) {
      log('');
      poll();
      pollTimer = setInterval(poll, __POLL_MS__);
    } else {
      log('Waiting for job to start...');
    }
  });

  onMessage('ui/notifications/tool-cancelled', function(params) {
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
    var errEl = document.getElementById('err-text');
    if (errEl) errEl.textContent = 'Tool was cancelled: ' + (params && params.reason || 'unknown');
    showView('view-error');
  });

  onMessage('ui/resource-teardown', function(params, msg) {
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
    if (msg && msg.id != null) {
      window.parent.postMessage({jsonrpc: '2.0', id: msg.id, result: {}}, '*');
    }
  });

  sendRequest('ui/initialize', {
    protocolVersion: '2026-01-26',
    clientInfo: {name: 'legal-progress-widget', version: '1.0.0'},
    capabilities: {},
    appCapabilities: {availableDisplayModes: ['inline']}
  }).then(function() {
    sendNotification('ui/notifications/initialized', {});
    log('Connecting...');
  }).catch(function(e) {
    log('Initialize failed: ' + (e.message || JSON.stringify(e)));
  });
})();
"""


def render_widget(profile: ClientProfile) -> str:
    poll_ms = profile.poll_interval_ms or settings.widget_poll_ms
    js = _WIDGET_JS.replace("__POLL_MS__", str(poll_ms))
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Legal Research Progress</title>
<style>
  :root {{
    --bg: var(--color-background-primary, #ffffff);
    --fg: var(--color-text-primary, #1a1a1a);
    --fg2: var(--color-text-secondary, #666);
    --border: var(--color-border-primary, #e0e0e0);
    --accent: var(--color-background-info, #0066cc);
    --ok: var(--color-background-success, #1a7f37);
    --err: var(--color-background-danger, #cf222e);
    --radius: var(--border-radius-md, 8px);
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 12px;
    font-family: var(--font-sans, system-ui, sans-serif);
    background: var(--bg); color: var(--fg);
    font-size: 14px; line-height: 1.5;
  }}
  .header {{ font-weight: 600; margin-bottom: 8px; }}
  .progress-wrap {{
    background: var(--border); border-radius: var(--radius);
    height: 8px; overflow: hidden; margin: 8px 0;
  }}
  #bar {{
    height: 100%; width: 0%; background: var(--accent);
    transition: width 0.3s ease;
  }}
  .pct-row {{ display: flex; justify-content: space-between; color: var(--fg2); font-size: 12px; }}
  #phase {{ font-weight: 500; }}
  #msg {{ color: var(--fg2); font-style: italic; min-height: 1.2em; }}
  #log {{ color: var(--fg2); font-size: 12px; }}
  .report {{ margin-top: 12px; }}
  .report h4 {{ margin: 12px 0 4px; font-size: 14px; }}
  .md {{ white-space: pre-wrap; font-size: 13px; color: var(--fg2); }}
  .meta {{ display: flex; gap: 16px; margin: 8px 0; font-size: 13px; }}
  .meta span {{ color: var(--fg2); }}
  .meta strong {{ color: var(--fg); }}
  .citations {{ margin: 8px 0; font-size: 13px; }}
  .citations a {{ color: var(--accent); }}
  .disclaimer {{
    margin-top: 12px; padding: 8px; border-radius: var(--radius);
    background: var(--color-background-warning, #fff8c5);
    font-size: 11px; color: var(--fg2);
  }}
  .error-box {{ color: var(--err); font-weight: 500; }}
</style>
</head>
<body>

<div id="view-progress">
  <div class="header">Legal Research in Progress</div>
  <div class="progress-wrap"><div id="bar"></div></div>
  <div class="pct-row"><span id="phase">Starting...</span><span id="pct">0.0%</span></div>
  <div id="msg"></div>
  <div id="log">Connecting...</div>
</div>

<div id="view-done" style="display:none">
  <div class="header">Legal Research Complete</div>
  <div class="meta">
    <span>Jurisdiction: <strong id="report-jur"></strong></span>
    <span>Risk Score: <strong id="report-risk"></strong>/100</span>
  </div>
  <div class="report">
    <h4>Summary</h4>
    <div class="md" id="report-summary"></div>
    <div id="report-sections"></div>
    <h4>Citations</h4>
    <div class="citations" id="report-citations"></div>
  </div>
  <div class="disclaimer" id="report-disclaimer"></div>
</div>

<div id="view-error" style="display:none">
  <div class="header">Research Failed</div>
  <div class="error-box" id="err-text"></div>
</div>

<div id="view-wait" style="display:none">
  <div class="header">Waiting for job to start...</div>
</div>

<script>
{js}
</script>
</body>
</html>"""
