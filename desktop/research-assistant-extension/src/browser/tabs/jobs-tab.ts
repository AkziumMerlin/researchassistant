import type { ResearchAssistantWidget } from '../research-assistant-widget';
import {
    field,
    jsonEditor,
    parseObject,
    runAction,
    saveStorageJson,
    sectionTabs,
    select,
    storageJson,
    textArea,
} from './tooling-common';
import { renderLiveDashboard } from './visualization';

interface JobRow {
    job_id?: string;
    id?: string;
    state?: string;
    config_path?: string;
    artifact_root?: string;
    created_at?: string;
    updated_at?: string;
    run_count?: number;
}

interface JobDetail extends JobRow {
    runs?: Array<Record<string, unknown>>;
    plan?: { run_ids?: string[] };
}

const DEFAULT_LIVE = {
    metrics: [],
    stages: [],
    kinds: ['progress'],
    states: [],
    trial_ids: [],
    run_ids: [],
    models: [],
    datasets: [],
    splits: [],
    search: '',
    active_only: true,
    group_by: 'run_id',
    aggregate: 'mean',
    uncertainty: 'none',
    max_points: 800,
    max_series: 80,
    y_scale: 'linear',
    cursor: {},
};

export async function renderJobs(view: ResearchAssistantWidget): Promise<void> {
    let selectedJob = '';
    let selectedRun = '';
    let polling = false;
    let disposed = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let liveCursor: Record<string, unknown> = {};
    const jobList = view.element('div', 'ra-virtual-list');
    const detailOutput = view.output('Select a job to inspect its persistent scheduler and runs.');
    const summary = view.element('span', 'ra-summary', 'Loading jobs…');
    const autoRefresh = document.createElement('input');
    autoRefresh.type = 'checkbox';
    autoRefresh.checked = true;

    const config = view.input('Config path', 'configs/experiment.yaml');
    const launcher = view.input('Launcher policy (optional)');
    const artifacts = view.input('Artifact root', 'runs');
    const overrides = textArea('Config overrides, one per line', '', 4);
    const launcherOverrides = textArea('Launcher overrides, one per line', '', 4);
    const resume = document.createElement('input');
    resume.type = 'checkbox';
    resume.checked = true;
    const createOutput = view.output('Preview or start a persistent experiment job.');

    const requestBody = (): Record<string, unknown> => ({
        config_path: config.value.trim(),
        launcher_path: launcher.value.trim() || null,
        artifact_root: artifacts.value.trim() || null,
        resume: resume.checked,
        overrides: view.split(overrides.value),
        launcher_overrides: view.split(launcherOverrides.value),
    });

    const renderJobs = (jobs: JobRow[]): void => {
        const fragment = document.createDocumentFragment();
        for (const job of jobs) {
            const id = String(job.job_id || job.id || '');
            if (!id) continue;
            const identity = view.element('div', 'ra-identity', undefined, [
                view.element('strong', undefined, id),
                view.element(
                    'small',
                    undefined,
                    `${job.config_path || 'config?'} · ${job.artifact_root || 'runs'} · ${job.updated_at || job.created_at || ''}`,
                ),
            ]);
            const actions = view.element('div', 'ra-actions', undefined, [
                view.button('Open', async () => {
                    selectedJob = id;
                    liveCursor = {};
                    await loadDetail();
                }, selectedJob === id ? 'primary' : ''),
                view.button('Recover', () => runAction(view, detailOutput, () => view.post(`/api/jobs/${encodeURIComponent(id)}/recover`, {}), load)),
                view.button('Adopt', () => runAction(view, detailOutput, () => view.post(`/api/jobs/${encodeURIComponent(id)}/adopt`, {}), load)),
                view.button('Cancel', () => runAction(view, detailOutput, () => view.post(`/api/jobs/${encodeURIComponent(id)}/cancel`, {}), load), 'danger'),
            ]);
            fragment.append(view.row([
                identity,
                view.element('span', `ra-state ${job.state || 'unknown'}`, job.state || 'unknown'),
                actions,
            ]));
        }
        jobList.replaceChildren(fragment);
        summary.textContent = `${jobs.length} job(s)${selectedJob ? ` · selected ${selectedJob}` : ''}`;
    };

    const load = async (): Promise<void> => {
        const payload = await view.get<{ jobs: JobRow[] }>('/api/jobs');
        if (!disposed) renderJobs(payload.jobs || []);
    };

    const loadDetail = async (): Promise<void> => {
        if (!selectedJob) throw new Error('Select a job first.');
        const result = await view.get<JobDetail>(`/api/jobs/${encodeURIComponent(selectedJob)}`);
        detailOutput.textContent = view.pretty(result);
        const runs = (result.runs || []).map(row => String(row.run_id || '')).filter(Boolean);
        if (!selectedRun || !runs.includes(selectedRun)) selectedRun = runs[0] || '';
        summary.textContent = `${selectedJob} · ${result.state || 'unknown'} · ${runs.length} run(s)`;
    };

    const schedule = (): void => {
        if (disposed || !autoRefresh.checked) return;
        timer = setTimeout(async () => {
            if (!polling) {
                polling = true;
                try {
                    await load();
                    if (selectedJob) {
                        await loadDetail();
                        if (liveAutoRefresh.checked) await queryLive(true);
                    }
                } catch {
                    // A temporary remote disconnect is surfaced by the backend status.
                } finally {
                    polling = false;
                }
            }
            schedule();
        }, 3000);
    };
    view.setTabCleanup(() => {
        disposed = true;
        if (timer) clearTimeout(timer);
    });

    const resumeLabel = view.element('label', 'ra-check');
    resumeLabel.append(resume, document.createTextNode(' Resume compatible runs'));
    const createCard = view.card(
        'Start persistent job',
        field(view, 'Config', config),
        field(view, 'Launcher policy', launcher),
        field(view, 'Artifact root', artifacts),
        resumeLabel,
        field(view, 'Config overrides', overrides),
        field(view, 'Launcher overrides', launcherOverrides),
        view.element('div', 'ra-actions', undefined, [
            view.button('Preview', () => runAction(view, createOutput, () => view.post('/api/jobs/preview', requestBody()))),
            view.button('Start job', () => runAction(view, createOutput, () => view.post('/api/jobs', requestBody()), load), 'primary'),
        ]),
        createOutput,
    );

    const refreshLabel = view.element('label', 'ra-check');
    refreshLabel.append(autoRefresh, document.createTextNode(' Auto-refresh every 3s'));
    const existingCard = view.card(
        'Persistent jobs',
        view.element('div', 'ra-toolbar', undefined, [
            view.button('Refresh', load),
            refreshLabel,
            summary,
        ]),
        jobList,
    );
    const overview = view.splitPane(existingCard, view.card('Selected job', detailOutput));

    const source = select(view, ['scheduler', 'worker'], 'scheduler');
    const logRun = view.input('Run ID (worker log)');
    const tail = document.createElement('input');
    tail.type = 'checkbox';
    tail.checked = true;
    const logOutput = view.output('Select a job and read scheduler or worker logs.');
    const logTail = view.element('label', 'ra-check');
    logTail.append(tail, document.createTextNode(' Read tail'));
    const logs = view.splitPane(
        view.card(
            'Log query',
            field(view, 'Source', source),
            field(view, 'Run', logRun),
            logTail,
            view.button('Read logs', () => {
                if (!selectedJob) throw new Error('Select a job first.');
                const query = new URLSearchParams({
                    source: source.value,
                    limit: '262144',
                    tail: String(tail.checked),
                });
                const runId = logRun.value.trim() || selectedRun;
                if (runId) query.set('run_id', runId);
                return runAction(view, logOutput, () => view.get(`/api/jobs/${encodeURIComponent(selectedJob)}/logs?${query}`));
            }, 'primary'),
        ),
        view.card('Log output', logOutput),
    );

    const metricRun = view.input('Run ID');
    const since = view.input('Since sequence', '0');
    const metricOutput = view.output('Read bounded raw metric events for one run.');
    const metrics = view.splitPane(
        view.card(
            'Metric stream',
            field(view, 'Run', metricRun),
            field(view, 'Cursor', since),
            view.button('Read metrics', () => {
                if (!selectedJob) throw new Error('Select a job first.');
                const runId = metricRun.value.trim() || selectedRun;
                if (!runId) throw new Error('Set a run ID.');
                const query = new URLSearchParams({
                    run_id: runId,
                    since_sequence: since.value || '0',
                    limit: '5000',
                });
                return runAction(view, metricOutput, () => view.get(`/api/jobs/${encodeURIComponent(selectedJob)}/metrics?${query}`));
            }, 'primary'),
        ),
        view.card('Metric events', metricOutput),
    );

    const liveSpec = jsonEditor(DEFAULT_LIVE, 18);
    const liveOutput = view.output('Query a live multi-run dashboard for the selected job.');
    const liveVisual = view.element('div', 'ra-live-dashboard');
    const liveAutoRefresh = document.createElement('input');
    liveAutoRefresh.type = 'checkbox';
    liveAutoRefresh.checked = true;
    const liveAutoLabel = view.element('label', 'ra-check');
    liveAutoLabel.append(liveAutoRefresh, document.createTextNode(' Refresh dashboard every 3s'));
    const viewName = view.input('Saved view name', 'active-runs');
    const savedSelect = view.element('select', 'theia-select');
    const savedViews = storageJson<Record<string, object>>('ra.jobs.live-views', {});
    const renderSaved = (): void => {
        savedSelect.replaceChildren();
        const empty = view.element('option', undefined, 'Select saved view');
        empty.value = '';
        savedSelect.append(empty);
        for (const name of Object.keys(savedViews).sort()) {
            const option = view.element('option', undefined, name);
            option.value = name;
            savedSelect.append(option);
        }
    };
    renderSaved();
    const queryLive = async (silent = false): Promise<void> => {
        if (!selectedJob) {
            if (!silent) throw new Error('Select a job first.');
            return;
        }
        const spec = parseObject(liveSpec, 'Live dashboard spec');
        const result = await view.post<Record<string, unknown>>(
            `/api/jobs/${encodeURIComponent(selectedJob)}/live-metrics`,
            { ...spec, cursor: liveCursor },
        );
        const dashboard = result.dashboard && typeof result.dashboard === 'object'
            ? result.dashboard as Record<string, unknown>
            : {};
        liveCursor = dashboard.cursor && typeof dashboard.cursor === 'object'
            ? dashboard.cursor as Record<string, unknown>
            : {};
        renderLiveDashboard(view, liveVisual, result);
        liveOutput.classList.remove('error');
        liveOutput.textContent = view.pretty({
            selected_metrics: dashboard.selected_metrics || [],
            catalog: dashboard.catalog || {},
            refresh: result.refresh || {},
        });
    };
    const live = view.splitPane(
        view.card(
            'Live dashboard specification',
            field(view, 'Spec', liveSpec),
            liveAutoLabel,
            view.element('div', 'ra-actions', undefined, [
                view.button('Query live dashboard', async () => {
                    liveOutput.textContent = 'Working…';
                    try {
                        await queryLive(false);
                    } catch (error) {
                        liveOutput.classList.add('error');
                        liveOutput.textContent = error instanceof Error ? error.message : String(error);
                        throw error;
                    }
                }, 'primary'),
                view.button('Reset cursor', async () => {
                    liveCursor = {};
                    await queryLive(false);
                }),
                view.button('Save view', () => {
                    const name = viewName.value.trim();
                    if (!name) throw new Error('Set a view name.');
                    const value = parseObject(liveSpec, 'Live dashboard spec');
                    delete value.cursor;
                    savedViews[name] = value;
                    saveStorageJson('ra.jobs.live-views', savedViews);
                    renderSaved();
                    savedSelect.value = name;
                    liveOutput.textContent = `Saved ${name}`;
                }),
                view.button('Load view', () => {
                    const value = savedViews[savedSelect.value];
                    if (!value) throw new Error('Select a saved view.');
                    liveSpec.value = JSON.stringify(value, null, 2);
                    liveCursor = {};
                }),
                view.button('Delete view', () => {
                    if (!savedSelect.value) throw new Error('Select a saved view.');
                    delete savedViews[savedSelect.value];
                    saveStorageJson('ra.jobs.live-views', savedViews);
                    renderSaved();
                }, 'danger'),
            ]),
            view.element('div', 'ra-row compact', undefined, [viewName, savedSelect]),
            liveOutput,
        ),
        view.card('Live charts and run state', liveVisual),
    );

    const artifactRun = view.input('Run ID');
    const artifactPath = view.input('Artifact path for preview');
    const artifactOutput = view.output('List or preview job artifacts.');
    const jobArtifacts = view.splitPane(
        view.card(
            'Job artifacts',
            field(view, 'Run', artifactRun),
            field(view, 'Path', artifactPath),
            view.element('div', 'ra-actions', undefined, [
                view.button('List', () => {
                    if (!selectedJob) throw new Error('Select a job first.');
                    const runId = artifactRun.value.trim() || selectedRun;
                    if (!runId) throw new Error('Set a run ID.');
                    return runAction(
                        view,
                        artifactOutput,
                        () => view.get(`/api/jobs/${encodeURIComponent(selectedJob)}/artifacts?run_id=${encodeURIComponent(runId)}&limit=5000`),
                    );
                }, 'primary'),
                view.button('Preview path', () => {
                    if (!selectedJob) throw new Error('Select a job first.');
                    const runId = artifactRun.value.trim() || selectedRun;
                    if (!runId || !artifactPath.value.trim()) throw new Error('Set a run ID and artifact path.');
                    const query = new URLSearchParams({
                        run_id: runId,
                        path: artifactPath.value.trim(),
                        cursor: '0',
                        limit: '262144',
                    });
                    return runAction(view, artifactOutput, () => view.get(`/api/jobs/${encodeURIComponent(selectedJob)}/artifacts/preview?${query}`));
                }),
            ]),
        ),
        view.card('Artifact output', artifactOutput),
    );

    view.content.replaceChildren(sectionTabs(view, [
        { id: 'overview', label: 'Jobs', node: view.element('div', 'ra-tool-stack', undefined, [overview, createCard]) },
        { id: 'live', label: 'Live metrics', node: live },
        { id: 'logs', label: 'Logs', node: logs },
        { id: 'metrics', label: 'Metric events', node: metrics },
        { id: 'artifacts', label: 'Job artifacts', node: jobArtifacts },
    ]));
    await load();
    schedule();
}
