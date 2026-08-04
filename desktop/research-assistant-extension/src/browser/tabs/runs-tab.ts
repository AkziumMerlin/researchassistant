import type { ResearchAssistantWidget } from '../research-assistant-widget';

interface RunRow {
    run_id: string;
    study_id?: string;
    trial_id?: string;
    state?: string;
    seed?: number;
    model?: string;
    dataset?: string;
}

export async function renderRuns(view: ResearchAssistantWidget): Promise<void> {
    const payload = await view.get<{ runs: RunRow[]; total: number; studies: string[] }>(
        '/api/workspace/runs?artifact_root=runs&limit=10000',
    );
    const rows = payload.runs || [];
    const toolbar = view.element('div', 'ra-toolbar');
    const query = view.input('Filter study, trial, run, model or dataset');
    const metric = view.input('Metric name (optional)');
    const groupBy = view.input('Group by', 'study_id,trial_id');
    const summary = view.element(
        'span',
        'ra-summary',
        `${payload.total ?? rows.length} runs · ${(payload.studies || []).length} studies`,
    );
    toolbar.append(query, metric, groupBy, summary);

    const list = view.element('div', 'ra-virtual-list ra-run-list');
    const output = view.output('Select runs from any studies and aggregate them explicitly.');

    const overview = view.output('Load the indexed run, metric and resource overview.');
    const overviewStage = view.input('Overview stage (optional)');
    const overviewMetric = view.input('Overview metric (optional)');
    const loadOverview = view.button('Load run overview', async () => {
        overview.textContent = view.pretty(await view.post('/api/runs/catalog', {
            artifact_root: 'runs',
            stage: overviewStage.value.trim() || null,
            metric: overviewMetric.value.trim() || null,
            trial_ids: [],
            limit: 5000,
        }));
    });
    const render = (): void => {
        const needle = query.value.trim().toLowerCase();
        const fragment = document.createDocumentFragment();
        for (const row of rows) {
            const searchable = [
                row.study_id,
                row.trial_id,
                row.run_id,
                row.model,
                row.dataset,
                row.state,
            ].join(' ').toLowerCase();
            if (needle && !searchable.includes(needle)) {
                continue;
            }
            const checkbox = document.createElement('input');
            checkbox.type = 'checkbox';
            checkbox.checked = view.selectedRuns.has(row.run_id);
            checkbox.addEventListener('change', () => {
                if (checkbox.checked) {
                    view.selectedRuns.add(row.run_id);
                } else {
                    view.selectedRuns.delete(row.run_id);
                }
                summary.textContent = `${rows.length} runs · ${view.selectedRuns.size} selected`;
            });
            const identity = view.element('div', 'ra-identity');
            identity.append(
                view.element('strong', undefined, `${row.study_id || 'study'} / ${row.run_id}`),
                view.element(
                    'small',
                    undefined,
                    `${row.trial_id || 'trial'} · seed ${row.seed ?? '—'} · ${row.model || 'model?'} · ${row.dataset || 'data?'}`,
                ),
            );
            fragment.append(
                view.row([
                    checkbox,
                    identity,
                    view.element('span', `ra-state ${row.state || 'unknown'}`, row.state || 'unknown'),
                    view.button('Inspect', async () => {
                        output.textContent = view.pretty(await view.get(
                            `/api/workspace/runs/${encodeURIComponent(row.run_id)}?artifact_root=runs`,
                        ));
                    }),
                ]),
            );
        }
        list.replaceChildren(fragment);
    };
    query.addEventListener('input', render);
    render();

    const aggregate = view.button('Aggregate selected runs', async () => {
        if (!view.selectedRuns.size) {
            throw new Error('Select at least one run.');
        }
        output.textContent = view.pretty(await view.post('/api/workspace/runs/aggregate', {
            artifact_root: 'runs',
            run_ids: [...view.selectedRuns],
            metric: metric.value.trim() || null,
            stage: null,
            group_by: view.split(groupBy.value),
        }));
    }, 'primary');
    view.safeClick(aggregate, output);
    view.content.replaceChildren(
        toolbar,
        view.splitPane(
            view.card('Runs', list),
            view.element('div', 'ra-tool-stack', undefined, [
                view.card('Cross-run aggregation', metric, groupBy, aggregate, output),
                view.card('Run and resource overview', overviewStage, overviewMetric, loadOverview, overview),
            ]),
        ),
    );
}
