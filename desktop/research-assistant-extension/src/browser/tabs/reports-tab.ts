import type { ResearchAssistantWidget } from '../research-assistant-widget';
import {
    field,
    jsonEditor,
    parseObject,
    runAction,
    sectionTabs,
    select,
} from './tooling-common';
import { renderChart, renderEvaluation, renderTable } from './visualization';

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

const DEFAULT_ADVANCED = {
    name: 'advanced-chart',
    artifact_root: 'runs',
    chart_type: 'scatter',
    filters: { metrics: [], stages: [], kinds: ['final'], states: ['completed'] },
    metric: null,
    x_metric: 'validation/loss',
    y_metric: 'test/loss',
    group_by: 'trial_id',
    x_group: 'dataset',
    y_group: 'model',
    aggregate: 'mean',
    bins: 30,
    max_points: 5000,
    max_cells: 2500,
    panels: [],
    title: null,
    x_label: null,
    y_label: null,
    y_scale: 'linear',
};

export async function renderReports(view: ResearchAssistantWidget): Promise<void> {
    const catalog = view.output('Metric catalog has not been loaded.');
    const chart = jsonEditor(DEFAULT_CHART, 19);
    const table = jsonEditor(DEFAULT_TABLE, 19);
    const evaluation = jsonEditor(DEFAULT_EVALUATION, 22);
    const advanced = jsonEditor(DEFAULT_ADVANCED, 22);

    const loadCatalog = async (rebuild = false): Promise<void> => {
        catalog.textContent = view.pretty(await view.post('/api/analytics/catalog', {
            artifact_root: 'runs',
            rebuild,
        }));
    };

    const chartStatus = view.output('Preview or export a chart.');
    const chartVisual = view.element('div', 'ra-visual-preview');
    const previewChart = async (): Promise<void> => {
        const result = await runAction(
            view,
            chartStatus,
            () => view.post('/api/analytics/chart', parseObject(chart, 'Chart specification')),
        );
        renderChart(view, chartVisual, result);
    };
    const chartPanel = view.splitPane(
        view.card(
            'Chart specification',
            chart,
            view.element('div', 'ra-actions', undefined, [
                view.button('Preview', previewChart, 'primary'),
                view.button('Export PDF/SVG/PNG', () => runAction(
                    view,
                    chartStatus,
                    () => view.post('/api/analytics/chart/export', {
                        spec: parseObject(chart, 'Chart specification'),
                        formats: ['pdf', 'svg', 'png'],
                        output_path: null,
                    }),
                )),
            ]),
            chartStatus,
        ),
        view.card('Chart preview', chartVisual),
    );

    const tableStatus = view.output('Preview or export a table and LaTeX source.');
    const tableVisual = view.element('div', 'ra-visual-preview');
    const tableLatex = view.output('LaTeX has not been generated.');
    let currentTableLatex = '';
    const previewTable = async (): Promise<void> => {
        const result = await runAction(
            view,
            tableStatus,
            () => view.post<Record<string, unknown>>(
                '/api/analytics/table',
                parseObject(table, 'Table specification'),
            ),
        ) as Record<string, unknown>;
        renderTable(view, tableVisual, result);
        currentTableLatex = String(result.latex || '');
        tableLatex.textContent = currentTableLatex || 'No LaTeX returned.';
    };
    const tablePanel = view.splitPane(
        view.card(
            'Table specification',
            table,
            view.element('div', 'ra-actions', undefined, [
                view.button('Preview', previewTable, 'primary'),
                view.button('Copy LaTeX', async () => {
                    if (!currentTableLatex) throw new Error('Preview the table first.');
                    await navigator.clipboard.writeText(currentTableLatex);
                    tableStatus.textContent = 'LaTeX copied.';
                }),
                view.button('Export table + LaTeX', () => runAction(
                    view,
                    tableStatus,
                    () => view.post('/api/analytics/table/export', {
                        spec: parseObject(table, 'Table specification'),
                        output_path: null,
                    }),
                )),
            ]),
            tableStatus,
        ),
        view.card('Table preview', tableVisual, tableLatex),
    );

    const evaluationStatus = view.output('Evaluate selected checkpoints across runs.');
    const evaluationVisual = view.element('div', 'ra-visual-preview');
    const evaluationLatex = view.output('LaTeX has not been generated.');
    let currentEvaluationLatex = '';
    const previewEvaluation = async (): Promise<void> => {
        const result = await runAction(
            view,
            evaluationStatus,
            () => view.post<Record<string, unknown>>(
                '/api/analytics/evaluate',
                parseObject(evaluation, 'Evaluation specification'),
            ),
        ) as Record<string, unknown>;
        renderEvaluation(view, evaluationVisual, result);
        currentEvaluationLatex = String(result.latex || '');
        evaluationLatex.textContent = currentEvaluationLatex || 'No LaTeX returned.';
    };
    const evaluationPanel = view.splitPane(
        view.card(
            'Checkpoint-selected evaluation',
            evaluation,
            view.element('div', 'ra-actions', undefined, [
                view.button('Evaluate', previewEvaluation, 'primary'),
                view.button('Copy LaTeX', async () => {
                    if (!currentEvaluationLatex) throw new Error('Run the evaluation first.');
                    await navigator.clipboard.writeText(currentEvaluationLatex);
                    evaluationStatus.textContent = 'Evaluation LaTeX copied.';
                }),
                view.button('Export evaluation', () => runAction(
                    view,
                    evaluationStatus,
                    () => view.post('/api/analytics/evaluation/export', {
                        spec: parseObject(evaluation, 'Evaluation specification'),
                        output_path: null,
                    }),
                )),
            ]),
            evaluationStatus,
        ),
        view.card('Evaluation result', evaluationVisual, evaluationLatex),
    );

    const advancedOutputPath = view.input('Output directory', 'reports/advanced-chart');
    const advancedStatus = view.output('Preview or export an advanced chart.');
    const advancedVisual = view.element('div', 'ra-visual-preview');
    const previewAdvanced = async (): Promise<void> => {
        const result = await runAction(
            view,
            advancedStatus,
            () => view.post('/api/analytics/advanced', parseObject(
                advanced,
                'Advanced chart specification',
            )),
        );
        const payload = result && typeof result === 'object'
            ? result as Record<string, unknown>
            : {};
        if (payload.chart) renderChart(view, advancedVisual, payload);
        else advancedVisual.replaceChildren(view.output(view.pretty(result)));
    };
    const advancedPanel = view.splitPane(
        view.card(
            'Advanced chart',
            advanced,
            field(view, 'Output', advancedOutputPath),
            view.element('div', 'ra-actions', undefined, [
                view.button('Preview advanced chart', previewAdvanced, 'primary'),
                view.button('Export', () => runAction(
                    view,
                    advancedStatus,
                    () => view.post('/api/analytics/advanced/export', {
                        spec: parseObject(advanced, 'Advanced chart specification'),
                        output_path: advancedOutputPath.value.trim(),
                        formats: ['svg', 'pdf', 'png'],
                    }),
                )),
            ]),
            advancedStatus,
        ),
        view.card('Advanced preview', advancedVisual),
    );

    const specPath = view.input('YAML report spec path', 'reports/spec.yaml');
    const specKind = select(view, ['chart', 'table'], 'chart');
    const specOutput = view.output(
        'Load a saved chart/table YAML specification into the corresponding editor.',
    );
    const specs = view.splitPane(
        view.card(
            'Saved report specification',
            field(view, 'Path', specPath),
            field(view, 'Kind', specKind),
            view.button('Load spec', async () => {
                const result = await runAction(
                    view,
                    specOutput,
                    () => view.post<{ kind: string; spec: object }>(
                        '/api/analytics/spec/load',
                        { path: specPath.value.trim(), kind: specKind.value },
                    ),
                ) as { kind: string; spec: object };
                const target = result.kind === 'table' ? table : chart;
                target.value = JSON.stringify(result.spec, null, 2);
            }, 'primary'),
        ),
        view.card('Loaded spec', specOutput),
    );

    const indexPanel = view.splitPane(
        view.card(
            'Metric index',
            view.element('div', 'ra-actions', undefined, [
                view.button('Refresh index', () => loadCatalog(false), 'primary'),
                view.button('Rebuild index', () => loadCatalog(true)),
            ]),
        ),
        view.card('Catalog', catalog),
    );

    view.content.replaceChildren(sectionTabs(view, [
        { id: 'index', label: 'Metric index', node: indexPanel },
        { id: 'charts', label: 'Charts', node: chartPanel },
        { id: 'advanced', label: 'Advanced plots', node: advancedPanel },
        { id: 'tables', label: 'Tables', node: tablePanel },
        { id: 'evaluation', label: 'Evaluation', node: evaluationPanel },
        { id: 'specs', label: 'Saved specs', node: specs },
    ]));
    await loadCatalog(false);
}
