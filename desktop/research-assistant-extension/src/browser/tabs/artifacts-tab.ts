import type { ResearchAssistantWidget } from '../research-assistant-widget';
import {
    field,
    jsonEditor,
    parseArray,
    parseObject,
    runAction,
    sectionTabs,
    textArea,
} from './tooling-common';

interface ArtifactRow {
    artifact_id: string;
    name: string;
    kind: string;
    path: string;
    run_id?: string;
    stage?: string;
    sample_id?: string;
    role?: string;
}

export async function renderArtifacts(view: ResearchAssistantWidget): Promise<void> {
    let rows: ArtifactRow[] = [];
    const query = view.input('Filter artifact, path, kind or run');
    const kind = view.input('Kind filter');
    const runId = view.input('Run filter');
    const list = view.element('div', 'ra-virtual-list');
    const output = view.output('Select one artifact for details/lineage or two for comparison.');
    const selected = view.element('span', 'ra-summary', `${view.selectedArtifacts.size} selected`);

    const render = (): void => {
        const needle = query.value.trim().toLowerCase();
        const fragment = document.createDocumentFragment();
        for (const item of rows) {
            if (needle && !`${item.name} ${item.path} ${item.kind} ${item.run_id || ''}`.toLowerCase().includes(needle)) {
                continue;
            }
            const checkbox = document.createElement('input');
            checkbox.type = 'checkbox';
            checkbox.checked = view.selectedArtifacts.has(item.artifact_id);
            checkbox.addEventListener('change', () => {
                if (checkbox.checked && view.selectedArtifacts.size >= 2) {
                    checkbox.checked = false;
                    return;
                }
                if (checkbox.checked) {
                    view.selectedArtifacts.add(item.artifact_id);
                } else {
                    view.selectedArtifacts.delete(item.artifact_id);
                }
                selected.textContent = `${view.selectedArtifacts.size} selected`;
            });
            const identity = view.element('div', 'ra-identity');
            identity.append(
                view.element('strong', undefined, item.name),
                view.element('small', undefined, `${item.kind} · ${item.path}${item.run_id ? ` · ${item.run_id}` : ''}`),
            );
            const actions = view.element('div', 'ra-actions', undefined, [
                view.button('Inspect', () => runAction(view, output, () => view.get(
                    `/api/workbench/artifacts/${encodeURIComponent(item.artifact_id)}?refresh=true`,
                ))),
                view.button('Lineage', () => runAction(view, output, () => view.get(
                    `/api/workspace/artifacts/${encodeURIComponent(item.artifact_id)}/lineage?artifact_root=runs`,
                ))),
                view.button('Open source', () => view.openWorkspaceFile(item.path)),
            ]);
            fragment.append(view.row([checkbox, identity, actions]));
        }
        list.replaceChildren(fragment);
    };

    const load = async (): Promise<void> => {
        const params = new URLSearchParams({ limit: '10000' });
        if (kind.value.trim()) params.set('kind', kind.value.trim());
        if (runId.value.trim()) params.set('run_id', runId.value.trim());
        const payload = await view.get<{ artifacts: ArtifactRow[] }>(`/api/workbench/artifacts?${params}`);
        rows = payload.artifacts || [];
        render();
        selected.textContent = `${rows.length} artifacts · ${view.selectedArtifacts.size} selected`;
    };
    query.addEventListener('input', render);

    const compare = view.button('Compare selected', () => {
        const ids = [...view.selectedArtifacts];
        if (ids.length !== 2) throw new Error('Select exactly two artifacts.');
        return runAction(view, output, () => view.post('/api/workbench/artifacts/compare', {
            left_id: ids[0],
            right_id: ids[1],
            key: null,
        }));
    }, 'primary');
    const catalog = view.element('div', 'ra-tool-stack', undefined, [
        view.element('div', 'ra-toolbar', undefined, [query, kind, runId, view.button('Refresh', load), selected, compare]),
        view.splitPane(view.card('Artifact catalog', list), view.card('Artifact detail', output)),
    ]);

    const discoverRoots = view.input('Discovery roots', 'runs,reports,artifacts');
    const registerPath = view.input('Workspace-relative path');
    const registerKind = view.input('Kind (optional)');
    const registerName = view.input('Name (optional)');
    const registerRun = view.input('Run ID (optional)');
    const registerStage = view.input('Stage (optional)');
    const registerSample = view.input('Sample ID (optional)');
    const registerRole = view.input('Role (optional)');
    const registerDimensions = view.input('Dimensions');
    const registerTags = view.input('Tags');
    const registerMetadata = jsonEditor({}, 6);
    const registrationOutput = view.output('Discover existing scientific files or register one explicitly.');
    const registration = view.splitPane(
        view.card(
            'Discover artifacts',
            field(view, 'Roots', discoverRoots),
            view.button('Discover', () => runAction(view, registrationOutput, () => view.post('/api/workbench/artifacts/discover', {
                roots: view.split(discoverRoots.value),
                limit: 100000,
            }), load), 'primary'),
        ),
        view.card(
            'Register artifact',
            field(view, 'Path', registerPath),
            field(view, 'Kind', registerKind),
            field(view, 'Name', registerName),
            field(view, 'Run', registerRun),
            field(view, 'Stage', registerStage),
            field(view, 'Sample', registerSample),
            field(view, 'Role', registerRole),
            field(view, 'Dimensions', registerDimensions),
            field(view, 'Tags', registerTags),
            field(view, 'Metadata', registerMetadata),
            view.button('Register', () => runAction(view, registrationOutput, () => view.post('/api/workbench/artifacts/register', {
                path: registerPath.value.trim(),
                kind: registerKind.value.trim() || null,
                name: registerName.value.trim() || null,
                run_id: registerRun.value.trim() || null,
                stage: registerStage.value.trim() || null,
                sample_id: registerSample.value.trim() || null,
                role: registerRole.value.trim() || null,
                dimensions: view.split(registerDimensions.value),
                metadata: parseObject(registerMetadata, 'Artifact metadata'),
                tags: view.split(registerTags.value),
            }), load), 'primary'),
            registrationOutput,
        ),
    );

    const sliceId = view.input('Artifact ID');
    const sliceSelection = textArea('Selection entries as JSON strings/indices', '["0:8", "..."]', 5);
    const sliceKey = view.input('Array/tensor key (optional)');
    const sliceLimit = view.input('Maximum elements', '100000');
    const sliceOutput = view.output('Slice registered arrays, tensors and structured artifacts without loading unbounded data.');
    const slice = view.splitPane(
        view.card(
            'Artifact slice',
            field(view, 'Artifact', sliceId),
            field(view, 'Selection JSON', sliceSelection),
            field(view, 'Key', sliceKey),
            field(view, 'Limit', sliceLimit),
            view.button('Slice', () => {
                const artifactId = sliceId.value.trim() || [...view.selectedArtifacts][0];
                if (!artifactId) throw new Error('Set or select an artifact ID.');
                return runAction(view, sliceOutput, () => view.post('/api/workbench/artifacts/slice', {
                    artifact_id: artifactId,
                    selection: parseArray(sliceSelection, 'Slice selection'),
                    key: sliceKey.value.trim() || null,
                    max_elements: Number(sliceLimit.value || '100000'),
                }));
            }, 'primary'),
        ),
        view.card('Slice result', sliceOutput),
    );

    const lifecyclePath = view.input('Workspace-relative path');
    const lifecycleReason = view.input('Reason (optional)');
    const trashId = view.input('Trash ID');
    const gcDays = view.input('Older than days', '30');
    const gcDryRun = document.createElement('input');
    gcDryRun.type = 'checkbox';
    gcDryRun.checked = true;
    const lifecycleOutput = view.output('Pin, archive and trash research outputs with protection checks and reversible operations.');
    const lifecycleAction = (endpoint: string, body: object): Promise<unknown> => runAction(
        view,
        lifecycleOutput,
        () => view.post(`/api/workbench/lifecycle/${endpoint}`, body),
    );
    const gcLabel = view.element('label', 'ra-check');
    gcLabel.append(gcDryRun, document.createTextNode(' Garbage collection dry run'));
    const lifecycle = view.splitPane(
        view.card(
            'Lifecycle operations',
            field(view, 'Path', lifecyclePath),
            field(view, 'Reason', lifecycleReason),
            view.element('div', 'ra-actions', undefined, [
                view.button('Protection', () => runAction(view, lifecycleOutput, () => view.get(
                    `/api/workbench/lifecycle/protection?path=${encodeURIComponent(lifecyclePath.value.trim())}`,
                ))),
                view.button('Pin', () => lifecycleAction('pin', { path: lifecyclePath.value.trim(), reason: lifecycleReason.value.trim() || null, force: false })),
                view.button('Unpin', () => lifecycleAction('unpin', { path: lifecyclePath.value.trim(), reason: null, force: false })),
                view.button('Archive', () => lifecycleAction('archive', { path: lifecyclePath.value.trim(), reason: lifecycleReason.value.trim() || null, force: false })),
                view.button('Unarchive', () => lifecycleAction('unarchive', { path: lifecyclePath.value.trim(), reason: null, force: false })),
                view.button('Trash', () => lifecycleAction('trash', { path: lifecyclePath.value.trim(), reason: lifecycleReason.value.trim() || null, force: false }), 'danger'),
            ]),
            field(view, 'Trash ID', trashId),
            view.button('Restore', () => lifecycleAction('restore', { trash_id: trashId.value.trim(), overwrite: false })),
            field(view, 'GC threshold', gcDays),
            gcLabel,
            view.button('Garbage collect', () => lifecycleAction('gc', {
                older_than_days: Number(gcDays.value || '30'),
                dry_run: gcDryRun.checked,
            }), 'danger'),
        ),
        view.card(
            'Lifecycle state',
            view.button('Refresh state', () => runAction(view, lifecycleOutput, () => view.get('/api/workbench/lifecycle')), 'primary'),
            lifecycleOutput,
        ),
    );

    view.content.replaceChildren(sectionTabs(view, [
        { id: 'catalog', label: 'Catalog', node: catalog },
        { id: 'register', label: 'Discover & register', node: registration },
        { id: 'slice', label: 'Slice', node: slice },
        { id: 'lifecycle', label: 'Lifecycle', node: lifecycle },
    ]));
    await load();
}
