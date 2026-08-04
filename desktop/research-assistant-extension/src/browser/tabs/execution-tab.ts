import type { ResearchAssistantWidget } from '../research-assistant-widget';

interface LaunchRow {
    launch_id?: string;
    id?: string;
    state?: string;
    config_path?: string;
    artifact_root?: string;
    worker_pid?: number;
    detail?: string;
}

interface LaunchList {
    launches: LaunchRow[];
}

export async function renderExecution(view: ResearchAssistantWidget): Promise<void> {
    const configPath = view.input('Experiment config', 'configs/experiment.yaml');
    const launcherPath = view.input('Launcher policy (optional)');
    const artifactRoot = view.input('Artifact root (optional)', 'runs');
    const overrides = document.createElement('textarea');
    overrides.placeholder = 'Config overrides, one per line: components.model.params.width=128';
    const launcherOverrides = document.createElement('textarea');
    launcherOverrides.placeholder = 'Launcher overrides, one per line';
    const resume = document.createElement('input');
    resume.type = 'checkbox';
    resume.checked = true;

    const rows = view.element('div', 'ra-virtual-list');
    const output = view.output('Preview a launch or inspect existing durable launches.');
    const summary = view.element('span', 'ra-summary', 'Loading launches…');

    const requestBody = (): Record<string, unknown> => ({
        config_path: configPath.value.trim(),
        launcher_path: launcherPath.value.trim() || null,
        artifact_root: artifactRoot.value.trim() || null,
        resume: resume.checked,
        overrides: view.split(overrides.value),
        launcher_overrides: view.split(launcherOverrides.value),
    });

    const runAction = async (action: () => Promise<unknown>): Promise<void> => {
        try {
            output.classList.remove('error');
            output.textContent = view.pretty(await action());
            await load();
        } catch (error) {
            output.classList.add('error');
            output.textContent = error instanceof Error ? error.message : String(error);
        }
    };

    const renderRows = (launches: LaunchRow[]): void => {
        const fragment = document.createDocumentFragment();
        for (const launch of launches) {
            const id = String(launch.launch_id || launch.id || 'launch');
            const state = String(launch.state || 'unknown');
            const identity = view.element('div', 'ra-identity');
            identity.append(
                view.element('strong', undefined, id),
                view.element(
                    'small',
                    undefined,
                    `${launch.config_path || 'config?'} · ${launch.artifact_root || 'runs'}${launch.worker_pid ? ` · pid ${launch.worker_pid}` : ''}`,
                ),
            );
            const actions = view.element('div', 'ra-actions');
            actions.append(
                view.button('Inspect', () => runAction(() => view.get(`/api/launches/${encodeURIComponent(id)}`))),
                view.button('Adopt', () => runAction(() => view.post(`/api/workspace/launches/${encodeURIComponent(id)}/adopt`, {}))),
                view.button('Retry', () => runAction(() => view.post(`/api/workspace/launches/${encodeURIComponent(id)}/retry`, {}))),
                view.button('Cancel', () => runAction(() => view.post(`/api/workspace/launches/${encodeURIComponent(id)}/cancel`, { force: false }))),
                view.button('Kill', () => runAction(() => view.post(`/api/workspace/launches/${encodeURIComponent(id)}/cancel`, { force: true })), 'danger'),
            );
            fragment.append(view.row([
                identity,
                view.element('span', `ra-state ${state}`, state),
                actions,
            ]));
        }
        rows.replaceChildren(fragment);
        summary.textContent = `${launches.length} durable launch(es)`;
    };

    const load = async (): Promise<void> => {
        const payload = await view.get<LaunchList>('/api/launches');
        renderRows(payload.launches || []);
    };

    const preview = view.button('Preview', () => runAction(() => view.post('/api/launches/preview', requestBody())), 'primary');
    const launch = view.button('Launch', () => runAction(() => view.post('/api/launches', requestBody())), 'primary');
    const reconcile = view.button('Reconcile', () => runAction(() => view.post('/api/workspace/launches/reconcile', {})));
    const refresh = view.button('Refresh', load);

    const resumeLabel = view.element('label', 'ra-check');
    resumeLabel.append(resume, document.createTextNode(' Resume compatible runs'));

    const form = view.card(
        'Create launch',
        configPath,
        launcherPath,
        artifactRoot,
        resumeLabel,
        overrides,
        launcherOverrides,
        view.element('div', 'ra-actions', undefined, [preview, launch]),
        output,
    );
    const existing = view.card(
        'Durable launches',
        view.element('div', 'ra-toolbar', undefined, [summary, refresh, reconcile]),
        rows,
    );
    view.content.replaceChildren(view.splitPane(existing, form));
    await load();
}
