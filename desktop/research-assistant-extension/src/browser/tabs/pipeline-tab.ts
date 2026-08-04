import type { ResearchAssistantWidget } from '../research-assistant-widget';
import {
    field,
    jsonEditor,
    parseObject,
    runAction,
    sectionTabs,
    select,
} from './tooling-common';

interface AssetRow {
    asset_id: string;
    name?: string;
    path?: string;
    kind?: string;
    status?: string;
    run_id?: string;
    pinned?: boolean;
}

const DEFAULT_PUBLICATION = {
    name: 'publication',
    title: null,
    authors: [],
    artifact_root: 'runs',
    study_ids: [],
    trial_ids: [],
    run_ids: [],
    reports: [],
    asset_statuses: ['selected', 'released'],
    include_all_artifacts: false,
    include_checkpoints: true,
    include_environment: true,
    template: 'generic',
    copy_mode: 'hardlink',
};

export async function renderPipeline(view: ResearchAssistantWidget): Promise<void> {
    const cacheOutput = view.output('Inspect or prune the content-addressed stage cache.');
    const keepEntries = view.input('Entries to keep', '10000');
    const cache = view.splitPane(
        view.card(
            'Stage cache',
            field(view, 'Keep newest entries', keepEntries),
            view.element('div', 'ra-actions', undefined, [
                view.button('Stats', () => runAction(view, cacheOutput, () => view.get('/api/pipeline/cache')), 'primary'),
                view.button('Prune', () => runAction(view, cacheOutput, () => view.post('/api/pipeline/cache/prune', {
                    keep_entries: Number(keepEntries.value || '10000'),
                })), 'danger'),
            ]),
        ),
        view.card('Cache result', cacheOutput),
    );

    const assetRoot = view.input('Artifact root', 'runs');
    const assetSearch = view.input('Search assets');
    const assetKind = select(view, ['', 'artifact', 'checkpoint'], '');
    const assetStatus = select(view, ['', 'candidate', 'selected', 'released', 'archived'], '');
    const assets = view.element('div', 'ra-virtual-list');
    const assetOutput = view.output('Refresh the registry, then promote, pin, archive or delete assets.');

    const loadAssets = async (): Promise<void> => {
        const query = new URLSearchParams({ limit: '5000' });
        if (assetSearch.value.trim()) query.set('search', assetSearch.value.trim());
        if (assetKind.value) query.set('kind', assetKind.value);
        if (assetStatus.value) query.set('status', assetStatus.value);
        const payload = await view.get<{ assets: AssetRow[]; stats?: object }>(`/api/pipeline/assets?${query}`);
        const fragment = document.createDocumentFragment();
        for (const asset of payload.assets || []) {
            const action = (name: string, danger = false): HTMLButtonElement => view.button(
                name,
                () => runAction(view, assetOutput, () => view.post('/api/pipeline/assets/action', {
                    asset_id: asset.asset_id,
                    action: name.toLowerCase(),
                    delete_source: false,
                }), loadAssets),
                danger ? 'danger' : '',
            );
            const actions = view.element('div', 'ra-actions', undefined, [
                action('Select'),
                action('Release'),
                action('Archive'),
                action(asset.pinned ? 'Unpin' : 'Pin'),
                action('Delete', true),
            ]);
            fragment.append(view.row([
                view.element('div', 'ra-identity', undefined, [
                    view.element('strong', undefined, asset.name || asset.asset_id),
                    view.element('small', undefined, `${asset.kind || 'artifact'} · ${asset.path || ''} · ${asset.run_id || ''}`),
                ]),
                view.element('span', `ra-state ${asset.status || 'candidate'}`, asset.status || 'candidate'),
                actions,
            ]));
        }
        assets.replaceChildren(fragment);
        assetOutput.textContent = view.pretty(payload.stats || { assets: payload.assets?.length || 0 });
    };

    const registry = view.element('div', 'ra-tool-stack', undefined, [
        view.element('div', 'ra-toolbar', undefined, [
            assetRoot,
            assetKind,
            assetStatus,
            assetSearch,
            view.button('Refresh registry', () => runAction(view, assetOutput, () => view.post('/api/pipeline/assets/refresh', {
                artifact_root: assetRoot.value.trim() || 'runs',
            }), loadAssets), 'primary'),
            view.button('Reload', loadAssets),
        ]),
        view.splitPane(view.card('Asset registry', assets), view.card('Registry status', assetOutput)),
    ]);

    const diagnosticRoot = view.input('Artifact root', 'runs');
    const diagnosticsOutput = view.output('Inspect failed runs, resource failures and configured automatic interventions.');
    const diagnostics = view.splitPane(
        view.card(
            'Pipeline diagnostics',
            field(view, 'Artifact root', diagnosticRoot),
            view.button('Run diagnostics', () => runAction(
                view,
                diagnosticsOutput,
                () => view.get(`/api/pipeline/diagnostics?artifact_root=${encodeURIComponent(diagnosticRoot.value.trim() || 'runs')}&limit=10000`),
            ), 'primary'),
        ),
        view.card('Diagnostic catalog', diagnosticsOutput),
    );

    const publicationSpec = jsonEditor(DEFAULT_PUBLICATION, 22);
    const publicationOutputPath = view.input('Output path (optional)', 'publications/publication');
    const publicationOutput = view.output('Preview the exact run, report, checkpoint and environment selection before building.');
    const publication = view.splitPane(
        view.card(
            'Publication bundle',
            field(view, 'Specification', publicationSpec),
            field(view, 'Output', publicationOutputPath),
            view.element('div', 'ra-actions', undefined, [
                view.button('Preview', () => runAction(view, publicationOutput, () => view.post('/api/pipeline/publication/preview', {
                    spec: parseObject(publicationSpec, 'Publication specification'),
                    output_path: publicationOutputPath.value.trim() || null,
                })), 'primary'),
                view.button('Build bundle', () => runAction(view, publicationOutput, () => view.post('/api/pipeline/publication/build', {
                    spec: parseObject(publicationSpec, 'Publication specification'),
                    output_path: publicationOutputPath.value.trim() || null,
                })), 'primary'),
            ]),
        ),
        view.card('Publication result', publicationOutput),
    );

    const recoveryJob = view.input('Job ID');
    const recoveryOutput = view.output('Adopt or recover persistent jobs after a process or machine restart.');
    const recovery = view.splitPane(
        view.card(
            'Job recovery',
            field(view, 'Job ID', recoveryJob),
            view.element('div', 'ra-actions', undefined, [
                view.button('List jobs', () => runAction(view, recoveryOutput, () => view.get('/api/jobs'))),
                view.button('Adopt', () => {
                    if (!recoveryJob.value.trim()) throw new Error('Set a job ID.');
                    return runAction(view, recoveryOutput, () => view.post(`/api/jobs/${encodeURIComponent(recoveryJob.value.trim())}/adopt`, {}));
                }, 'primary'),
                view.button('Recover', () => {
                    if (!recoveryJob.value.trim()) throw new Error('Set a job ID.');
                    return runAction(view, recoveryOutput, () => view.post(`/api/jobs/${encodeURIComponent(recoveryJob.value.trim())}/recover`, {}));
                }),
            ]),
        ),
        view.card('Recovery result', recoveryOutput),
    );

    view.content.replaceChildren(sectionTabs(view, [
        { id: 'recovery', label: 'Recovery', node: recovery },
        { id: 'cache', label: 'Stage cache', node: cache },
        { id: 'assets', label: 'Assets', node: registry },
        { id: 'diagnostics', label: 'Diagnostics', node: diagnostics },
        { id: 'publication', label: 'Publication', node: publication },
    ]));
}
