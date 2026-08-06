import type { ResearchAssistantWidget } from '../research-assistant-widget';
import { field, runAction, select } from './tooling-common';
import { renderChart } from './visualization';

interface TensorBoardRun {
    name: string;
    path: string;
    event_file_count: number;
    scalar_tags: string[];
    point_count: number;
}

interface TensorBoardTag {
    name: string;
    runs: number;
    points: number;
}

interface TensorBoardCatalog {
    root: string;
    event_files: number;
    run_count: number;
    runs: TensorBoardRun[];
    runs_truncated: boolean;
    tags: TensorBoardTag[];
    tag_count: number;
    unsupported: Record<string, number>;
    errors: string[];
    truncated: boolean;
    cache_hit: boolean;
}

interface TensorBoardChartResult {
    chart?: unknown;
    warnings?: string[];
    source?: Record<string, unknown>;
}

function numeric(input: HTMLInputElement, label: string): number {
    const value = Number(input.value);
    if (!Number.isFinite(value)) throw new Error(`${label} must be a number.`);
    return value;
}

function scrollList(view: ResearchAssistantWidget): HTMLDivElement {
    const list = view.element('div', 'ra-tensorboard-list');
    list.style.display = 'grid';
    list.style.gap = '4px';
    list.style.maxHeight = '320px';
    list.style.overflow = 'auto';
    list.style.padding = '4px';
    return list;
}

function selectionRow(
    view: ResearchAssistantWidget,
    label: string,
    detail: string,
    checked: boolean,
    change: (checked: boolean) => void,
): HTMLLabelElement {
    const row = view.element('label', 'ra-tensorboard-option');
    row.style.display = 'grid';
    row.style.gridTemplateColumns = 'auto minmax(0, 1fr)';
    row.style.gap = '8px';
    row.style.alignItems = 'start';
    row.style.padding = '5px 4px';
    const checkbox = view.element('input');
    checkbox.type = 'checkbox';
    checkbox.checked = checked;
    checkbox.addEventListener('change', () => change(checkbox.checked));
    const text = view.element('span');
    text.append(
        view.element('span', undefined, label),
        view.element('small', 'ra-help', detail),
    );
    text.style.display = 'grid';
    row.append(checkbox, text);
    return row;
}

function recommendedTags(tags: TensorBoardTag[]): string[] {
    const metric = /(^|[/_.-])(loss|accuracy|acc|error|rmse|mae)([/_.-]|$)/i;
    const recommended = tags.filter(tag => metric.test(tag.name)).slice(0, 6);
    return (recommended.length ? recommended : tags.slice(0, 4)).map(tag => tag.name);
}

export function renderTensorBoardPanel(view: ResearchAssistantWidget): HTMLElement {
    const logdir = view.input('TensorBoard log directory', 'runs');
    const scanStatus = view.output(
        'Choose a directory containing events.out.tfevents.* files, then scan it.',
    );
    const catalogSummary = view.element('div', 'ra-help');
    const runFilter = view.input('Filter runs');
    const tagFilter = view.input('Filter scalar tags');
    const runList = scrollList(view);
    const tagList = scrollList(view);
    const selectedRuns = new Set<string>();
    const selectedTags = new Set<string>();
    let catalog: TensorBoardCatalog | undefined;

    const renderRuns = (): void => {
        runList.replaceChildren();
        const query = runFilter.value.trim().toLocaleLowerCase();
        const rows = (catalog?.runs || []).filter(run => (
            !query || `${run.name} ${run.path}`.toLocaleLowerCase().includes(query)
        ));
        if (!rows.length) {
            runList.append(view.element('div', 'ra-empty', 'No matching TensorBoard runs.'));
            return;
        }
        for (const run of rows) {
            runList.append(selectionRow(
                view,
                run.name,
                `${run.scalar_tags.length} scalar tag(s), ${run.point_count} points, `
                    + `${run.event_file_count} event file(s)`,
                selectedRuns.has(run.name),
                checked => {
                    if (checked) selectedRuns.add(run.name);
                    else selectedRuns.delete(run.name);
                },
            ));
        }
    };

    const renderTags = (): void => {
        tagList.replaceChildren();
        const query = tagFilter.value.trim().toLocaleLowerCase();
        const rows = (catalog?.tags || []).filter(tag => (
            !query || tag.name.toLocaleLowerCase().includes(query)
        ));
        if (!rows.length) {
            tagList.append(view.element('div', 'ra-empty', 'No matching scalar tags.'));
            return;
        }
        for (const tag of rows) {
            tagList.append(selectionRow(
                view,
                tag.name,
                `${tag.runs} run(s), ${tag.points} points`,
                selectedTags.has(tag.name),
                checked => {
                    if (checked) selectedTags.add(tag.name);
                    else selectedTags.delete(tag.name);
                },
            ));
        }
    };

    runFilter.addEventListener('input', renderRuns);
    tagFilter.addEventListener('input', renderTags);

    const scan = async (reload: boolean): Promise<void> => {
        const firstScan = catalog === undefined;
        const result = await runAction(
            view,
            scanStatus,
            () => view.post<TensorBoardCatalog>('/api/tensorboard/catalog', {
                logdir: logdir.value.trim(),
                reload,
                max_runs: 1000,
            }),
        ) as TensorBoardCatalog;
        catalog = result;
        const availableRuns = new Set(result.runs.map(run => run.name));
        const availableTags = new Set(result.tags.map(tag => tag.name));
        for (const name of [...selectedRuns]) {
            if (!availableRuns.has(name)) selectedRuns.delete(name);
        }
        for (const name of [...selectedTags]) {
            if (!availableTags.has(name)) selectedTags.delete(name);
        }
        if (firstScan || !selectedRuns.size) {
            result.runs.forEach(run => selectedRuns.add(run.name));
        }
        if (firstScan || !selectedTags.size) {
            recommendedTags(result.tags).forEach(tag => selectedTags.add(tag));
        }
        renderRuns();
        renderTags();
        const unsupported = Object.entries(result.unsupported)
            .map(([kind, count]) => `${kind}: ${count}`)
            .join(', ');
        const notes = [
            `${result.run_count} run(s), ${result.tag_count} scalar tag(s), `
                + `${result.event_files} event file(s)`,
            result.cache_hit ? 'cached' : 'reloaded',
        ];
        if (result.runs_truncated) notes.push('run list truncated');
        if (result.truncated) notes.push('scan limit reached');
        if (unsupported) notes.push(`unsupported summaries: ${unsupported}`);
        if (result.errors.length) notes.push(`${result.errors.length} parse error(s)`);
        catalogSummary.textContent = notes.join(' · ');
        scanStatus.textContent = result.errors.length
            ? result.errors.slice(0, 8).join('\n')
            : `TensorBoard catalog loaded from ${result.root}.`;
    };

    const xAxis = select(view, ['step', 'relative_time', 'wall_time'], 'step');
    const smoothing = view.input('Smoothing', '0');
    smoothing.type = 'number';
    smoothing.min = '0';
    smoothing.max = '0.999';
    smoothing.step = '0.05';
    const maxPoints = view.input('Maximum points per series', '1000');
    maxPoints.type = 'number';
    maxPoints.min = '20';
    maxPoints.max = '5000';
    maxPoints.step = '10';
    const maxSeries = view.input('Maximum series', '50');
    maxSeries.type = 'number';
    maxSeries.min = '1';
    maxSeries.max = '200';
    const yScale = select(view, ['linear', 'log'], 'linear');
    const chartTitle = view.input('Chart title (optional)');
    const chartStatus = view.output('Select runs and scalar tags, then preview the chart.');
    const chartVisual = view.element('div', 'ra-visual-preview');

    const preview = async (): Promise<void> => {
        if (!catalog) throw new Error('Scan a TensorBoard log directory first.');
        if (!selectedRuns.size) throw new Error('Select at least one TensorBoard run.');
        if (!selectedTags.size) throw new Error('Select at least one scalar tag.');
        const smoothingValue = numeric(smoothing, 'Smoothing');
        if (smoothingValue < 0 || smoothingValue > 0.999) {
            throw new Error('Smoothing must be between 0 and 0.999.');
        }
        const pointsValue = numeric(maxPoints, 'Maximum points');
        const seriesValue = numeric(maxSeries, 'Maximum series');
        const result = await runAction(
            view,
            chartStatus,
            () => view.post<TensorBoardChartResult>('/api/tensorboard/chart', {
                logdir: logdir.value.trim(),
                runs: [...selectedRuns],
                tags: [...selectedTags],
                x_axis: xAxis.value,
                smoothing: smoothingValue,
                max_points: pointsValue,
                max_series: seriesValue,
                y_scale: yScale.value,
                title: chartTitle.value.trim() || null,
                reload: false,
            }),
        ) as TensorBoardChartResult;
        renderChart(view, chartVisual, result);
        const warnings = result.warnings || [];
        chartStatus.textContent = warnings.length
            ? `Chart rendered.\n${warnings.join('\n')}`
            : 'Chart rendered from TensorBoard event files.';
    };

    const sourcePanel = view.card(
        'TensorBoard event logs',
        field(
            view,
            'Log directory',
            logdir,
            'Path inside the connected workspace. Event files are read by the remote sidecar.',
        ),
        view.element('div', 'ra-actions', undefined, [
            view.button('Scan', () => scan(false), 'primary'),
            view.button('Force reload', () => scan(true)),
        ]),
        catalogSummary,
        scanStatus,
    );

    const runsPanel = view.card(
        'Runs',
        runFilter,
        view.element('div', 'ra-actions', undefined, [
            view.button('Select all', () => {
                catalog?.runs.forEach(run => selectedRuns.add(run.name));
                renderRuns();
            }),
            view.button('Clear', () => {
                selectedRuns.clear();
                renderRuns();
            }),
        ]),
        runList,
    );
    const tagsPanel = view.card(
        'Scalar tags',
        tagFilter,
        view.element('div', 'ra-actions', undefined, [
            view.button('Common metrics', () => {
                selectedTags.clear();
                recommendedTags(catalog?.tags || []).forEach(tag => selectedTags.add(tag));
                renderTags();
            }),
            view.button('Select all', () => {
                catalog?.tags.forEach(tag => selectedTags.add(tag.name));
                renderTags();
            }),
            view.button('Clear', () => {
                selectedTags.clear();
                renderTags();
            }),
        ]),
        tagList,
    );

    const chartControls = view.card(
        'Scalar chart',
        field(view, 'X axis', xAxis),
        field(view, 'Smoothing', smoothing),
        field(view, 'Maximum points per series', maxPoints),
        field(view, 'Maximum series', maxSeries),
        field(view, 'Y scale', yScale),
        field(view, 'Title', chartTitle),
        view.button('Preview TensorBoard chart', preview, 'primary'),
        chartStatus,
    );

    return view.element('div', undefined, undefined, [
        sourcePanel,
        view.splitPane(runsPanel, tagsPanel),
        view.splitPane(chartControls, view.card('TensorBoard chart', chartVisual)),
    ]);
}
