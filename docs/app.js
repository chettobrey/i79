// Escape user-derived content before inserting into innerHTML.
function escHtml(str) {
  return String(str ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

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
  dataMinTs: 0,
  dataMaxTs: 0,
  dateFromTs: 0,
  dateToTs: 0,
};

const listEl = document.getElementById("incident-list");
const updatedEl = document.getElementById("updated");
const statIncidents = document.getElementById("stat-incidents");
const statFatalities = document.getElementById("stat-fatalities");
const statConstruction = document.getElementById("stat-construction");
const statOfficial = document.getElementById("stat-official");
const timelineEl = document.getElementById("timeline-chart");
const timelineCaptionEl = document.getElementById("timeline-caption");
const dateFromInput = document.getElementById("date-from");
const dateToInput = document.getElementById("date-to");
const dateFromLabel = document.getElementById("date-from-label");
const dateToLabel = document.getElementById("date-to-label");
const dateRangeSummary = document.getElementById("date-range-summary");

function formatDate(iso) {
  if (!iso) return "Unknown date";
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function formatMonthYear(ts) {
  return new Date(ts).toLocaleDateString(undefined, { month: "short", year: "numeric" });
}

function sliderTsFromValue(value) {
  return state.dataMinTs + parseInt(value) * 86400000;
}

function updateSliderLabels() {
  const fromText = formatMonthYear(state.dateFromTs);
  const toText = formatMonthYear(state.dateToTs);
  dateFromLabel.textContent = fromText;
  dateToLabel.textContent = toText;
  dateRangeSummary.textContent = `${fromText} – ${toText}`;
  dateFromInput.setAttribute("aria-valuenow", dateFromInput.value);
  dateFromInput.setAttribute("aria-valuetext", fromText);
  dateToInput.setAttribute("aria-valuenow", dateToInput.value);
  dateToInput.setAttribute("aria-valuetext", toText);
}

function initSlider() {
  const timestamps = state.incidents
    .filter((i) => i.published_at)
    .map((i) => new Date(i.published_at).getTime())
    .filter((t) => !isNaN(t));

  if (timestamps.length === 0) return;

  state.dataMinTs = Math.min(...timestamps);
  state.dataMaxTs = Math.max(...timestamps);
  state.dateFromTs = state.dataMinTs;
  state.dateToTs = state.dataMaxTs;

  const totalDays = Math.ceil((state.dataMaxTs - state.dataMinTs) / 86400000);

  for (const input of [dateFromInput, dateToInput]) {
    input.min = 0;
    input.max = totalDays;
    input.setAttribute("aria-valuemin", 0);
    input.setAttribute("aria-valuemax", totalDays);
  }
  dateFromInput.value = 0;
  dateToInput.value = totalDays;

  updateSliderLabels();
}

function applyFilter(incidents, mode, fromTs, toTs) {
  let rows = incidents.filter((incident) => {
    if (!incident.published_at) return false;
    const ts = new Date(incident.published_at).getTime();
    return !isNaN(ts) && ts >= fromTs && ts <= toTs + 86400000;
  });

  if (mode === "construction") return rows.filter((x) => x.construction_related);
  if (mode === "fatal") return rows.filter((x) => (x.verified_fatalities ?? x.suspected_fatalities) > 0);
  if (mode === "official") return rows.filter((x) => x.source_type === "official_wv511");
  return rows;
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
      return `<rect x="${x.toFixed(2)}" y="${y.toFixed(2)}" width="${barW.toFixed(2)}" height="${h.toFixed(2)}" fill="#2f5b8f"><title>${escHtml(label)}</title></rect>`;
    })
    .join("");

  const labels = stats
    .map((row, i) => {
      if (stats.length > 9 && i % 2 === 1) return "";
      const x = padLeft + i * step + step / 2;
      const y = height - 16;
      return `<text x="${x.toFixed(2)}" y="${y}" text-anchor="middle" fill="#5d6470" font-size="11">${escHtml(monthLabel(row.key))}</text>`;
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

function makePopupEl(incident) {
  const div = document.createElement("div");
  const strong = document.createElement("strong");
  strong.textContent = incident.title;
  div.appendChild(strong);
  div.appendChild(document.createElement("br"));
  div.appendChild(document.createTextNode(formatDate(incident.published_at)));
  div.appendChild(document.createElement("br"));
  div.appendChild(document.createTextNode(incident.location_text));
  div.appendChild(document.createElement("br"));
  const a = document.createElement("a");
  a.href = incident.url;
  a.target = "_blank";
  a.rel = "noopener noreferrer";
  a.textContent = "Source";
  div.appendChild(a);
  return div;
}

function render() {
  const rows = applyFilter(state.incidents, state.mode, state.dateFromTs, state.dateToTs);

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
        title: incident.title,
      }).bindPopup(makePopupEl(incident));
      markersLayer.addLayer(marker);
    }

    const li = document.createElement("li");
    const fatalityCount = incident.verified_fatalities ?? incident.suspected_fatalities ?? 0;
    li.innerHTML = `
      <a href="${escHtml(incident.url)}" target="_blank" rel="noopener noreferrer">${escHtml(incident.title)}</a>
      <div class="meta">${escHtml(formatDate(incident.published_at))} | ${escHtml(incident.source)} | ${escHtml(incident.location_text)}</div>
      <div>${escHtml(incident.summary || "")}</div>
      <span class="badge">${incident.source_type === "official_wv511" ? "Official WV511" : "News-Derived"}</span>
      ${incident.verification_status ? `<span class="badge">${escHtml(incident.verification_status)}</span>` : ""}
      ${incident.construction_related ? '<span class="badge construction">Construction Related</span>' : ""}
      ${fatalityCount > 0 ? `<span class="badge fatal">Fatalities: ${fatalityCount}</span>` : ""}
      ${incident.notes ? `<div class="meta">${escHtml(incident.notes)}</div>` : ""}
    `;
    listEl.appendChild(li);
  });
}

// Date range slider handlers
dateFromInput.addEventListener("input", () => {
  if (parseInt(dateFromInput.value) > parseInt(dateToInput.value)) {
    dateFromInput.value = dateToInput.value;
  }
  state.dateFromTs = sliderTsFromValue(dateFromInput.value);
  updateSliderLabels();
  render();
  window.goatcounter?.count({ path: "/date-range", title: "Date range changed" });
});

dateToInput.addEventListener("input", () => {
  if (parseInt(dateToInput.value) < parseInt(dateFromInput.value)) {
    dateToInput.value = dateFromInput.value;
  }
  state.dateToTs = sliderTsFromValue(dateToInput.value);
  updateSliderLabels();
  render();
  window.goatcounter?.count({ path: "/date-range", title: "Date range changed" });
});

// Filter button handlers
for (const btn of document.querySelectorAll("[data-mode]")) {
  btn.addEventListener("click", () => {
    state.mode = btn.dataset.mode;
    document.querySelectorAll("[data-mode]").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    render();
    window.goatcounter?.count({ path: `/filter/${state.mode}`, title: `Filter: ${state.mode}` });
  });
}

async function main() {
  const res = await fetch("./incidents.json", { cache: "no-store" });
  const payload = await res.json();
  state.incidents = payload.incidents || [];

  if (payload.summary?.generated_at) {
    updatedEl.textContent = `Data refreshed ${new Date(payload.summary.generated_at).toLocaleString()}`;
  }

  initSlider();
  render();
}

main().catch((err) => {
  updatedEl.textContent = `Unable to load data: ${err.message}`;
});
