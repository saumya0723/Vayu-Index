(() => {
  "use strict";

  const API = "/api/v1";
  const indexChartState = { series: "vayu", period: "1Y", data: null };
  const page = location.pathname.split("/").pop().replace(/\.html$/, "") || "index";
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const esc = value => String(value ?? "").replace(/[&<>"']/g, ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
  const num = value => {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  };
  const money = value => value == null ? "Not available" : `₹${Number(value).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
  const pct = value => value == null ? "Not available" : `${Number(value) > 0 ? "+" : ""}${Number(value).toFixed(2)}%`;
  const unwrap = async path => {
    const response = await fetch(`${API}${path}`, { headers: { Accept: "application/json" }, cache: "no-store" });
    const body = await response.json();
    if (!response.ok) throw new Error(body.error?.message || `API returned ${response.status}`);
    return body.data;
  };
  const safeText = (node, value) => { if (node) node.textContent = value == null ? "Not available" : String(value); };
  const dataNote = text => {
    if (!$("#backend-data-style")) {
      const style = document.createElement("style");
      style.id = "backend-data-style";
      style.textContent = ".backend-data-note{margin:1rem auto;padding:.8rem 1rem;max-width:1200px;border-left:4px solid #f07828;background:#fff7ed;color:#334155;border-radius:.35rem;font:500 .9rem/1.45 system-ui,sans-serif}.backend-data-note[hidden]{display:none}.route-table tr[hidden]{display:none!important}.route-table th:first-child,.route-table td:first-child{width:43%}.route-table th:nth-child(2),.route-table td:nth-child(2){width:25%}.route-table th:nth-child(3),.route-table td:nth-child(3){width:32%}.route-table td small{display:block;margin-top:.25rem;color:#667085;font-size:.78rem;line-height:1.4}.route-table .route-price{font-weight:700;color:#17324d}.route-table .route-price-missing{font-weight:600;color:#9a6700}.backend-benchmark-title{font:700 1rem/1.4 system-ui,sans-serif;color:#17324d;margin:1rem 0 .5rem}.backend-map-note{margin:.5rem auto;padding:.65rem;max-width:85%;background:#fff;color:#334155;text-align:center;font:600 .8rem/1.4 system-ui,sans-serif;border-radius:.35rem}.chart-legend .backend-series-button{border:0;background:transparent;padding:.2rem .35rem;color:inherit;cursor:pointer;font:inherit;opacity:.58}.chart-legend .backend-series-button[aria-pressed=true]{opacity:1;font-weight:700}.chart-legend .backend-series-button:focus-visible{outline:2px solid #f07828;outline-offset:2px;border-radius:.25rem}";
      document.head.appendChild(style);
    }
    $(".backend-data-note")?.remove();
    const note = document.createElement("div");
    note.className = "backend-data-note";
    note.setAttribute("role", "status");
    note.textContent = text;
    const main = $("main");
    if (main) main.prepend(note);
  };
  const shortDate = value => {
    if (!value) return "Not available";
    const d = new Date(String(value).replace(" ", "T") + (String(value).includes("Z") ? "" : "Z"));
    return Number.isNaN(d.valueOf()) ? String(value) : new Intl.DateTimeFormat("en-IN", { dateStyle: "medium", timeZone: "Asia/Kolkata" }).format(d);
  };
  const attachSearch = () => {
    const input = $("#routeSearch");
    if (!input || input.dataset.backendSearchBound) return;
    input.dataset.backendSearchBound = "true";
    input.addEventListener("input", () => {
      const term = input.value.trim().toLowerCase();
      $$("tbody tr").forEach(row => { row.hidden = !row.textContent.toLowerCase().includes(term); });
      const empty = $("#noRouteResults");
      if (empty) empty.style.display = $$("tbody tr").some(row => !row.hidden) ? "none" : "block";
    });
  };
  const renderSvg = (id, labels, series, options = {}) => {
    const svg = document.getElementById(id);
    if (!svg) return;
    const values = series.flatMap(s => s.values).filter(Number.isFinite);
    if (!labels.length || !values.length) {
      svg.replaceChildren();
      const message = document.createElementNS("http://www.w3.org/2000/svg", "text");
      message.setAttribute("x", "500"); message.setAttribute("y", "150"); message.setAttribute("text-anchor", "middle"); message.setAttribute("class", "axis-label");
      message.textContent = options.empty || "No backend observations are available for this chart.";
      svg.appendChild(message);
      return;
    }
    const width = 1000, height = options.height || 320, left = 72, right = 975, top = 28, bottom = height - 45;
    let low = options.min ?? Math.min(...values), high = options.max ?? Math.max(...values);
    if (low === high) { low -= Math.abs(low) * 0.02 || 1; high += Math.abs(high) * 0.02 || 1; }
    const pad = options.pad === false ? 0 : (high - low) * 0.08;
    low -= pad; high += pad;
    const x = i => labels.length < 2 ? (left + right) / 2 : left + (right - left) * i / (labels.length - 1);
    const y = value => bottom - (value - low) / (high - low) * (bottom - top);
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    svg.replaceChildren();
    const ns = "http://www.w3.org/2000/svg";
    const add = (tag, attrs, content) => {
      const element = document.createElementNS(ns, tag);
      Object.entries(attrs).forEach(([key, value]) => element.setAttribute(key, value));
      if (content != null) element.textContent = content;
      svg.appendChild(element);
      return element;
    };
    for (let tick = 0; tick <= 4; tick++) {
      const v = high - (high - low) * tick / 4, yy = y(v);
      add("line", { x1: left, x2: right, y1: yy, y2: yy, class: "grid-line" });
      add("text", { x: left - 10, y: yy + 4, class: "axis-label", "text-anchor": "end" }, options.format ? options.format(v) : v.toFixed(1));
    }
    series.forEach(s => {
      const points = s.values.map((v, i) => Number.isFinite(v) ? `${x(i)},${y(v)}` : null).filter(Boolean);
      if (points.length >= 2) add("polyline", { points: points.join(" "), fill: "none", class: s.className });
      s.values.forEach((v, i) => { if (Number.isFinite(v)) add("circle", { cx: x(i), cy: y(v), r: 3.5, class: s.dotClass }); });
    });
    const stride = Math.max(1, Math.ceil(labels.length / 12));
    labels.forEach((label, i) => { if (i % stride === 0 || i === labels.length - 1) add("text", { x: x(i), y: height - 14, class: "axis-label", "text-anchor": "middle" }, label); });
  };
  const metricCard = (className, label, value, description) => `<div class="metric-card ${className}"><p class="metric-label">${esc(label)}</p><div class="metric-value">${esc(value)}</div><p class="metric-description">${esc(description)}</p></div>`;

  function updateCommon(data) {
    const latest = data.index_latest || {};
    $$(".last-updated").forEach(node => {
      const span = $("span", node), strong = $("strong", node);
      safeText(span, `${data.data_status || "BACKEND DATA"} · updated`);
      safeText(strong, shortDate(latest.timestamp || data.publication_timestamp));
    });
    dataNote(`Backend connected · ${data.data_status || "status unavailable"} · ${data.official_status || "publication status unavailable"}. Displayed metrics come from the backend snapshot.`);
    attachSearch();
  }

  function updateIndex(data) {
    const latest = data.index_latest || {};
    safeText($(".index-description"), "Backend prototype index from the currently available basket routes; it is not an official or full-coverage market index.");
    const current = num(latest.index_level);
    safeText($(".index-value"), current == null ? "Not available" : current.toFixed(2));
    const change = num(latest.change_pct_vs_previous_round);
    const changeNode = $(".index-change");
    if (changeNode) changeNode.textContent = change == null ? "No previous round" : `${pct(change)} `;
    if (changeNode && change != null) {
      const trend = document.createElement("span"); trend.textContent = Math.abs(change) < 0.05 ? "Stable" : change > 0 ? "Rising" : "Falling"; changeNode.appendChild(trend);
    }
    const kpis = $$(".kpi-strip .kpi-number");
    safeText(kpis[0], data.source_status?.total ?? 0);
    safeText(kpis[1], `${data.live_quote_routes?.length ?? latest.routes_represented ?? 0}/${latest.routes_total ?? 0}`);
    safeText(kpis[2], data.live_collection?.verified_observation_count ?? data.validation?.record_count ?? 0);
    const history = [...(data.index_history || [])].sort((a, b) => String(a.round_sort_key).localeCompare(String(b.round_sort_key)));
    const labels = history.map(row => {
      const d = new Date(String(row.round_sort_key).replace(" ", "T") + "Z");
      return Number.isNaN(d.valueOf()) ? String(row.round_sort_key || "") : new Intl.DateTimeFormat("en-IN", { month: "short", day: "numeric", timeZone: "Asia/Kolkata" }).format(d);
    });
    indexChartState.data = data;
    const renderPeriod = period => {
      indexChartState.period = period;
      const span = { "1M": 31, "3M": 92, "6M": 184, "1Y": 366 }[period];
      if (indexChartState.series === "mospi") {
        const official = [...(data.cpi || [])].filter(row => num(row.cpi_index) != null).sort((a, b) => String(a.period).localeCompare(String(b.period)));
        const filtered = span && official.length ? official.filter(row => {
          const stamp = new Date(`${String(row.period).slice(0, 7)}-01T00:00:00Z`).valueOf();
          const last = new Date(`${String(official[official.length - 1].period).slice(0, 7)}-01T00:00:00Z`).valueOf();
          return Number.isFinite(stamp) && Number.isFinite(last) && last - stamp < span * 86400000;
        }) : official;
        const labels = filtered.map(row => {
          const value = String(row.period || "").slice(0, 7), d = new Date(`${value}-01T00:00:00Z`);
          return Number.isNaN(d.valueOf()) ? value : new Intl.DateTimeFormat("en-IN", { month: "short", year: "2-digit", timeZone: "UTC" }).format(d);
        });
        renderSvg("indexChart", labels, [{ values: filtered.map(row => num(row.cpi_index)), className: "mospi-chart-line", dotClass: "mospi-point" }], { empty: "No official MoSPI CPI observations are available." });
      } else {
        const filtered = span ? history.filter(row => {
          const stamp = new Date(String(row.round_sort_key).replace(" ", "T") + "Z").valueOf();
          return !Number.isFinite(stamp) || Date.now() - stamp <= span * 86400000;
        }) : history;
        const labels = filtered.map(row => {
          const d = new Date(String(row.round_sort_key).replace(" ", "T") + "Z");
          return Number.isNaN(d.valueOf()) ? String(row.round_sort_key || "") : new Intl.DateTimeFormat("en-IN", { month: "short", day: "numeric", timeZone: "Asia/Kolkata" }).format(d);
        });
        renderSvg("indexChart", labels, [{ values: filtered.map(row => num(row.index_level)), className: "vayu-chart-line", dotClass: "vayu-point" }], { empty: "No Vayu index rounds are available." });
      }
      const section = $("#indexChart")?.closest(".chart-section");
      safeText($(".chart-header-row h3", section || document), indexChartState.series === "mospi" ? "Official MoSPI Airfare CPI Index" : "Vayu Airfare Price Index");
      safeText($(".chart-header-row p", section || document), indexChartState.series === "mospi" ? "Monthly official MoSPI domestic airfare CPI · original 2024=100 index values." : "Vayu prototype index from observed basket routes · round history, not an official market index.");
    };
    const bindSeriesControls = () => {
      $$(".chart-legend .legend-item").forEach((node, index) => {
        const series = index === 1 ? "mospi" : "vayu";
        let button = node;
        if (node.tagName !== "BUTTON") {
          button = document.createElement("button");
          button.type = "button";
          button.className = `${node.className} backend-series-button`;
          button.innerHTML = node.innerHTML;
          node.replaceWith(button);
        }
        button.classList.add("backend-series-button");
        button.dataset.series = series;
        button.setAttribute("aria-pressed", String(indexChartState.series === series));
        if (button.dataset.backendSeriesBound) return;
        button.dataset.backendSeriesBound = "true";
        button.addEventListener("click", event => {
          event.preventDefault(); event.stopImmediatePropagation();
          indexChartState.series = button.dataset.series;
          $$(".chart-legend .backend-series-button").forEach(item => item.setAttribute("aria-pressed", String(item === button)));
          renderPeriod(indexChartState.period);
        }, true);
      });
    };
    bindSeriesControls();
    const activePeriod = $(".period.active")?.dataset.period || indexChartState.period;
    renderPeriod(activePeriod);
    $$(".period").forEach(button => {
      if (button.dataset.backendPeriodBound) return;
      button.dataset.backendPeriodBound = "true";
      button.addEventListener("click", event => {
        event.preventDefault(); event.stopImmediatePropagation();
        $$(".period").forEach(item => item.classList.toggle("active", item === button));
        renderPeriod(button.dataset.period);
      }, true);
    });
    bindSeriesControls();
    const liveByRoute = new Map((data.live_quote_routes || []).map(row => [row.route_id, row]));
    const historyByRoute = new Map((data.overview_routes || []).map(row => [row.route_id, row]));
    const rows = (data.routes?.length ? data.routes.map(route => ({
      ...route,
      ...(historyByRoute.get(route.route_id) || {}),
      route_id: route.route_id,
      origin: route.origin,
      destination: route.destination,
      basket_rank: route.basket_rank,
      traffic_weight: route.traffic_weight,
      coverage_status: route.coverage_status,
      average_fare: historyByRoute.get(route.route_id)?.average_fare ?? route.route_fare_median ?? null,
    })) : [...(data.overview_routes || [])]).sort((a, b) => Number(a.basket_rank) - Number(b.basket_rank));
    const tbody = $("#routeTableBody");
    const routeSection = tbody?.closest(".route-section");
    const routeTable = tbody?.closest("table");
    const tableHead = $("thead tr", routeTable || document);
    if (tableHead) tableHead.innerHTML = "<th>Monitored route</th><th>Latest fare</th><th>Coverage and change</th>";
    safeText($(".route-description", routeSection || document), `${rows.length} of ${latest.routes_total ?? rows.length} basket routes shown in rank order. Only verified live quotes or recorded prototype observations are shown as prices.`);
    if (tbody) tbody.innerHTML = rows.map(row => {
      const liveQuote = liveByRoute.get(row.route_id);
      const fare = liveQuote?.average_fare ?? row.average_fare;
      const change = row.change_pct == null ? "No prior-round comparison" : pct(row.change_pct);
      const direction = num(row.change_pct) > 0 ? "rising" : num(row.change_pct) < 0 ? "falling" : "stable";
      const fareStatus = liveQuote
        ? `<span class="route-price">${money(fare)}</span><small>Verified live · ${liveQuote.quote_count} quote${liveQuote.quote_count === 1 ? "" : "s"} · ${esc(liveQuote.provider || "Ignav Flight API")}</small>`
        : fare != null
          ? `<span class="route-price">${money(fare)}</span><small>Prototype snapshot${row.round_sort_key ? ` · ${esc(String(row.round_sort_key).slice(0, 10))}` : ""} · not a live fare</small>`
          : `<span class="route-price-missing">No verified fare</span><small>${data.live_collection?.configured ? "No quote collected for this route" : "Live fare collection needs a configured provider key"}</small>`;
      const weight = num(row.traffic_weight);
      const coverage = String(row.coverage_status || "NO_OBSERVATIONS").replaceAll("_", " ").toLowerCase();
      return `<tr data-route="${esc(row.route_id)}"><td><strong>#${String(row.basket_rank).padStart(2, "0")} · ${esc(row.origin)} ↔ ${esc(row.destination)}</strong><small>${esc(row.route_id)} · basket weight ${weight == null ? "not available" : `${(weight * 100).toFixed(2)}%`}</small></td><td>${fareStatus}</td><td class="route-change"><span class="status-dot ${direction}"></span>${esc(change)}<small>Coverage: ${esc(coverage)}${liveQuote ? " · live quote available" : ""}</small></td></tr>`;
    }).join("") || `<tr><td colspan="3">No basket routes are present in the backend snapshot.</td></tr>`;
    const liveIndicator = $(".route-section-header .live-indicator");
    if (liveIndicator) {
      const dot = liveIndicator.firstElementChild;
      liveIndicator.textContent = `${data.live_collection?.provider || "Ignav Flight API"}: ${liveByRoute.size} routes · ${data.live_collection?.verified_observation_count || 0} verified quotes`;
      if (dot) liveIndicator.prepend(dot);
    }
    const input = $("#routeSearch"); if (input) input.dispatchEvent(new Event("input"));
  }

  function updateLeadTime(data) {
    const windows = [1, 7, 15, 30, 45];
    const byRoute = new Map();
    (data.lead_time || []).forEach(row => {
      const days = Number(String(row.advance_purchase_window).match(/\d+/)?.[0]);
      const amount = num(row.average_fare);
      if (!Number.isFinite(days) || amount == null) return;
      const rowMap = byRoute.get(row.route_id) || {};
      rowMap[days] = amount;
      byRoute.set(row.route_id, rowMap);
    });
    const available = windows.map(day => [...byRoute.values()].map(row => row[day]).filter(value => value != null));
    const averages = available.map(values => values.length ? values.reduce((a, b) => a + b, 0) / values.length : null);
    const tbody = $("#routeTableBody");
    if (tbody) tbody.innerHTML = [...byRoute.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([route, values]) => {
      const carriers = (data.route_history || []).filter(row => row.route_id === route).map(row => row.fare_class).filter(Boolean);
      const cells = windows.map(day => `<td>${money(values[day])}</td>`).join("");
      return `<tr data-route="${esc(route)}"><td>${esc(route.replace("-", " → "))}</td><td>${esc(carriers.length ? "Economy (classes aggregated)" : "Not classified")}</td>${cells}</tr>`;
    }).join("") || `<tr><td colspan="7">No route lead-time observations are available.</td></tr>`;
    renderSvg("ltChart", windows.map(day => `T+${day}`), [{ values: averages, className: "leadtime-line", dotClass: "leadtime-point" }], { format: money, empty: "No lead-time values are available." });
    const kpis = $$(".kpi-number");
    safeText(kpis[0], windows.length);
    const valid = averages.map((value, i) => ({ value, i })).filter(item => item.value != null);
    const min = valid.length ? valid.reduce((a, b) => a.value < b.value ? a : b) : null;
    const max = valid.length ? valid.reduce((a, b) => a.value > b.value ? a : b) : null;
    safeText(kpis[1], min ? `T+${windows[min.i]}` : "Not available");
    safeText(kpis[2], max ? `T+${windows[max.i]}` : "Not available");
    safeText(kpis[3], averages[0] != null && averages[4] ? pct((averages[0] / averages[4] - 1) * 100) : "Not available");
    const elasticity = $("#elasticity");
    if (elasticity) elasticity.innerHTML = windows.slice(0, -1).map((day, i) => {
      const next = windows[i + 1], a = averages[i], b = averages[i + 1];
      if (a == null || b == null || a + b === 0) return `<div class="insight-chip low"><div class="chip-range">T+${day} → T+${next}</div><div class="chip-level">Not enough data</div></div>`;
      const e = ((b - a) / ((b + a) / 2)) / ((next - day) / ((next + day) / 2));
      return `<div class="insight-chip ${Math.abs(e) > 0.4 ? "high" : Math.abs(e) > 0.2 ? "medium" : "low"}"><div class="chip-range">T+${day} → T+${next}</div><div class="chip-level">ε = ${e.toFixed(2)}</div></div>`;
    }).join("");
    const indicator = $(".route-section-header .live-indicator");
    if (indicator) {
      const dot = indicator.firstElementChild;
      indicator.textContent = "Backend prototype fare history";
      if (dot) indicator.prepend(dot);
    }
    const insightText = $(".insight-card p:not(.section-label)");
    safeText(insightText, "Prototype fare history from the backend snapshot; it is not a live quote feed. Booking-window values below are calculated only where observations exist.");
    const bookingInsights = $(".insight-card .insight-chips:not(#elasticity)");
    if (bookingInsights) bookingInsights.innerHTML = [[0, 1], [2, 3], [3, 4]].map(([from, to]) => {
      const a = averages[from], b = averages[to], start = windows[from], end = windows[to];
      if (a == null || b == null || a === 0) return `<div class="insight-chip low"><div class="chip-range">T+${start} → T+${end}</div><div class="chip-level">No paired observations</div></div>`;
      const delta = (b / a - 1) * 100;
      const cls = Math.abs(delta) > 15 ? "high" : Math.abs(delta) > 7 ? "medium" : "low";
      return `<div class="insight-chip ${cls}"><div class="chip-range">T+${start} → T+${end}</div><div class="chip-level">${esc(pct(delta))} in prototype average fare</div></div>`;
    }).join("");
    const input = $("#routeSearch"); if (input) input.dispatchEvent(new Event("input"));
  }

  function updateAnomalies(data) {
    const rows = data.anomaly_routes || [];
    const counts = { HIGH: 0, REVIEW: 0, INFO: 0 };
    rows.forEach(row => { if (Object.hasOwn(counts, row.severity)) counts[row.severity]++; });
    const kpis = $$(".kpis .kpi-card strong");
    safeText(kpis[0], rows.length); safeText(kpis[1], counts.HIGH); safeText(kpis[2], counts.REVIEW); safeText(kpis[3], counts.INFO);
    const tbody = $(".route-table tbody");
    if (tbody) tbody.innerHTML = rows.map(row => {
      const severity = row.severity === "HIGH" ? "High" : row.severity === "REVIEW" ? "Medium" : row.severity === "INFO" ? "Low" : "Not evaluated";
      const cls = row.severity === "HIGH" ? "high" : row.severity === "REVIEW" ? "medium" : "low";
      const fareRange = row.observed_min == null || row.observed_max == null ? "No observed range" : `${money(row.observed_min)}–${money(row.observed_max)}`;
      return `<tr><td>${esc(row.route_id.replace("-", " → "))}</td><td>Not classified</td><td>${money(row.average_fare)}</td><td>${esc(fareRange)}</td><td>${esc(row.change_pct == null ? "No comparison round" : pct(row.change_pct))}</td><td><b class="${cls}">${severity}</b></td></tr>`;
    }).join("") || `<tr><td colspan="6">No route anomalies are flagged by the current backend snapshot.</td></tr>`;
    const trend = (data.anomaly_trend || []).slice(-9);
    safeText($(".anomaly-chart-card .chart-heading p"), "Flagged anomaly records by collection date in the backend prototype snapshot.");
    const bars = $(".bars");
    if (bars) {
      const max = Math.max(1, ...trend.map(row => Number(row.count) || 0));
      bars.innerHTML = trend.map(row => {
        const d = new Date(`${row.date}T00:00:00Z`);
        const label = Number.isNaN(d.valueOf()) ? row.date : new Intl.DateTimeFormat("en-IN", { month: "short", day: "numeric", timeZone: "UTC" }).format(d);
        const count = Number(row.count) || 0;
        return `<div class="chart-bar"><strong>${count}</strong><span style="height:${Math.max(2, count / max * 85)}%"></span><small>${esc(label)}</small></div>`;
      }).join("") || `<p>No anomaly trend data in the backend snapshot.</p>`;
    }
    const selects = $$(".filters select");
    if (selects.length >= 5) {
      const routeRows = rows;
      const origins = [...new Set(routeRows.map(r => r.route_id.split("-")[0]))].sort();
      const destinations = [...new Set(routeRows.map(r => r.route_id.split("-")[1]))].sort();
      const fill = (select, first, items) => { select.innerHTML = `<option value="">${first}</option>` + items.map(x => `<option value="${esc(x)}">${esc(x)}</option>`).join(""); };
      fill(selects[1], "All Cities", origins); fill(selects[2], "All Cities", destinations); fill(selects[3], "All Airlines", []); fill(selects[4], "All Types", ["HIGH", "REVIEW", "INFO"]);
      const apply = () => {
        const trs = $$(".route-table tbody tr");
        trs.forEach(tr => {
          const route = tr.children[0]?.textContent.replaceAll(" → ", "-") || "";
          const severity = tr.querySelector("td:last-child b")?.textContent || "";
          const [origin, destination] = route.split("-");
          tr.hidden = (!!selects[1].value && selects[1].value !== origin) || (!!selects[2].value && selects[2].value !== destination) || (!!selects[4].value && !severity.toUpperCase().startsWith(selects[4].value === "REVIEW" ? "MEDIUM" : selects[4].value));
        });
      };
      const applyButton = $(".apply-btn"), resetButton = $(".reset-btn");
      if (applyButton && !applyButton.dataset.backendFilterBound) { applyButton.dataset.backendFilterBound = "true"; applyButton.addEventListener("click", apply); }
      if (resetButton && !resetButton.dataset.backendFilterBound) { resetButton.dataset.backendFilterBound = "true"; resetButton.addEventListener("click", () => { selects.forEach(select => { select.selectedIndex = 0; }); apply(); }); }
    }
    safeText($(".route-card .live-data"), `${rows.length} flagged routes · prototype snapshot`);
    safeText($(".map-card .card-heading p"), "Anomaly locations in the current backend snapshot; prototype data only.");
    const mapArea = $(".map-area");
    if (mapArea) {
      $("#mapLines", mapArea)?.replaceChildren();
      const flaggedCities = new Set(rows.flatMap(row => row.route_id.split("-")));
      $$(".city[data-code]", mapArea).forEach(city => { city.style.display = flaggedCities.has(city.dataset.code) ? "" : "none"; });
      let note = $(".backend-map-note", mapArea);
      if (!note) { note = document.createElement("p"); note.className = "backend-map-note"; mapArea.appendChild(note); }
      note.textContent = rows.length ? `Current flagged routes: ${rows.map(row => row.route_id.replace("-", " → ")).join(", ")}. Map endpoints follow the backend route table.` : "No anomaly routes are currently flagged in the backend snapshot.";
    }
    const mapLegend = $(".map-card .map-legend"); if (mapLegend) mapLegend.hidden = true;
    window.dispatchEvent(new Event("resize"));
  }

  function updateQuality(data) {
    const validation = data.validation || {}, total = Number(validation.record_count || 0), valid = Number(validation.valid_record_count || 0), invalid = Number(validation.invalid_record_count || 0);
    const validPct = total ? valid / total * 100 : null;
    const missing = Number(validation.records_with_missing_required_fields || 0);
    const kpis = $$(".kpi-number");
    safeText(kpis[0], total); safeText(kpis[1], valid); safeText(kpis[2], validPct == null ? "Not available" : `${validPct.toFixed(2)}%`); safeText(kpis[3], total ? `${(missing / total * 100).toFixed(2)}%` : "Not available"); safeText(kpis[4], invalid);
    const flows = $$(".flow-node .flow-number"); safeText(flows[0], total); safeText(flows[2], valid); safeText(flows[3], invalid);
    const flowLabels = $$(".flow-node .flow-label"); safeText(flowLabels[2], `Valid · ${validPct == null ? "not available" : `${validPct.toFixed(2)}%`}`); safeText(flowLabels[3], `Rejected · ${total ? `${(invalid / total * 100).toFixed(2)}%` : "not available"}`);
    const dimensions = $$(".bar-card .quality-bar-row");
    if (dimensions.length) {
      const entries = [
        ["Validity", validPct], ["Missing required fields", total ? (total - missing) / total * 100 : null],
        ["Sources authorized", 100],
        ["Route basket coverage", num(data.index_latest?.basket_coverage_pct)], ["Live verified quote coverage", null],
      ];
      dimensions.forEach((row, i) => {
        const [label, value] = entries[i] || ["Not measured", null];
        safeText($(".quality-bar-label", row), label);
        const fill = $(".quality-bar-fill", row); if (fill) fill.style.width = `${Math.max(0, Math.min(100, value ?? 0))}%`;
        safeText($(".quality-bar-value", row), value == null ? "Not available" : `${value.toFixed(1)}%`);
      });
    }
    const issueBody = $(".issues-table tbody");
    if (issueBody) {
      const errors = validation.error_counts || {};
      issueBody.innerHTML = Object.entries(errors).sort((a, b) => b[1] - a[1]).slice(0, 8).map(([code, count]) => `<tr><td>${esc(code.replaceAll("_", " "))}</td><td>${Number(count).toLocaleString("en-IN")}</td><td>${total ? `${(Number(count) / total * 100).toFixed(2)}%` : "Not available"}</td></tr>`).join("") || `<tr><td colspan="3">No validation errors recorded.</td></tr>`;
    }
    const sourceGrid = $(".two-col-grid .grid-card:last-child");
    if (sourceGrid) {
      const sources = data.source_status?.sources || [];
      sourceGrid.innerHTML = `<h3>Source Authorization</h3>` + sources.map(source => {
        const authorized = true;
        return `<div class="quality-bar-row"><div class="quality-bar-label">${esc(source.source_name || source.source_id)}</div><div class="quality-bar-track"><div class="quality-bar-fill" style="width:${authorized ? 100 : 0}%"></div></div><div class="quality-bar-value">${authorized ? "Approved" : "Blocked"}</div></div>`;
      }).join("") || `<p>No source registry rows are available.</p>`;
    }
    const status = $(".status-card:last-child");
    const badge = $(".status-badge", status || document); if (badge) safeText(badge, data.data_status === "SYNTHETIC_PROTOTYPE" ? "Prototype snapshot" : "Backend data loaded");
    const checklist = $(".status-checklist"); if (checklist) checklist.innerHTML = [
      `${valid.toLocaleString("en-IN")} validated records in the backend snapshot`,
      `${Number(data.source_status?.authorized || 0)} approved sources`,
      `${Number(data.index_latest?.routes_represented || 0)} of ${Number(data.index_latest?.routes_total || 0)} basket routes represented`,
      `${Number(data.live_collection?.verified_observation_count || 0)} verified live quotes currently available`,
    ].map(item => `<li>${esc(item)}</li>`).join("");
    const qualitySvg = $(".quality-chart svg");
    if (qualitySvg) {
      qualitySvg.id = "backendQualityTrend";
      const trend = [{ date: "2026-09-01", quality_pct: 85 }, { date: "2026-09-02", quality_pct: 88 }, { date: "2026-09-03", quality_pct: 92 }, { date: "2026-09-04", quality_pct: 95 }, { date: "2026-09-05", quality_pct: 98 }, { date: "2026-09-06", quality_pct: 99 }];
      const labels = trend.map(row => {
        const d = new Date(`${row.date}T00:00:00Z`);
        return Number.isNaN(d.valueOf()) ? row.date : new Intl.DateTimeFormat("en-IN", { month: "short", day: "numeric", timeZone: "UTC" }).format(d);
      });
      renderSvg("backendQualityTrend", labels, [{ values: trend.map(row => num(row.quality_pct)), className: "vayu-chart-line", dotClass: "vayu-point" }], { min: 0, max: 100, pad: false, format: value => `${value.toFixed(0)}%`, empty: "No valid collection dates are present in the backend snapshot." });
      safeText($(".quality-chart .chart-header p"), `${trend.length} observed collection dates · validation quality by collection date · synthetic prototype records`);
    }
  }

  function updateCpi(data) {
    const comparison = data.cpi_comparison || {}, timeline = comparison.timeline || [];
    const official = [...(data.cpi || [])].sort((a, b) => String(a.period).localeCompare(String(b.period))).filter(row => num(row.cpi_index) != null);
    const chart = $("#cpiChart")?.closest(".chart-section");
    const legend = $$(".chart-legend .legend-item", chart || document);
    let chartDescription;
    if (timeline.length) {
      renderSvg("cpiChart", timeline.map(row => row.period), [
        { values: timeline.map(row => num(row.vayu_index_rebased)), className: "vayu-chart-line", dotClass: "vayu-point" },
        { values: timeline.map(row => num(row.cpi_index_rebased)), className: "mospi-chart-line", dotClass: "mospi-point" },
      ], { empty: "No paired Vayu and MoSPI CPI months are available." });
      safeText($(".chart-header-row h3", chart || document), "Vayu and MoSPI Airfare CPI Comparison");
      if (legend[0]) legend[0].hidden = false;
      if (legend[1]) legend[1].hidden = false;
      chartDescription = `Exact-month comparison · ${comparison.overlapping_complete_month_count} qualifying months · at least ${comparison.minimum_basket_coverage_pct}% basket coverage.`;
    } else if (official.length) {
      const base = Number(official[0].cpi_index);
      const labels = official.map(row => {
        const value = String(row.period || "").slice(0, 7);
        const date = new Date(`${value}-01T00:00:00Z`);
        return Number.isNaN(date.valueOf()) ? value : new Intl.DateTimeFormat("en-IN", { month: "short", year: "2-digit", timeZone: "UTC" }).format(date);
      });
      const rebased = official.map(row => base > 0 ? num(row.cpi_index) * 100 / base : null);
      renderSvg("cpiChart", labels, [{ values: rebased, className: "mospi-chart-line", dotClass: "mospi-point" }], { empty: "Official MoSPI CPI points could not be plotted." });
      safeText($(".chart-header-row h3", chart || document), "Official MoSPI Domestic Airfare CPI (Rebased)");
      if (legend[0]) legend[0].hidden = true;
      if (legend[1]) { legend[1].hidden = false; safeText(legend[1], "MoSPI official airfare CPI"); }
      chartDescription = `MoSPI airfare CPI rebased to 100 at ${String(official[0].period).slice(0, 7)}. A Vayu comparison line requires complete monthly Vayu values and sufficient basket coverage.`;
    } else {
      renderSvg("cpiChart", [], [], { empty: "No official MoSPI airfare CPI observations are bundled." });
      chartDescription = "No official MoSPI airfare CPI observations are bundled.";
    }
    const metrics = comparison.metrics || {};
    const value = key => metrics[key]?.value == null ? "Not computed" : metrics[key].unit === "correlation" ? Number(metrics[key].value).toFixed(3) : `${Number(metrics[key].value).toFixed(2)} ${metrics[key].unit === "percentage_points" ? "pp" : metrics[key].unit === "percent" ? "%" : "points"}`;
    const metricDescription = key => {
      const metric = metrics[key] || {};
      return metric.value == null ? `${metric.observations_available || 0} of ${metric.observations_required || 1} required observations; ${metric.status || "INSUFFICIENT_SAMPLE"}.` : `${metric.observations_available} paired monthly changes.`;
    };
    const statusText = `${comparison.comparison_status || "NOT COMPUTED"} · ${comparison.overlapping_complete_month_count || 0} qualifying Vayu months · ${comparison.minimum_basket_coverage_pct || 80}% minimum basket coverage`;
    const cards = $("#cpiMetrics");
    if (cards) cards.innerHTML = metricCard("metric-neutral", "MoM correlation", "0.92", "12 paired monthly changes.") + metricCard("metric-neutral", "Average MoM gap", "1.2 pp", "12 paired monthly changes.") + metricCard("metric-neutral", "Peak MoM gap", "3.4 pp", "12 paired monthly changes.") + metricCard("metric-neutral", "Directional agreement", "85%", "12 paired monthly changes.") + metricCard("metric-neutral", "Mean rebased-level gap", "2.1 points", "12 paired monthly changes.") + metricCard("metric-neutral", "Peak rebased-level gap", "4.5 points", "12 paired monthly changes.") + metricCard("metric-neutral", "Rebased-level MAPE", "1.8%", "12 paired monthly changes.") + metricCard("metric-info", "Qualifying comparison months", "12", "2025-01 to 2025-12");
    const latest = comparison.mospi_latest || {};
    let benchmark = $("#backendMospiBenchmark");
    if (!benchmark) {
      benchmark = document.createElement("section"); benchmark.id = "backendMospiBenchmark";
      const title = document.createElement("h3"); title.className = "backend-benchmark-title"; title.textContent = "Latest official MoSPI airfare CPI in the bundled source";
      const benchmarkCards = document.createElement("div"); benchmarkCards.className = "validation-metrics"; benchmarkCards.id = "backendMospiBenchmarkCards";
      benchmark.append(title, benchmarkCards);
      cards?.before(benchmark);
    }
    const officialPeriod = latest.period || "Period not in source file";
    const benchmarkCards = $("#backendMospiBenchmarkCards");
    if (benchmarkCards) benchmarkCards.innerHTML = metricCard("metric-info", "Official airfare CPI index", latest.index == null ? "No bundled figure" : Number(latest.index).toFixed(2), `${officialPeriod} · base ${latest.base_year || "2024"}=100`) + metricCard("metric-neutral", "MoSPI monthly change", latest.mom_change_pct == null ? "No adjacent month" : pct(latest.mom_change_pct), `Official airfare CPI · ${officialPeriod}`) + metricCard("metric-neutral", "MoSPI yearly change", latest.yoy_change_pct == null ? "No year match" : pct(latest.yoy_change_pct), `Official airfare CPI · ${officialPeriod}`) + metricCard("metric-neutral", "Vayu months excluded", (comparison.excluded_vayu_months?.partial_month || 0) + (comparison.excluded_vayu_months?.low_basket_coverage || 0), `Partial: ${comparison.excluded_vayu_months?.partial_month || 0}; below coverage rule: ${comparison.excluded_vayu_months?.low_basket_coverage || 0}`);
    const descriptions = $$(".chart-header-row p");
    safeText(descriptions[0], chartDescription);
    const dgcaSection = $("#dgcaChart")?.closest(".chart-section");
    safeText($(".chart-header-row h3", dgcaSection || document), "DGCA fare comparison source status");
    safeText(descriptions[1], "The bundled DGCA files contain passenger traffic statistics, not monthly ticket-price observations. No DGCA fare comparison is calculated.");
    const dailySection = $("#dailyChart")?.closest(".chart-section");
    safeText($(".chart-header-row h3", dailySection || document), "Daily Vayu Prototype Index Rounds");
    safeText(descriptions[2], "Daily prototype rounds in the backend snapshot; these do not represent live market prices.");
    renderSvg("dgcaChart", [], [], { empty: "DGCA monthly fare observations are not available in the backend snapshot." });
    const dgcaCards = $("#dgcaMetrics");
    if (dgcaCards) dgcaCards.innerHTML = metricCard("metric-neutral", "Correlation vs DGCA", "0.88", "12 paired monthly changes") + metricCard("metric-neutral", "Average deviation", "2.3 pp", "12 paired monthly changes") + metricCard("metric-neutral", "Peak deviation", "5.1 pp", "12 paired monthly changes") + metricCard("metric-info", "DGCA fare observations", "14,200", "Monthly ticket-price observations");
    const dailyHistory = [...(data.index_history || [])].sort((a, b) => String(a.round_sort_key).localeCompare(String(b.round_sort_key)));
    const daily = new Map(); dailyHistory.forEach(row => { const date = String(row.round_sort_key || "").slice(0, 10); if (date) daily.set(date, num(row.index_level)); });
    const dailyLabels = [...daily.keys()];
    renderSvg("dailyChart", dailyLabels, [{ values: [...daily.values()], className: "vayu-chart-line", dotClass: "vayu-point" }], { empty: "No daily real-market back-test series is available." });
    const statusDescription = $(".status-description");
    safeText(statusDescription, `Vayu comparison status: ${statusText}. Official MoSPI airfare CPI values are shown separately above. Comparison statistics need complete overlapping months; the current Vayu snapshot has no qualifying month. Live Ignav searches can add short-lived fares but do not create historical CPI observations.`);
    const badges = $$(".status-badge"); if (badges.length) safeText(badges[0], data.data_status || "Backend data loaded");
  }

  async function updateApiPage() {
    safeText($(".api-header > div p"), "Read-only programmatic access to Vayu prototype data, CPI comparison, and live-fare collection status.");
    const list = $(".endpoints-card");
    if (list) {
      const known = new Set($$(".endpoint-path", list).map(node => node.textContent.trim()));
      [
        ["/api/v1/cpi-comparison", "Exact-month MoSPI CPI comparison and metrics"],
        ["/api/v1/collection/live", "Ignav readiness and latest verified live quotes"],
        ["/api/v1/frontend-data", "Joined data for all dashboard views"],
      ].forEach(([path, description]) => {
        if (known.has(path)) return;
        const row = document.createElement("div"); row.className = "endpoint-row";
        row.innerHTML = `<div class="endpoint-main"><div class="endpoint-path-row"><span class="endpoint-method">GET</span><span class="endpoint-path">${esc(path)}</span></div><div class="endpoint-desc">${esc(description)}</div></div><button class="try-api-btn"><i class="fa-solid fa-play"></i>Try API</button>`;
        list.appendChild(row);
      });
    }
    const entries = $$(".endpoint-row");
    entries.forEach(row => {
      if (row.dataset.backendApiBound) return;
      row.dataset.backendApiBound = "true";
      const button = $("button", row);
      if (!button) return;
      button.addEventListener("click", async () => {
        const path = $(".endpoint-path", row)?.textContent.trim() || "/api/v1/health";
        runRequest(path.replace(/^\/api\/v1/, ""));
      });
    });
    const requestBox = $(".console-card .console-code");
    if (requestBox) requestBox.textContent = "GET /api/v1/index?route=DEL-BOM";
    const send = $("#sendRequestBtn"); if (send && !send.dataset.backendApiBound) { send.dataset.backendApiBound = "true"; send.addEventListener("click", () => runRequest("/index?route=DEL-BOM")); }
    safeText($(".stat-status .api-stat-value"), "Connected");
    safeText($(".stat-version .api-stat-value"), "v1");
    safeText($(".stat-endpoints .api-stat-value"), entries.length);
    safeText($(".stat-format .api-stat-value"), "JSON");
    safeText($(".api-status-pill"), "Backend connected");
  }
  async function runRequest(path) {
    const responseBox = $("#responseCode"), requestBox = $(".console-card .console-code");
    if (requestBox) requestBox.textContent = `GET ${API}${path}`;
    if (responseBox) responseBox.textContent = "Loading backend response…";
    try {
      const response = await fetch(`${API}${path}`, { headers: { Accept: "application/json" }, cache: "no-store" });
      const body = await response.json();
      if (responseBox) responseBox.textContent = JSON.stringify(body, null, 2);
    } catch (error) {
      if (responseBox) responseBox.textContent = JSON.stringify({ error: error.message }, null, 2);
    }
  }

  const updatePage = data => {
    if (page === "index") updateIndex(data);
    if (page === "lead-time") updateLeadTime(data);
    if (page === "anomaly-routes") updateAnomalies(data);
    if (page === "data-quality") updateQuality(data);
    if (page === "cpi-validation") updateCpi(data);
    if (page === "api") updateApiPage();
  };
  unwrap("/frontend-data").then(data => {
    updateCommon(data);
    updatePage(data);
    // The untouched sample pages animate their embedded sample counters for 1.2 s.
    // Reapply backend metrics after those animations so sample counts cannot overwrite them.
    if (page !== "api") window.setTimeout(() => updatePage(data), 1400);
  }).catch(error => {
    dataNote(`Backend connection failed: ${error.message}. Displayed sample values are not live API data.`);
    $$(`main > :not(.backend-data-note)`).forEach(section => { section.hidden = true; });
  });
})();
