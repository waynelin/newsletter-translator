/* Newsletter Translator — frontend app */

const $ = (id) => document.getElementById(id);

async function loadConfig() {
  try {
    const res = await fetch('/api/config');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    $('relay-email').value = data.relay_email;

    const srcSel = $('source-lang');
    const tgtSel = $('target-lang');
    for (const opt of srcSel.options) opt.selected = opt.value === data.source_lang;
    for (const opt of tgtSel.options) opt.selected = opt.value === data.target_lang;

    $('dest-email').value = data.dest_email;
  } catch (err) {
    console.error('Failed to load config:', err);
  }
}

async function saveConfig(e) {
  e.preventDefault();
  const btn = $('save-btn');
  const feedback = $('save-feedback');

  btn.disabled = true;
  feedback.className = 'save-feedback hidden';
  feedback.textContent = '';

  const payload = {
    source_lang: $('source-lang').value,
    target_lang: $('target-lang').value,
    dest_email: $('dest-email').value.trim(),
  };

  try {
    const res = await fetch('/api/config', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    feedback.textContent = 'Saved!';
    feedback.className = 'save-feedback success';
  } catch (err) {
    feedback.textContent = `Error: ${err.message}`;
    feedback.className = 'save-feedback error';
  } finally {
    btn.disabled = false;
    setTimeout(() => { feedback.className = 'save-feedback hidden'; }, 3000);
  }
}

function copyRelayEmail() {
  const val = $('relay-email').value;
  if (!val) return;
  navigator.clipboard.writeText(val).then(() => {
    const fb = $('copy-feedback');
    fb.classList.remove('hidden');
    setTimeout(() => fb.classList.add('hidden'), 2000);
  });
}

function formatDate(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toLocaleString();
}

function statusBadge(status) {
  const cls = `status-badge status-${status}`;
  return `<span class="${cls}">${status}</span>`;
}

function truncate(str, n = 60) {
  if (!str) return '—';
  return str.length > n ? str.slice(0, n) + '…' : str;
}

async function loadLogs() {
  const container = $('logs-container');
  container.innerHTML = '<p class="loading">Loading...</p>';

  try {
    const res = await fetch('/api/logs?limit=20');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    if (data.items.length === 0) {
      container.innerHTML = '<p class="empty-state">No emails processed yet. Forward a newsletter to your relay address to get started.</p>';
      return;
    }

    const rows = data.items.map(log => `
      <tr>
        <td>${formatDate(log.received_at)}</td>
        <td title="${log.from_addr}">${truncate(log.from_addr, 30)}</td>
        <td title="${log.subject}">${truncate(log.subject, 50)}</td>
        <td>${statusBadge(log.status)}</td>
        <td>${log.input_tokens != null ? log.input_tokens.toLocaleString() : '—'}</td>
        <td>${log.cache_read_tokens != null ? log.cache_read_tokens.toLocaleString() : '—'}</td>
      </tr>
    `).join('');

    container.innerHTML = `
      <table>
        <thead>
          <tr>
            <th>Received</th>
            <th>From</th>
            <th>Subject</th>
            <th>Status</th>
            <th>Tokens</th>
            <th>Cache Hits</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
      <p style="margin-top:10px;font-size:0.8rem;color:#9ca3af;">
        Showing ${data.items.length} of ${data.total} emails
      </p>
    `;
  } catch (err) {
    container.innerHTML = `<p class="loading">Failed to load logs: ${err.message}</p>`;
  }
}

// Init
document.addEventListener('DOMContentLoaded', () => {
  loadConfig();
  loadLogs();

  $('config-form').addEventListener('submit', saveConfig);
  $('copy-btn').addEventListener('click', copyRelayEmail);
  $('refresh-btn').addEventListener('click', loadLogs);
});
