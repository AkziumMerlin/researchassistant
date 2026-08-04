import type { ResearchAssistantWidget } from '../research-assistant-widget';

const DEFAULT_CHART = {
    name: 'learning-curves',
    artifact_root: 'runs',
    filters: { metrics: [], stages: [], kinds: ['progress'], states: ['completed'] },
    chart_type: 'line',
    group_by: 'trial_id',
    aggregate: 'mean',
    uncertainty: 'std',
    max_points: 1000,
    max_series: 50,
    y_scale: 'linear',
    title: null,
    x_label: 'step',
    y_label: null,
};

const DEFAULT_TABLE = {
    name: 'benchmark-table',
    artifact_root: 'runs',
    filters: { metrics: [], kinds: ['final'], states: ['completed'] },
    row: 'dataset',
    column: 'model',
    aggregate: 'mean_std',
    precision: 4,
    direction: 'minimize',
    bold_best: true,
    underline_second: false,
    caption: null,
    label: null,
    missing: '--',
    max_rows: 100,
    max_columns: 50,
};

const DEFAULT_EVALUATION = {
    name: 'selected-checkpoint-evaluation',
    artifact_root: 'runs',
    filters: { states: ['completed'] },
    selection_metric: 'validation/loss',
    target_metric: 'test/loss',
    stage: null,
    selection_split: 'validation',
    target_split: 'test',
    selection_kind: 'progress',
    target_kind: 'progress',
    direction: 'minimize',
    alignment: 'same_step',
    group_by: ['dataset', 'model'],
    precision: 4,
    table_direction: 'minimize',
    bold_best: true,
    underline_second: false,
    caption: null,
    label: null,
    max_runs: 2000,
};

export async function renderReports(view: ResearchAssistantWidget): Promise<void> {
    const output = view.output('Choose a report operation.');
    const catalog = view.output('Metric catalog has not been loaded.');
    const chart = editor(DEFAULT_CHART);
    const table = editor(DEFAULT_TABLE);
    const evaluation = editor(DEFAULT_EVALUATION);

    const parse = (area: HTMLTextAreaElement): Record<string, unknown> => {
        const value = JSON.parse(area.value);
        if (!value || typeof value !== 'object' || Array.isArray(value)) {
            throw new Error('Report specification must be a JSON object.');
        }
        return value as Record<string, unknown>;
    };

    const run = async (operation: () => Promise<unknown>): Promise<void> => {
        try {
            output.classList.remove('error');
            output.textContent = view.pretty(await operation());
        } catch (error) {
            output.classList.add('error');
            output.textContent = error instanceof Error ? error.message : String(error);
        }
    };

    const loadCatalog = async (rebuild = false): Promise<void> => {
        catalog.textContent = view.pretty(await view.post('/api/analytics/catalog', {
            artifact_root: 'runs',
            rebuild,
        }));
    };

    const chartActions = view.element('div', 'ra-actions', undefined, [
        view.button('Preview chart', () => run(() => view.post('/api/analytics/chart', parse(chart))), 'primary'),
        view.button('Export chart', () => run(() => view.post('/api/analytics/chart/export', {
            spec: parse(chart),
            formats: ['pdf', 'svg', 'png'],
            output_path: null,
        }))),
    ]);
    const tableActions = view.element('div', 'ra-actions', undefined, [
        view.button('Preview table', () => run(() => view.post('/api/analytics/table', parse(table))), 'primary'),
        view.button('Export table', () => run(() => view.post('/api/analytics/table/export', {
            spec: parse(table),
            output_path: null,
        }))),
    ]);
    const evaluationActions = view.element('div', 'ra-actions', undefined, [
        view.button('Evaluate', () => run(() => view.post('/api/analytics/evaluate', parse(evaluation))), 'primary'),
        view.button('Export evaluation', () => run(() => view.post('/api/analytics/evaluation/export', {
            spec: parse(evaluation),
            output_path: null,
        }))),
    ]);

    const catalogActions = view.element('div', 'ra-actions', undefined, [
        view.button('Refresh index', () => loadCatalog(false)),
        view.button('Rebuild index', () => loadCatalog(true)),
    ]);

    view.content.replaceChildren(
        view.element('div', 'ra-report-grid', undefined, [
            view.card('Metric index', catalogActions, catalog),
            view.card('Chart specification', chart, chartActions),
            view.card('Table specification', table, tableActions),
            view.card('Checkpoint-selected evaluation', evaluation, evaluationActions),
        ]),
        view.card('Report output', output),
    );
    await loadCatalog(false);
}

function editor(value: Record<string, unknown>): HTMLTextAreaElement {
    const area = document.createElement('textarea');
    area.className = 'ra-spec-editor';
    area.spellcheck = false;
    area.value = JSON.stringify(value, null, 2);
    return area;
}
