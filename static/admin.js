const API_BASE_URL = "";

document.addEventListener("DOMContentLoaded", () => {
  document.querySelector("#load").addEventListener("click", loadMetrics);
  document.querySelector("#cleanup").addEventListener("click", cleanup);
});

async function loadMetrics() {
  const data = await adminFetch("/api/admin/metrics");
  render(data);
}

async function cleanup() {
  const data = await adminFetch("/api/admin/cleanup", { method: "POST" });
  render(data);
}

async function adminFetch(url, options = {}) {
  const token = document.querySelector("#token").value;
  const response = await fetch(`${API_BASE_URL}${url}`, {
    credentials: "omit",
    ...options,
    headers: { "x-admin-token": token, ...(options.headers || {}) },
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Admin request failed");
  return data;
}

function render(data) {
  document.querySelector("#metrics").innerHTML = `
    <article class="product-card">
      <pre>${escapeHtml(JSON.stringify(data, null, 2))}</pre>
    </article>
  `;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}
