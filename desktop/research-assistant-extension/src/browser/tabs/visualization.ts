import type { ResearchAssistantWidget } from '../research-assistant-widget';

const SVG_NS = 'http://www.w3.org/2000/svg';
const COLORS = [
    '#60a5fa', '#f59e0b', '#34d399', '#f472b6', '#a78bfa', '#22d3ee',
    '#fb7185', '#a3e635', '#facc15', '#c084fc', '#2dd4bf', '#fdba74',
];

type JsonObject = Record<string, unknown>;

interface ChartPoint {
    x: number;
    y: number;
    lower?: number;
    upper?: number;
    n?: number;
}

interface ChartSeries {
    name: string;
    points: ChartPoint[];
}

interface ChartData {
    spec?: {
        chart_type?: string;
        uncertainty?: string;
        y_scale?: string;
        title?: string | null;
        y_label?: string | null;
    };
    series?: ChartSeries[];
    truncated?: boolean;
    series_count?: number;
    series_total?: number;
}

function svg<K extends keyof SVGElementTagNameMap>(
    tag: K,
    attributes: Record<string, string | number> = {},
): SVGElementTagNameMap[K] {
    const node = document.createElementNS(SVG_NS, tag);
    for (const [name, value] of Object.entries(attributes)) {
        node.setAttribute(name, String(value));
    }
    return node;
}

function finite(value: unknown): number | undefined {
    const number = Number(value);
    return Number.isFinite(number) ? number : undefined;
}

function formatNumber(value: unknown): string {
    const number = finite(value);
    if (number === undefined) return '—';
    const absolute = Math.abs(number);
    if ((absolute > 0 && absolute < 1e-3) || absolute >= 1e4) {
        return number.toExponential(3);
    }
    return number.toLocaleString(undefined, { maximumSignificantDigits: 5 });
}

function title(chart: ChartData): string {
    return chart.spec?.title || chart.spec?.y_label || 'metric';
}

function transformedBounds(chart: ChartData): {
    xMin: number;
    xMax: number;
    yMin: number;
    yMax: number;
    transform: (value: number) => number;
} | undefined {
    const log = chart.spec?.y_scale === 'log';
    const points = (chart.series || []).flatMap(series => series.points)
        .filter(point => finite(point.x) !== undefined && finite(point.y) !== undefined)
        .filter(point => !log || Number(point.y) > 0);
    if (!points.length) return undefined;
    const transform = (value: number): number => log
        ? Math.log10(Math.max(value, Number.MIN_VALUE))
        : value;
    const xs = points.map(point => Number(point.x));
    const ys = points.flatMap(point => [
        Number(point.lower ?? point.y),
        Number(point.upper ?? point.y),
    ]).filter(value => Number.isFinite(value) && (!log || value > 0)).map(transform);
    if (!ys.length) return undefined;
    let xMin = Math.min(...xs);
    let xMax = Math.max(...xs);
    let yMin = Math.min(...ys);
    let yMax = Math.max(...ys);
    if (xMin === xMax) xMax = xMin + 1;
    if (yMin === yMax) {
        yMin -= 0.5;
        yMax += 0.5;
    }
    return { xMin, xMax, yMin, yMax, transform };
}

function renderLineChart(view: ResearchAssistantWidget, chart: ChartData): HTMLElement {
    const host = view.element('section', 'ra-chart');
    host.append(view.element('h4', undefined, title(chart)));
    const bounds = transformedBounds(chart);
    if (!bounds) {
        host.append(view.element('div', 'ra-empty', 'No matching metric values.'));
        return host;
    }
    const width = 900;
    const height = 320;
    const left = 72;
    const right = 18;
    const top = 24;
    const bottom = 48;
    const plotWidth = width - left - right;
    const plotHeight = height - top - bottom;
    const sx = (value: number): number => left
        + ((value - bounds.xMin) / (bounds.xMax - bounds.xMin)) * plotWidth;
    const sy = (value: number): number => top
        + (1 - (bounds.transform(value) - bounds.yMin) / (bounds.yMax - bounds.yMin))
        * plotHeight;
    const image = svg('svg', { viewBox: `0 0 ${width} ${height}`, role: 'img' });
    image.append(
        svg('line', { x1: left, y1: top, x2: left, y2: height - bottom, class: 'ra-chart-axis' }),
        svg('line', {
            x1: left,
            y1: height - bottom,
            x2: width - right,
            y2: height - bottom,
            class: 'ra-chart-axis',
        }),
    );
    for (let tick = 0; tick <= 4; tick += 1) {
        const y = top + (tick / 4) * plotHeight;
        const transformed = bounds.yMax - (tick / 4) * (bounds.yMax - bounds.yMin);
        const value = chart.spec?.y_scale === 'log' ? 10 ** transformed : transformed;
        image.append(svg('line', {
            x1: left,
            y1: y,
            x2: width - right,
            y2: y,
            class: 'ra-chart-gridline',
        }));
        const label = svg('text', {
            x: left - 8,
            y: y + 4,
            'text-anchor': 'end',
            class: 'ra-chart-tick',
        });
        label.textContent = formatNumber(value);
        image.append(label);
    }
    for (const [index, series] of (chart.series || []).entries()) {
        const color = COLORS[index % COLORS.length];
        const points = series.points
            .filter(point => finite(point.x) !== undefined && finite(point.y) !== undefined)
            .filter(point => chart.spec?.y_scale !== 'log' || Number(point.y) > 0);
        if (!points.length) continue;
        if (chart.spec?.uncertainty !== 'none') {
            const upper = points
                .filter(point => chart.spec?.y_scale !== 'log' || Number(point.upper ?? point.y) > 0)
                .map(point => `${sx(Number(point.x))},${sy(Number(point.upper ?? point.y))}`);
            const lower = [...points].reverse()
                .filter(point => chart.spec?.y_scale !== 'log' || Number(point.lower ?? point.y) > 0)
                .map(point => `${sx(Number(point.x))},${sy(Number(point.lower ?? point.y))}`);
            if (upper.length && lower.length) {
                image.append(svg('polygon', {
                    points: [...upper, ...lower].join(' '),
                    fill: color,
                    opacity: 0.12,
                }));
            }
        }
        const path = points.map((point, position) => (
            `${position ? 'L' : 'M'}${sx(Number(point.x)).toFixed(2)},${sy(Number(point.y)).toFixed(2)}`
        )).join(' ');
        image.append(svg('path', {
            d: path,
            fill: 'none',
            stroke: color,
            'stroke-width': 2,
            'vector-effect': 'non-scaling-stroke',
        }));
        if (points.length <= 100) {
            for (const point of points) {
                const marker = svg('circle', {
                    cx: sx(Number(point.x)),
                    cy: sy(Number(point.y)),
                    r: 2.5,
                    fill: color,
                });
                const tooltip = svg('title');
                tooltip.textContent = `${series.name}\nstep ${formatNumber(point.x)}\n${formatNumber(point.y)}`;
                marker.append(tooltip);
                image.append(marker);
            }
        }
    }
    host.append(image, legend(view, chart.series || []));
    if (chart.truncated) {
        host.append(view.element(
            'small',
            'ra-help warning',
            `Showing ${chart.series_count ?? chart.series?.length ?? 0} of ${chart.series_total ?? 'many'} series.`,
        ));
    }
    return host;
}

function renderBarChart(view: ResearchAssistantWidget, chart: ChartData): HTMLElement {
    const host = view.element('section', 'ra-chart');
    host.append(view.element('h4', undefined, title(chart)));
    const values = (chart.series || []).map(series => {
        const point = series.points.at(-1);
        return point ? { name: series.name, ...point } : undefined;
    }).filter((value): value is { name: string } & ChartPoint => Boolean(value));
    const log = chart.spec?.y_scale === 'log';
    const valid = values.filter(value => finite(value.y) !== undefined && (!log || value.y > 0));
    if (!valid.length) {
        host.append(view.element('div', 'ra-empty', 'No matching metric values.'));
        return host;
    }
    const transform = (value: number): number => log
        ? Math.log10(Math.max(value, Number.MIN_VALUE))
        : value;
    const transformed = valid.flatMap(value => [
        transform(Number(value.lower ?? value.y)),
        transform(Number(value.upper ?? value.y)),
    ]);
    let minimum = log ? Math.min(...transformed) : Math.min(0, ...transformed);
    let maximum = Math.max(...transformed);
    if (minimum === maximum) maximum = minimum + 1;
    const width = 900;
    const height = 360;
    const left = 72;
    const right = 18;
    const top = 28;
    const bottom = 92;
    const plotWidth = width - left - right;
    const slot = plotWidth / valid.length;
    const barWidth = Math.max(4, Math.min(54, slot * 0.64));
    const sy = (value: number): number => height - bottom
        - ((transform(value) - minimum) / (maximum - minimum)) * (height - top - bottom);
    const baseline = sy(log ? 10 ** minimum : 0);
    const image = svg('svg', { viewBox: `0 0 ${width} ${height}`, role: 'img' });
    image.append(
        svg('line', { x1: left, y1: top, x2: left, y2: height - bottom, class: 'ra-chart-axis' }),
        svg('line', { x1: left, y1: baseline, x2: width - right, y2: baseline, class: 'ra-chart-axis' }),
    );
    valid.forEach((point, index) => {
        const center = left + slot * (index + 0.5);
        const topY = sy(point.y);
        const rectangle = svg('rect', {
            x: center - barWidth / 2,
            y: Math.min(topY, baseline),
            width: barWidth,
            height: Math.max(1, Math.abs(baseline - topY)),
            rx: 3,
            fill: COLORS[index % COLORS.length],
            opacity: 0.86,
        });
        const tooltip = svg('title');
        tooltip.textContent = `${point.name}: ${formatNumber(point.y)} (n=${point.n ?? '—'})`;
        rectangle.append(tooltip);
        image.append(rectangle);
        const label = svg('text', {
            x: center,
            y: height - bottom + 16,
            transform: `rotate(-32 ${center} ${height - bottom + 16})`,
            'text-anchor': 'end',
            class: 'ra-chart-tick',
        });
        label.textContent = point.name;
        image.append(label);
    });
    host.append(image);
    return host;
}

function legend(view: ResearchAssistantWidget, series: ChartSeries[]): HTMLElement {
    const host = view.element('div', 'ra-chart-legend');
    series.slice(0, 20).forEach((item, index) => {
        const swatch = view.element('span', 'ra-chart-swatch');
        swatch.style.backgroundColor = COLORS[index % COLORS.length];
        host.append(view.element(
            'span',
            'ra-chart-legend-item',
            undefined,
            [swatch, document.createTextNode(item.name)],
        ));
    });
    if (series.length > 20) {
        host.append(view.element('small', 'ra-help', `+${series.length - 20} series`));
    }
    return host;
}

export function renderChart(
    view: ResearchAssistantWidget,
    host: HTMLElement,
    value: unknown,
): void {
    const payload = value && typeof value === 'object' ? value as JsonObject : {};
    const chart = (payload.chart || payload) as ChartData;
    host.replaceChildren(
        chart.spec?.chart_type === 'bar'
            ? renderBarChart(view, chart)
            : renderLineChart(view, chart),
    );
}

interface TableCell {
    row_name: string;
    column_name: string;
    mean?: number;
    std?: number;
    minimum?: number;
    maximum?: number;
    n?: number;
}

interface TableData {
    rows?: string[];
    columns?: string[];
    cells?: TableCell[];
    spec?: {
        row?: string;
        aggregate?: string;
        precision?: number;
        missing?: string;
    };
}

function tableCell(cell: TableCell | undefined, data: TableData): string {
    if (!cell) return data.spec?.missing || '--';
    const precision = data.spec?.precision || 4;
    const number = (value: unknown): string => {
        const parsed = finite(value);
        return parsed === undefined ? (data.spec?.missing || '--') : parsed.toPrecision(precision);
    };
    if (data.spec?.aggregate === 'mean_std') {
        return `${number(cell.mean)} ± ${number(cell.std)}`;
    }
    const value = data.spec?.aggregate === 'min'
        ? cell.minimum
        : data.spec?.aggregate === 'max'
            ? cell.maximum
            : cell.mean;
    return number(value);
}

export function renderTable(
    view: ResearchAssistantWidget,
    host: HTMLElement,
    value: unknown,
): void {
    const payload = value && typeof value === 'object' ? value as JsonObject : {};
    const data = (payload.table || payload) as TableData;
    const rows = data.rows || [];
    const columns = data.columns || [];
    if (!rows.length || !columns.length) {
        host.replaceChildren(view.element('div', 'ra-empty', 'No matching final metric values.'));
        return;
    }
    const cells = new Map((data.cells || []).map(cell => [
        `${cell.row_name}\u0000${cell.column_name}`,
        cell,
    ]));
    const table = view.element('table', 'ra-data-table');
    const head = view.element('thead');
    const headRow = view.element('tr');
    headRow.append(view.element('th', undefined, data.spec?.row?.replaceAll('_', ' ') || 'row'));
    columns.forEach(column => headRow.append(view.element('th', undefined, column)));
    head.append(headRow);
    const body = view.element('tbody');
    rows.forEach(rowName => {
        const row = view.element('tr');
        row.append(view.element('th', undefined, rowName));
        columns.forEach(column => {
            row.append(view.element(
                'td',
                undefined,
                tableCell(cells.get(`${rowName}\u0000${column}`), data),
            ));
        });
        body.append(row);
    });
    table.append(head, body);
    host.replaceChildren(view.element('div', 'ra-table-scroll', undefined, [table]));
}

export function renderEvaluation(
    view: ResearchAssistantWidget,
    host: HTMLElement,
    value: unknown,
): void {
    const payload = value && typeof value === 'object' ? value as JsonObject : {};
    const evaluation = (payload.evaluation || {}) as JsonObject;
    const groups = Array.isArray(evaluation.groups) ? evaluation.groups as JsonObject[] : [];
    const runs = Array.isArray(evaluation.runs) ? evaluation.runs as JsonObject[] : [];
    const cards = view.element('div', 'ra-summary-cards', undefined, [
        summaryCard(view, 'selected', evaluation.selected_runs),
        summaryCard(view, 'eligible', evaluation.eligible_runs),
        summaryCard(view, 'excluded', evaluation.excluded_runs),
        summaryCard(view, 'groups', groups.length),
    ]);
    const groupTable = objectTable(view, groups, [
        'label', 'n', 'mean', 'std', 'minimum', 'maximum', 'seeds',
    ]);
    const runTable = objectTable(view, runs, [
        'eligible', 'trial_id', 'run_id', 'seed', 'selected_step',
        'selection_value', 'target_value', 'reason',
    ]);
    host.replaceChildren(
        cards,
        view.element('h4', undefined, 'Groups'),
        groupTable,
        view.element('h4', undefined, 'Runs'),
        runTable,
    );
}

function summaryCard(
    view: ResearchAssistantWidget,
    label: string,
    value: unknown,
): HTMLElement {
    return view.element('div', 'ra-summary-card', undefined, [
        view.element('small', 'ra-help', label),
        view.element('strong', undefined, String(value ?? 0)),
    ]);
}

function objectTable(
    view: ResearchAssistantWidget,
    rows: JsonObject[],
    columns: string[],
): HTMLElement {
    if (!rows.length) return view.element('div', 'ra-empty', 'No rows.');
    const table = view.element('table', 'ra-data-table');
    const head = view.element('thead');
    const headRow = view.element('tr');
    columns.forEach(column => headRow.append(view.element('th', undefined, column.replaceAll('_', ' '))));
    head.append(headRow);
    const body = view.element('tbody');
    rows.forEach(item => {
        const row = view.element('tr');
        columns.forEach(column => {
            const value = item[column];
            const text = Array.isArray(value)
                ? value.join(', ')
                : typeof value === 'number'
                    ? formatNumber(value)
                    : String(value ?? '—');
            row.append(view.element('td', undefined, text));
        });
        body.append(row);
    });
    table.append(head, body);
    return view.element('div', 'ra-table-scroll', undefined, [table]);
}

export function renderLiveDashboard(
    view: ResearchAssistantWidget,
    host: HTMLElement,
    value: unknown,
): void {
    const payload = value && typeof value === 'object' ? value as JsonObject : {};
    const dashboard = (payload.dashboard || payload) as JsonObject;
    const summary = (dashboard.summary || {}) as JsonObject;
    const states = (summary.states || {}) as JsonObject;
    const refresh = (payload.refresh || {}) as JsonObject;
    const cards = view.element('div', 'ra-summary-cards', undefined, [
        summaryCard(view, 'visible runs', summary.runs),
        summaryCard(view, 'job runs', summary.job_runs),
        summaryCard(view, 'running', Number(states.running || 0) + Number(states.queued || 0) + Number(states.pending || 0)),
        summaryCard(view, 'completed', states.completed),
        summaryCard(view, 'failed/interrupted', Number(states.failed || 0) + Number(states.interrupted || 0) + Number(states.cancelled || 0)),
        summaryCard(view, 'new indexed events', refresh.events_indexed),
    ]);
    const chartHost = view.element('div', 'ra-chart-grid');
    const panels = Array.isArray(dashboard.panels) ? dashboard.panels as JsonObject[] : [];
    panels.forEach(panel => {
        const chart = panel.chart as ChartData | undefined;
        if (!chart) return;
        chart.spec = { ...(chart.spec || {}), title: String(panel.metric || title(chart)) };
        chartHost.append(chart.spec?.chart_type === 'bar'
            ? renderBarChart(view, chart)
            : renderLineChart(view, chart));
    });
    if (!panels.length) chartHost.append(view.element('div', 'ra-empty', 'Waiting for metric points.'));
    const runs = Array.isArray(dashboard.runs) ? dashboard.runs as JsonObject[] : [];
    const runTable = objectTable(view, runs, [
        'state', 'run_id', 'trial_id', 'seed', 'model', 'step', 'step_kind', 'eta_seconds', 'resources',
    ]);
    host.replaceChildren(cards, chartHost, view.element('h4', undefined, 'Runs'), runTable);
}
