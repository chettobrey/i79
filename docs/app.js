const CENTER = [39.38, -80.2];
const map = L.map("map").setView(CENTER, 9);

L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 18,
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
}).addTo(map);

const markersLayer = L.layerGroup().addTo(map);

const state = {
  incidents: [],
  mode: "all",
};

const listEl = document.getElementById("incident-list");
const updatedEl = document.getElementById("updated");
const statIncidents = document.getElementById("stat-incidents");
const statFatalities = document.getElementById("stat-fatalities");
const statConstruction = document.getElementById("stat-construction");
const statOfficial = document.getElementById("stat-official");
const timelineEl = document.getElementById("timeline-chart");
const timelineCaptionEl = document.getElementById("timeline-caption");

function formatDate(iso) {
  if (!iso) return "Unknown date";
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function applyFilter(incidents, mode) {
  if (mode === "construction") {
    return incidents.filter((x) => x.construction_related);
  }
  if (mode === "fatal") {
    return incidents.filter((x) => (x.verified_fatalities ?? x.suspected_fatalities) > 0);
  }
  if (mode === "official") {
    return incidents.filter((x) => x.source_type === "official_wv511");
  }
  return incidents;
}

function markerColor(incident) {
  if (incident.suspected_fatalities > 0) return "#b5282e";
  if (incident.construction_related) return "#f08a24";
  return "#2f5b8f";
}

function monthKey(iso) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}`;
}

function monthLabel(key) {
  const [year, month] = key.split("-").map(Number);
  const d = new Date(Date.UTC(year, month - 1, 1));
  return d.toLocaleDateString(undefined, { month: "short", year: "2-digit" });
}

function renderTimeline(rows) {
  const buckets = new Map();
  rows.forEach((row) => {
    const key = monthKey(row.published_at);
    if (!key) return;
    const current = buckets.get(key) || { incidents: 0, fatalities: 0 };
    current.incidents += 1;
    current.fatalities += row.verified_fatalities ?? row.suspected_fatalities ?? 0;
    buckets.set(key, current);
  });

  const months = Array.from(buckets.keys()).sort().slice(-18);
  if (months.length === 0) {
    timelineEl.innerHTML = "";
    timelineCaptionEl.textContent = "No dated records in current filter.";
    return;
  }

  const stats = months.map((m) => ({ key: m, ...buckets.get(m) }));
  const maxIncidents = Math.max(1, ...stats.map((x) => x.incidents));
  const maxFatalities = Math.max(1, ...stats.map((x) => x.fatalities));

  const width = 960;
  const height = 220;
  const padLeft = 44;
  const padRight = 16;
  const padTop = 16;
  const padBottom = 44;
  const chartW = width - padLeft - padRight;
  const chartH = height - padTop - padBottom;
  const step = chartW / stats.length;
  const barW = Math.max(6, step * 0.58);

  const linePoints = stats
    .map((row, i) => {
      const x = padLeft + i * step + step / 2;
      const y = padTop + chartH - (row.fatalities / maxFatalities) * chartH;
      return `${x},${y}`;
    })
    .join(" ");

  const bars = stats
    .map((row, i) => {
      const x = padLeft + i * step + (step - barW) / 2;
      const h = (row.incidents / maxIncidents) * chartH;
      const y = padTop + chartH - h;
      const label = `${monthLabel(row.key)} incidents ${row.incidents}, fatalities ${row.fatalities}`;
      return `<rect x="${x.toFixed(2)}" y="${y.toFixed(2)}" width="${barW.toFixed(2)}" height="${h.toFixed(2)}" fill="#2f5b8f"><title>${label}</title></rect>`;
    })
    .join("");

  const labels = stats
    .map((row, i) => {
      if (stats.length > 9 && i % 2 === 1) return "";
      const x = padLeft + i * step + step / 2;
      const y = height - 16;
      return `<text x="${x.toFixed(2)}" y="${y}" text-anchor="middle" fill="#5d6470" font-size="11">${monthLabel(row.key)}</text>`;
    })
    .join("");

  const legend = `
    <rect x="${padLeft}" y="${height - 34}" width="11" height="11" fill="#2f5b8f"></rect>
    <text x="${padLeft + 16}" y="${height - 24}" fill="#5d6470" font-size="12">Incidents</text>
    <line x1="${padLeft + 90}" y1="${height - 29}" x2="${padLeft + 106}" y2="${height - 29}" stroke="#b5282e" stroke-width="3"></line>
    <text x="${padLeft + 112}" y="${height - 24}" fill="#5d6470" font-size="12">Fatalities</text>
  `;

  timelineEl.innerHTML = `
    <line x1="${padLeft}" y1="${padTop + chartH}" x2="${width - padRight}" y2="${padTop + chartH}" stroke="#d8d1c4" />
    ${bars}
    <polyline points="${linePoints}" fill="none" stroke="#b5282e" stroke-width="2.5" />
    ${labels}
    ${legend}
  `;
  timelineCaptionEl.textContent = `Showing ${stats.length} month(s) for current filter.`;
}

function render() {
  const rows = applyFilter(state.incidents, state.mode);

  statIncidents.textContent = rows.length;
  statFatalities.textContent = rows.reduce((n, row) => n + (row.verified_fatalities ?? row.suspected_fatalities ?? 0), 0);
  statConstruction.textContent = rows.filter((x) => x.construction_related).length;
  statOfficial.textContent = rows.filter((x) => x.source_type === "official_wv511").length;
  renderTimeline(rows);

  markersLayer.clearLayers();
  listEl.innerHTML = "";

  rows.forEach((incident) => {
    if (typeof incident.lat === "number" && typeof incident.lon === "number") {
      const marker = L.circleMarker([incident.lat, incident.lon], {
        radius: 8,
        weight: 2,
        color: markerColor(incident),
        fillOpacity: 0.65,
      }).bindPopup(`
        <strong>${incident.title}</strong><br>
        ${formatDate(incident.published_at)}<br>
        ${incident.location_text}<br>
        <a href="${incident.url}" target="_blank" rel="noopener">Source</a>
      `);
      markersLayer.addLayer(marker);
    }

    const li = document.createElement("li");
    const fatalityCount = incident.verified_fatalities ?? incident.suspected_fatalities ?? 0;
    li.innerHTML = `
      <a href="${incident.url}" target="_blank" rel="noopener">${incident.title}</a>
      <div class="meta">${formatDate(incident.published_at)} | ${incident.source} | ${incident.location_text}</div>
      <div>${incident.summary || ""}</div>
      <span class="badge">${incident.source_type === "official_wv511" ? "Official WV511" : "News-Derived"}</span>
      ${incident.verification_status ? `<span class="badge">${incident.verification_status}</span>` : ""}
      ${incident.construction_related ? '<span class="badge construction">Construction Related</span>' : ""}
      ${fatalityCount > 0 ? `<span class="badge fatal">Fatalities: ${fatalityCount}</span>` : ""}
      ${incident.notes ? `<div class="meta">${incident.notes}</div>` : ""}
    `;
    listEl.appendChild(li);
  });
}

async function main() {
  const res = await fetch("./incidents.json", { cache: "no-store" });
  const payload = await res.json();
  state.incidents = payload.incidents || [];

  if (payload.summary?.generated_at) {
    updatedEl.textContent = `Data refreshed ${new Date(payload.summary.generated_at).toLocaleString()}`;
  }

  render();
}

for (const btn of document.querySelectorAll("[data-mode]")) {
  btn.addEventListener("click", () => {
    state.mode = btn.dataset.mode;
    document.querySelectorAll("[data-mode]").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    render();
  });
}

main().catch((err) => {
  updatedEl.textContent = `Unable to load data: ${err.message}`;
});
