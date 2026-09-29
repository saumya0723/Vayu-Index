(() => {
  'use strict';

  const API = '/api/v1';
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));
  const SVG = 'http://www.w3.org/2000/svg';
  const routeNames = {
    AMD: 'Ahmedabad', BLR: 'Bengaluru', BOM: 'Mumbai', CCU: 'Kolkata',
    COK: 'Kochi', DEL: 'Delhi', GOI: 'Goa', HYD: 'Hyderabad',
    MAA: 'Chennai', PNQ: 'Pune'
  };

  const routeLabel = id => String(id || '').split('-').map(code => routeNames[code] || code).join(' ↔ ');
  const numeric = value => {
    const result = Number(value);
    return Number.isFinite(result) ? result : null;
  };
  const money = value => {
    const amount = numeric(value);
    return amount === null ? 'Not available' : new Intl.NumberFormat('en-IN', {
      style: 'currency', currency: 'INR', maximumFractionDigits: 0
    }).format(amount);
  };
  const percent = value => {
    const amount = numeric(value);
    return amount === null ? 'N/A' : `${amount > 0 ? '+' : ''}${amount.toFixed(2)}%`;
  };
  const make = (tag, value, className) => {
    const node = document.createElement(tag);
    if (value !== undefined && value !== null) node.textContent = String(value);
    if (className) node.className = className;
    return node;
  };
  const svgNode = (tag, attrs = {}, label) => {
    const node = document.createElementNS(SVG, tag);
    Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, String(value)));
    if (label !== undefined) node.textContent = String(label);
    return node;
  };

  async function getData(path) {
    const response = await fetch(path, { headers: { Accept: 'application/json' } });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error?.message || `Request failed (${response.status})`);
    return payload.data;
  }

  function addPrototypeNotice(data) {
    const anchor = $('.last-updated');
    if (!anchor) return;
    let notice = $('.backend-prototype-notice');
    if (!notice) {
      notice = make('div', undefined, 'backend-prototype-notice');
      Object.assign(notice.style, {
        margin: '0 auto 12px', maxWidth: '1240px', padding: '9px 16px',
        borderRadius: '7px', background: '#f7eddb', color: '#6b4c20',
        font: '600 12px/1.4 system-ui, sans-serif', letterSpacing: '.04em'
      });
      anchor.after(notice);
    }
    const liveState = data.live_collection?.status || data.source_status?.live_collection_status || 'LIVE COLLECTION NOT STARTED';
    const liveLabel = liveState === 'WAITING_FOR_PARTNER_ACCESS'
      ? 'LIVE COLLECTION WAITING FOR PARTNER ACCESS'
      : liveState === 'READY_TO_COLLECT'
        ? 'LIVE COLLECTION READY · OPERATOR CONFIRMATION REQUIRED'
        : liveState.replaceAll('_', ' ');
    notice.textContent = `${data.data_status} · ${data.official_status} · ${liveLabel}`;
    const updated = $('strong', anchor);
    if (updated && data.publication_timestamp) {
      const stamp = new Date(data.publication_timestamp);
      if (!Number.isNaN(stamp.getTime())) {
        updated.textContent = stamp.toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' });
      }
    }
  }

  function fillCell(row, value, className) {
    const cell = make('td', value);
    if (className) cell.className = className;
    row.appendChild(cell);
    return cell;
  }

  function replaceRows(table, rows) {
    const body = $('tbody', table);
    if (!body) return;
    body.replaceChildren();
    rows.forEach(values => {
      const row = make('tr');
      row.dataset.route = String(values.routeSearch || values.route_id || '').toLowerCase();
      values.cells.forEach((value, index) => fillCell(row, value, values.classes?.[index]));
      if (values.severity) {
        const target = row.lastElementChild;
        target.replaceChildren(make('span', values.severity.label, `severity-badge ${values.severity.className}`));
      }
      body.appendChild(row);
    });
    if (body.parentElement) body.parentElement.dataset.liveRows = String(rows.length);
  }

  function setupRouteSearch() {
    const input = $('#routeSearch');
    if (!input) return;
    input.addEventListener('input', () => {
      const term = input.value.trim().toLowerCase();
      const rows = $$('#routeTableBody tr');
      let shown = 0;
      rows.forEach(row => {
        const searchable = `${row.dataset.route || ''} ${row.textContent}`.toLowerCase();
        const match = searchable.includes(term);
        row.hidden = !match;
        if (match) shown += 1;
      });
      const empty = $('#noRouteResults');
      if (empty) empty.style.display = shown === 0 ? 'block' : 'none';
    });
  }

  function timeLabel(value, monthly = false) {
    if (!value) return '';
    const date = String(value).slice(0, 10);
    if (monthly) return date.slice(0, 7);
    return date.slice(5);
  }

  function drawLineChart(svg, labels, series, options = {}) {
    if (!svg) return;
    const vb = (svg.getAttribute('viewBox') || '0 0 1000 280').split(/\s+/).map(Number);
    const width = vb[2] || 1000;
    const height = vb[3] || 280;
    const left = 62, right = width - 28, top = 28, bottom = height - 38;
    const values = series.flatMap(item => item.values).filter(value => Number.isFinite(value));
    svg.replaceChildren();
    if (!values.length) {
      svg.appendChild(svgNode('text', { x: width / 2, y: height / 2, class: 'axis-label', 'text-anchor': 'middle' }, 'No published series available'));
      return;
    }
    let min = options.min ?? Math.min(...values);
    let max = options.max ?? Math.max(...values);
    if (min === max) { min -= 1; max += 1; }
    const padding = options.padding === false ? 0 : (max - min) * .12;
    min = options.min ?? min - padding;
    max = options.max ?? max + padding;
    const y = value => bottom - ((value - min) / (max - min)) * (bottom - top);
    for (let i = 0; i <= 4; i += 1) {
      const value = max - ((max - min) * i / 4);
      const gy = top + (bottom - top) * i / 4;
      svg.appendChild(svgNode('line', { x1: left, x2: right, y1: gy, y2: gy, class: 'grid-line' }));
      svg.appendChild(svgNode('text', { x: left - 9, y: gy + 4, class: 'axis-label', 'text-anchor': 'end' }, options.format ? options.format(value) : value.toFixed(1)));
    }
    const x = index => labels.length < 2 ? (left + right) / 2 : left + (right - left) * index / (labels.length - 1);
    series.forEach(item => {
      let segment = [];
      const flush = () => {
        if (segment.length > 1) {
          const path = segment.map((point, index) => `${index ? 'L' : 'M'}${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(' ');
          svg.appendChild(svgNode('path', { d: path, class: item.className, fill: 'none' }));
        }
        segment = [];
      };
      item.values.forEach((value, index) => {
        if (!Number.isFinite(value)) { flush(); return; }
        const point = { x: x(index), y: y(value) };
        segment.push(point);
        const dot = svgNode('circle', { cx: point.x, cy: point.y, r: 4, class: item.pointClass || '' });
        const title = svgNode('title', {}, `${labels[index]} · ${item.name}: ${options.format ? options.format(value) : value.toFixed(2)}`);
        dot.appendChild(title);
        svg.appendChild(dot);
      });
      flush();
    });
    const tickCount = Math.min(labels.length, options.ticks || 7);
    for (let i = 0; i < tickCount; i += 1) {
      const index = tickCount === 1 ? 0 : Math.round(i * (labels.length - 1) / (tickCount - 1));
      svg.appendChild(svgNode('text', { x: x(index), y: height - 9, class: 'axis-label', 'text-anchor': 'middle' }, labels[index]));
    }
  }

  function drawBars(svg, labels, values) {
    if (!svg) return;
    const vb = (svg.getAttribute('viewBox') || '0 0 1000 280').split(/\s+/).map(Number);
    const width = vb[2] || 1000, height = vb[3] || 280;
    const left = 62, right = width - 28, top = 28, bottom = height - 38;
    const max = Math.max(1, ...values);
    svg.replaceChildren();
    for (let i = 0; i <= 4; i += 1) {
      const y = top + (bottom - top) * i / 4;
      svg.appendChild(svgNode('line', { x1: left, x2: right, y1: y, y2: y, class: 'grid-line' }));
      svg.appendChild(svgNode('text', { x: left - 8, y: y + 4, class: 'axis-label', 'text-anchor': 'end' }, Math.round(max * (4 - i) / 4)));
    }
    const slot = labels.length ? (right - left) / labels.length : right - left;
    labels.forEach((label, index) => {
      const barHeight = (values[index] / max) * (bottom - top);
      const center = left + slot * (index + .5);
      svg.appendChild(svgNode('rect', { x: center - Math.min(30, slot * .28), y: bottom - barHeight, width: Math.min(60, slot * .56), height: barHeight, rx: 3, class: 'anomaly-bar' }));
      svg.appendChild(svgNode('text', { x: center, y: Math.max(top + 12, bottom - barHeight - 7), class: 'anomaly-bar-label', 'text-anchor': 'middle' }, values[index]));
      svg.appendChild(svgNode('text', { x: center, y: height - 9, class: 'axis-label', 'text-anchor': 'middle' }, label));
    });
  }

  function renderOverview(data) {
    if (!$('.index-summary')) return;
    $('.index-value').textContent = numeric(data.index_latest.index_level)?.toFixed(2) || data.index_latest.index_level;
    const change = $('.index-change');
    if (change) {
      const status = change.querySelector('span');
      change.firstChild.textContent = `${percent(data.index_latest.change_pct_vs_previous_round)} `;
      if (status) status.textContent = 'Prototype round change';
    }
    const kpis = $$('.kpi-strip .kpi-number');
    [data.live_collection?.complete_observation_count || 0, data.routes.length, data.live_collection?.configured ? 1 : 0].forEach((value, index) => {
      if (kpis[index]) kpis[index].textContent = new Intl.NumberFormat('en-IN').format(value);
    });
    const kpiLabels = $$('.kpi-strip .kpi-label');
    if (kpiLabels[0]) kpiLabels[0].innerHTML = 'Latest Live<br>Quotes';
    if (kpiLabels[1]) kpiLabels[1].innerHTML = 'Basket Routes<br>Configured';
    if (kpiLabels[2]) kpiLabels[2].innerHTML = 'Live Provider<br>Configured';

    const routeRows = data.live_quote_routes?.length
      ? data.live_quote_routes.map(route => ({
        route_id: route.route_id,
        routeSearch: routeLabel(route.route_id),
        cells: [routeLabel(route.route_id), money(route.average_fare), `${route.quote_count} · ${money(route.minimum_fare)}–${money(route.maximum_fare)}`]
      }))
      : data.overview_routes.map(route => ({
        route_id: route.route_id,
        routeSearch: routeLabel(route.route_id),
        cells: [routeLabel(route.route_id), money(route.average_fare), percent(route.change_pct)]
      }));
    const table = $('.route-section .route-table');
    if (table) {
      if (data.live_quote_routes?.length) {
        const title = $('.route-section h3');
        if (title) title.textContent = 'Latest Live Economy Quotes';
        const headers = $$('thead th', table);
        if (headers[1]) headers[1].textContent = 'Mean Live Fare';
        if (headers[2]) headers[2].textContent = 'Quote Count · Range';
      }
      replaceRows(table, routeRows);
    }
    const live = $('.route-section .live-indicator');
    if (live) live.textContent = data.live_quote_routes?.length ? 'Skyscanner Live Quotes' : 'Prototype Data';

    const daily = new Map();
    data.index_history.forEach(row => daily.set(String(row.round_sort_key).slice(0, 10), row));
    const history = Array.from(daily.values()).sort((a, b) => a.round_sort_key.localeCompare(b.round_sort_key));
    const labels = history.map(row => timeLabel(row.round_sort_key));
    const values = history.map(row => numeric(row.index_level));
    drawLineChart($('#indexChart'), labels, [{ name: 'Vayu Index', values, className: 'vayu-chart-line', pointClass: 'vayu-point' }], { min: 95, max: 105, format: value => value.toFixed(1) });
    const note = $('.chart-section .chart-header-row p');
    if (note) note.textContent = 'Synthetic prototype index rounds. Live provider quotes are shown separately and do not alter this index.';
    $$('.period').forEach(button => button.addEventListener('click', () => {
      requestAnimationFrame(() => drawLineChart($('#indexChart'), labels, [{ name: 'Vayu Index', values, className: 'vayu-chart-line', pointClass: 'vayu-point' }], { min: 95, max: 105, format: value => value.toFixed(1) }));
    }));
  }

  function severityStyle(severity) {
    if (severity === 'HIGH') return { label: 'High', className: 'high' };
    if (severity === 'REVIEW') return { label: 'Review', className: 'medium' };
    if (severity === 'INFO') return { label: 'Info', className: 'low' };
    return { label: severity || 'None', className: 'low' };
  }

  function renderAnomalies(data) {
    if (!$('.anomaly-table')) return;
    const nums = $$('.kpi-strip .kpi-number');
    const counts = data.anomaly_summary.severity_counts;
    const high = counts.HIGH || 0, review = counts.REVIEW || 0, info = counts.INFO || 0;
    [data.anomaly_summary.route_count, high, review, info].forEach((value, index) => {
      if (nums[index]) nums[index].textContent = String(value);
    });
    const headers = $$('thead th', $('.anomaly-table'));
    if (headers[3]) headers[3].textContent = 'Observed Range';
    if (headers[4]) headers[4].textContent = 'Round Change';
    const rows = data.anomaly_routes.map(route => ({
      route_id: route.route_id,
      routeSearch: routeLabel(route.route_id),
      cells: [routeLabel(route.route_id), 'Prototype aggregate', money(route.average_fare), `${money(route.observed_min)}–${money(route.observed_max)}`, percent(route.change_pct), ''],
      severity: severityStyle(route.severity)
    }));
    replaceRows($('.anomaly-table'), rows);
    const chartRows = data.anomaly_trend;
    drawBars($('.chart-section .index-chart'), chartRows.map(row => row.date.slice(5)), chartRows.map(row => row.count));
    const chartDesc = $('.chart-section .chart-header-row p');
    if (chartDesc) chartDesc.textContent = 'Non-NONE diagnostic records by collection date in the prototype snapshot.';
    const live = $('.route-section .live-indicator');
    if (live) live.textContent = 'Prototype Data';
    const caption = $('.map-caption');
    if (caption) caption.textContent = `Showing ${data.anomaly_routes.length} flagged route(s) in the current prototype snapshot.`;
    const coordinates = { DEL: [161, 174], AMD: [80, 282], BOM: [85, 358], PNQ: [102, 369], GOI: [102, 428], CCU: [357, 291], HYD: [184, 391], BLR: [168, 477], MAA: [215, 474], COK: [145, 535] };
    const map = $('.india-map');
    if (map) {
      $$('line.map-route', map).forEach(line => line.remove());
      data.anomaly_routes.forEach(route => {
        const pair = route.route_id.split('-');
        if (!coordinates[pair[0]] || !coordinates[pair[1]]) return;
        const severity = severityStyle(route.severity).className;
        map.appendChild(svgNode('line', {
          x1: coordinates[pair[0]][0], y1: coordinates[pair[0]][1],
          x2: coordinates[pair[1]][0], y2: coordinates[pair[1]][1],
          class: `map-route ${severity}`
        }));
      });
    }
  }

  function windowSort(value) {
    const match = String(value).match(/^T(\d+)/);
    return match ? Number(match[1]) : Number.MAX_SAFE_INTEGER;
  }
  function windowLabel(value) {
    const match = String(value).match(/\(([^)]+)\)/);
    return match ? `${match[1]} Days` : value;
  }

  function renderLeadTime(data) {
    if (!location.pathname.endsWith('lead-time.html')) return;
    const summaries = data.lead_time.slice().sort((a, b) => windowSort(a.advance_purchase_window) - windowSort(b.advance_purchase_window));
    const totals = new Map();
    summaries.forEach(row => {
      const item = totals.get(row.advance_purchase_window) || { total: 0, count: 0 };
      const fare = numeric(row.average_fare);
      if (fare !== null) { item.total += fare * row.observation_count; item.count += row.observation_count; }
      totals.set(row.advance_purchase_window, item);
    });
    const windows = Array.from(totals.keys()).sort((a, b) => windowSort(a) - windowSort(b));
    const windowAverages = windows.map(window => {
      const item = totals.get(window);
      return item.count ? item.total / item.count : null;
    });
    const ordered = windowAverages.map((fare, index) => ({ fare, window: windows[index] })).filter(item => item.fare !== null);
    const cheapest = ordered.reduce((best, item) => item.fare < best.fare ? item : best, ordered[0]);
    const highest = ordered.reduce((best, item) => item.fare > best.fare ? item : best, ordered[0]);
    const rise = cheapest && highest && cheapest.fare ? ((highest.fare / cheapest.fare) - 1) * 100 : null;
    const values = $$('.kpi-strip .kpi-number');
    const labels = $$('.kpi-strip .kpi-label');
    [String(windows.length), cheapest ? windowLabel(cheapest.window) : 'N/A', highest ? windowLabel(highest.window) : 'N/A', percent(rise)].forEach((value, index) => { if (values[index]) values[index].textContent = value; });
    ['Booking Windows<br>Observed', 'Lowest Average<br>Fare Window', 'Highest Average<br>Fare Window', 'Fare Difference<br>Across Windows'].forEach((value, index) => { if (labels[index]) labels[index].innerHTML = value; });

    const routes = Array.from(new Set(summaries.map(row => row.route_id))).sort();
    const table = $('.leadtime-table');
    if (table) {
      const header = $('thead tr', table);
      if (header) {
        header.replaceChildren();
        ['Route', 'Airline / Source', ...windows.map(windowLabel)].forEach(title => header.appendChild(make('th', title)));
      }
      const rows = routes.map(route => {
        const byWindow = new Map(summaries.filter(row => row.route_id === route).map(row => [row.advance_purchase_window, row.average_fare]));
        return { route_id: route, routeSearch: routeLabel(route), cells: [routeLabel(route), 'Prototype aggregate', ...windows.map(window => money(byWindow.get(window)))] };
      });
      replaceRows(table, rows);
    }
    const chart = $('.chart-section .index-chart');
    drawLineChart(chart, windows.map(windowLabel), [{ name: 'Average Fare', values: windowAverages, className: 'leadtime-line', pointClass: 'leadtime-point' }], { min: 0, format: value => money(value) });
    const live = $('.route-section .live-indicator');
    if (live) live.textContent = 'Prototype Data';
  }

  function replaceQualityRows(section, issues) {
    if (!section) return;
    $$('.quality-bar-row', section).forEach(row => row.remove());
    const maximum = Math.max(1, ...issues.map(item => item.count));
    issues.forEach(item => {
      const row = make('div', undefined, 'quality-bar-row');
      row.append(make('div', item.label, 'quality-bar-label'));
      const track = make('div', undefined, 'quality-bar-track');
      const fill = make('div', undefined, 'quality-bar-fill');
      fill.style.width = `${item.count / maximum * 100}%`;
      track.appendChild(fill);
      row.append(track, make('div', item.count, 'quality-bar-value'));
      section.appendChild(row);
    });
  }

  function renderQuality(data) {
    if (!location.pathname.endsWith('data-quality.html')) return;
    const v = data.validation;
    const nums = $$('.kpi-strip .kpi-number');
    const quality = numeric(v.valid_pct);
    const missingPct = v.record_count ? (v.records_with_missing_required_fields / v.record_count * 100) : 0;
    [v.record_count, v.valid_record_count, quality === null ? 'N/A' : `${quality.toFixed(2)}%`, `${missingPct.toFixed(2)}%`, v.invalid_record_count].forEach((value, index) => { if (nums[index]) nums[index].textContent = typeof value === 'number' ? new Intl.NumberFormat('en-IN').format(value) : value; });
    const kpiLabels = $$('.kpi-strip .kpi-label');
    if (kpiLabels[0]) kpiLabels[0].innerHTML = 'Synthetic<br>Records';
    const flowNumbers = $$('.flow-number');
    [v.record_count, 'Validation snapshot', v.valid_record_count, v.invalid_record_count].forEach((value, index) => { if (flowNumbers[index]) flowNumbers[index].textContent = typeof value === 'number' ? new Intl.NumberFormat('en-IN').format(value) : value; });
    const flowLabels = $$('.flow-label');
    if (flowLabels[0]) flowLabels[0].textContent = 'Synthetic records processed';
    if (flowLabels[2]) flowLabels[2].textContent = `Valid — ${quality === null ? 'N/A' : `${quality.toFixed(2)}%`}`;
    if (flowLabels[3]) flowLabels[3].textContent = `Invalid — ${v.record_count ? (v.invalid_record_count / v.record_count * 100).toFixed(2) : '0.00'}%`;

    const dimensionSection = $$('.chart-section').find(section => $('h3', section)?.textContent.includes('Quality Dimensions'));
    if (dimensionSection) {
      const heading = $('h3', dimensionSection);
      if (heading) heading.textContent = 'Validation Error Codes';
      const topErrors = Object.entries(v.error_counts).map(([label, count]) => ({ label: label.replaceAll('_', ' '), count })).sort((a, b) => b.count - a.count).slice(0, 6);
      replaceQualityRows(dimensionSection, topErrors.length ? topErrors : [{ label: 'No validation errors', count: 0 }]);
    }
    const sourceCard = $$('.two-col-grid .grid-card').find(card => $('h3', card)?.textContent.includes('Data Source Quality'));
    if (sourceCard) {
      const heading = $('h3', sourceCard);
      if (heading) heading.textContent = 'Collection Authorization';
      const rows = data.source_status.sources.slice(0, 6).map(source => ({ label: source.source_name || source.source_id, count: Number(source.compliance_blocks || 0) }));
      replaceQualityRows(sourceCard, rows.length ? rows : [{ label: 'No source status rows', count: 0 }]);
      sourceCard.appendChild(make('p', `${data.source_status.authorized} of ${data.source_status.total} sources authorized; live collection has not started.`));
    }
    const issueTable = $('.issues-table tbody');
    if (issueTable) {
      issueTable.replaceChildren();
      Object.entries(v.error_counts).sort((a, b) => b[1] - a[1]).slice(0, 8).forEach(([code, count]) => {
        const row = make('tr');
        fillCell(row, code.replaceAll('_', ' '));
        fillCell(row, count);
        fillCell(row, `${(count / Math.max(1, v.record_count) * 100).toFixed(2)}%`);
        issueTable.appendChild(row);
      });
    }
    const trend = $('.chart-section .index-chart');
    const statusEntries = Object.entries(v.status_counts);
    drawBars(trend, statusEntries.map(([name]) => name.replaceAll('_', ' ')), statusEntries.map(([, count]) => count));
    const trendDesc = $('.chart-section .chart-header-row p');
    if (trendDesc) trendDesc.textContent = 'Validation status counts in the published synthetic observation snapshot.';
    const statusCard = $('.status-card');
    if (statusCard) {
      const title = $('h3', statusCard);
      if (title) title.textContent = 'Prototype Validation Snapshot';
      const badge = $('.status-badge', statusCard);
      if (badge) badge.textContent = `${v.valid_record_count} valid · ${v.invalid_record_count} invalid`;
      const checklist = $('.status-checklist', statusCard);
      if (checklist) checklist.replaceChildren(
        make('li', `${v.record_count} synthetic observations were validated.`),
        make('li', `${v.records_with_validation_errors} records contain validation errors.`),
        make('li', `${v.records_with_missing_required_fields} records have missing required fields.`),
        make('li', 'Live airfare collection has not started.')
      );
    }
  }

  function renderCpi(data) {
    if (!location.pathname.endsWith('cpi-validation.html')) return;
    const subtitle = $('.page-title p');
    if (subtitle) subtitle.textContent = 'Benchmarked against MoSPI Domestic Airfare CPI (2024=100)';
    const legend = $$('.chart-legend .legend-item');
    if (legend[0]) legend[0].lastChild.textContent = 'Vayu Index · complete paired months';
    if (legend[1]) legend[1].lastChild.textContent = 'MoSPI Domestic Airfare CPI';
    const cpi = data.cpi.map(row => ({ key: row.period.slice(0, 7), label: `${row.month.slice(0, 3)} ${row.year}`, value: numeric(row.cpi_index) }));
    const comparison = data.cpi_comparison;
    const paired = comparison.timeline || [];
    const pairedByMonth = new Map(paired.map(row => [row.period, row]));
    const keys = paired.length
      ? cpi.map(row => row.key).filter(key => key >= comparison.overlap_period_start && key <= comparison.overlap_period_end)
      : cpi.map(row => row.key);
    const labels = keys.map(key => cpi.find(row => row.key === key)?.label || key);
    const cpiValues = paired.length
      ? keys.map(key => numeric(pairedByMonth.get(key)?.cpi_index_rebased))
      : cpi.map((row, index) => cpi.length && cpi[0].value ? row.value / cpi[0].value * 100 : null);
    const indexValues = paired.length ? keys.map(key => numeric(pairedByMonth.get(key)?.vayu_index_rebased)) : keys.map(() => null);
    drawLineChart($('.chart-section .index-chart'), labels, [
      { name: paired.length ? 'MoSPI Airfare CPI (rebased at overlap)' : 'MoSPI Airfare CPI (rebased at first month)', values: cpiValues, className: 'mospi-chart-line', pointClass: 'mospi-point' },
      { name: 'Vayu Index (rebased at overlap)', values: indexValues, className: 'vayu-chart-line', pointClass: 'vayu-point' }
    ], { format: value => value.toFixed(1), ticks: 8 });
    const chartDesc = $('.chart-section .chart-header-row p');
    if (chartDesc) chartDesc.textContent = paired.length
      ? `Exact complete-month overlap ${comparison.overlap_period_start}–${comparison.overlap_period_end}; both series rebased to 100 at the first paired month. ${comparison.paired_monthly_change_count} adjacent monthly changes are available.`
      : `Packaged MoSPI domestic airfare CPI: ${cpi[0]?.label || 'N/A'}–${cpi.at(-1)?.label || 'N/A'} (rebased within its own span). Vayu values are omitted: there are no exact complete months with at least ${comparison.minimum_basket_coverage_pct}% basket coverage.`;
    const metrics = $$('.validation-metrics .metric-value');
    const pearson = comparison.metrics.pearson_correlation_of_mom_changes;
    const averageGap = comparison.metrics.mean_absolute_mom_change_gap;
    const peakGap = comparison.metrics.peak_absolute_mom_change_gap;
    const metricText = [
      pearson.value === null ? 'N/A' : pearson.value.toFixed(2),
      averageGap.value === null ? 'N/A' : `${averageGap.value.toFixed(2)} pp`,
      peakGap.value === null ? 'N/A' : `${peakGap.value.toFixed(2)} pp`,
      String(comparison.overlapping_complete_month_count)
    ];
    metricText.forEach((value, index) => { if (metrics[index]) metrics[index].textContent = value; });
    const descriptions = $$('.validation-metrics .metric-description');
    [
      `MoM change correlation · ${pearson.observations_available}/${pearson.observations_required} changes required`,
      `Mean absolute MoM gap · ${averageGap.observations_available}/${averageGap.observations_required} changes required`,
      'Largest absolute MoM change gap in paired months',
      'Exact complete months with at least 80% basket coverage'
    ].forEach((value, index) => { if (descriptions[index]) descriptions[index].textContent = value; });
    const title = $('.status-header h3');
    if (title) title.textContent = 'Comparison Status';
    const badge = $('.status-badge', $('.validation-status-card'));
    const hasSixChanges = averageGap.status === 'AVAILABLE';
    if (badge) {
      badge.className = `status-badge ${hasSixChanges ? 'healthy' : 'medium'}`;
      badge.textContent = hasSixChanges ? (pearson.status === 'AVAILABLE' ? 'Metrics available' : 'Partial metrics') : 'Insufficient overlap';
    }
    const description = $('.validation-status-card .status-description');
    if (description) {
      const latest = comparison.mospi_latest;
      const latestSummary = latest
        ? ` The packaged MoSPI series ends at ${latest.period}: index ${latest.index.toFixed(2)}, month-on-month ${latest.mom_change_pct === null ? 'N/A' : `${latest.mom_change_pct.toFixed(2)}%`}, year-on-year ${latest.yoy_change_pct === null ? 'N/A' : `${latest.yoy_change_pct.toFixed(2)}%`}.`
        : '';
      description.textContent = comparison.overlapping_complete_month_count === 0
        ? `The comparison uses exact complete months, requires at least 80% of the locked basket, and does not fill gaps. The current Vayu snapshot has ${comparison.overlapping_complete_month_count} eligible overlap months, so CPI-to-Vayu correlation and deviation metrics are unavailable. No CPI validation claim is made.${latestSummary}`
        : `The comparison uses exact complete months, requires at least 80% of the locked basket, and does not fill gaps. ${comparison.paired_monthly_change_count} adjacent monthly changes are paired. Metrics remain descriptive and are not a production validation claim.${latestSummary}`;
    }
  }

  async function requestAndDisplay(path, target) {
    if (!target) return;
    target.textContent = 'Loading…';
    try {
      const response = await fetch(path, { headers: { Accept: 'application/json' } });
      const payload = await response.json();
      target.textContent = JSON.stringify(payload, null, 2);
    } catch (error) {
      target.textContent = JSON.stringify({ error: String(error) }, null, 2);
    }
  }

  function renderApiPage(data) {
    if (!location.pathname.endsWith('api.html')) return;
    const responsePane = $('#responseCode');
    const endpoints = $('.endpoints-card');
    const existing = new Set(endpoints ? $$('.endpoint-path', endpoints).map(node => node.textContent.trim()) : []);
    [
      ['/api/v1/cpi-comparison', 'Exact-month CPI metrics with complete-period and basket-coverage gates.'],
      ['/api/v1/collection/live', 'Partner API readiness and latest live fare quotes.']
    ].forEach(([path, description]) => {
      if (existing.has(path) || !endpoints) return;
      const row = make('div', undefined, 'endpoint-row');
      const main = make('div', undefined, 'endpoint-main');
      const pathRow = make('div', undefined, 'endpoint-path-row');
      pathRow.append(make('span', 'GET', 'endpoint-method'), make('span', path, 'endpoint-path'));
      main.append(pathRow, make('div', description, 'endpoint-desc'));
      const button = make('button', 'Try API', 'try-api-btn');
      row.append(main, button);
      endpoints.appendChild(row);
    });
    const endpointCount = $$('.api-stat .api-stat-value', $('.api-stats'))[2];
    if (endpointCount) endpointCount.textContent = '7';
    $$('.try-api-btn').forEach(button => {
      button.addEventListener('click', () => {
        const path = $('.endpoint-path', button.closest('.endpoint-row'))?.textContent.trim();
        if (path) requestAndDisplay(path, responsePane);
      });
    });
    const original = $('#sendRequestBtn');
    if (original) {
      const button = original.cloneNode(true);
      original.replaceWith(button);
      button.addEventListener('click', () => {
        const requestText = $('.console-card .console-code')?.textContent || 'GET /api/v1/index';
        const lines = requestText.trim().split(/\r?\n/);
        const path = (lines[0].match(/GET\s+(\S+)/) || [])[1] || '/api/v1/index';
        const query = lines.slice(1).join('').replace(/^\?/, '?');
        requestAndDisplay(path + query, responsePane);
      });
    }
  }

  function setupTryFallback() {
    const error = $('#error');
    if (error) error.hidden = true;
  }

  async function init() {
    setupTryFallback();
    try {
      const data = await getData(`${API}/frontend-data`);
      addPrototypeNotice(data);
      renderOverview(data);
      renderAnomalies(data);
      renderLeadTime(data);
      renderQuality(data);
      renderCpi(data);
      renderApiPage(data);
      setupRouteSearch();
    } catch (error) {
      const anchor = $('.last-updated');
      if (anchor) {
        const notice = make('div', `Backend data unavailable: ${error.message}`, 'backend-prototype-notice');
        Object.assign(notice.style, { margin: '0 auto 12px', maxWidth: '1240px', padding: '9px 16px', background: '#f9dddd', color: '#7d2525', borderRadius: '7px', font: '600 12px system-ui, sans-serif' });
        anchor.after(notice);
      }
    }
  }

  document.addEventListener('DOMContentLoaded', init, { once: true });
})();
