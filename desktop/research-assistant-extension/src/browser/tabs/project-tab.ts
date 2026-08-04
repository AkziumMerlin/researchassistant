import type { ResearchAssistantWidget } from '../research-assistant-widget';
import {
    field,
    jsonEditor,
    parseObject,
    runAction,
    sectionTabs,
    select,
    textArea,
} from './tooling-common';

interface ComponentSpec {
    kind: string;
    name: string;
    catalog?: string;
    description?: string;
    provider?: string;
    schema?: { properties?: Record<string, { default?: unknown }> };
}

interface Bootstrap {
    workspace: { name: string; path: string };
    diagnostics: Record<string, unknown>;
    connection: Record<string, unknown>;
    plugins: string[];
    components: ComponentSpec[];
}

interface ComponentRow {
    node: HTMLElement;
    kind: HTMLSelectElement;
    type: HTMLSelectElement;
    params: HTMLTextAreaElement;
}

interface StageRow {
    node: HTMLElement;
    name: HTMLInputElement;
    type: HTMLInputElement | HTMLSelectElement;
    needs: HTMLInputElement;
    params: HTMLTextAreaElement;
    components: HTMLTextAreaElement;
}


function defaultsFromSchema(component: ComponentSpec | undefined): Record<string, unknown> {
    const result: Record<string, unknown> = {};
    for (const [name, schema] of Object.entries(component?.schema?.properties || {})) {
        if (schema.default !== undefined) result[name] = schema.default;
    }
    return result;
}

function integerList(value: string): number[] {
    const result = value.split(/[\s,]+/).filter(Boolean).map(item => Number(item));
    if (!result.length || result.some(item => !Number.isInteger(item))) {
        throw new Error('Seeds must be a non-empty comma-separated list of integers.');
    }
    return result;
}

export async function renderProject(view: ResearchAssistantWidget): Promise<void> {
    const bootstrap = await view.get<Bootstrap>('/api/bootstrap');
    const output = view.output('Create or inspect a reproducible experiment configuration.');

    const diagnostics = view.card(
        'Project diagnostics',
        view.element('div', 'ra-kv-grid', undefined, [
            view.element('strong', undefined, 'Workspace'),
            view.element('span', undefined, `${bootstrap.workspace.name} · ${bootstrap.workspace.path}`),
            view.element('strong', undefined, 'Connection'),
            view.element('span', undefined, view.pretty(bootstrap.connection)),
            view.element('strong', undefined, 'Runtime'),
            view.element('span', undefined, view.pretty(bootstrap.diagnostics)),
            view.element('strong', undefined, 'Plugins'),
            view.element('span', undefined, bootstrap.plugins.join(', ') || 'none'),
        ]),
        view.element('div', 'ra-actions', undefined, [
            view.button('Initialize project plugin', () => runAction(
                view,
                output,
                () => view.post('/api/project/init', {}),
            ), 'primary'),
        ]),
        output,
    );

    const path = view.input('Config path', 'configs/experiment.yaml');
    const name = view.input('Experiment name', 'experiment');
    const description = textArea('Description', '', 3);
    const tags = view.input('Tags', 'baseline');
    const seeds = view.input('Seeds', '0,1,2');
    const accelerator = select(view, ['auto', 'cpu', 'cuda'], 'auto');
    const devices = view.input('Devices', '1');
    const memory = view.input('Memory GiB (optional)');
    const artifactRoot = view.input('Artifact root', 'runs');
    const matrix = jsonEditor({}, 6);
    const creatorOutput = view.output('The creator previews the compiled study before writing the YAML file.');
    const componentRows: ComponentRow[] = [];
    const stageRows: StageRow[] = [];
    const componentHost = view.element('div', 'ra-form-list');
    const stageHost = view.element('div', 'ra-form-list');

    const configurableComponents = bootstrap.components.filter(component =>
        component.catalog !== 'graph-node' && component.kind !== 'stage'
    );
    const componentKinds = [...new Set(configurableComponents.map(component => component.kind))]
        .sort();
    const componentsForKind = (kind: string): ComponentSpec[] => configurableComponents
        .filter(component => component.kind === kind)
        .sort((left, right) => left.name.localeCompare(right.name));

    const addComponent = (initial?: Partial<{ kind: string; type: string; params: object }>): void => {
        const initialKind = initial?.kind && componentKinds.includes(initial.kind)
            ? initial.kind
            : componentKinds[0] || 'model';
        const kind = select(view, componentKinds, initialKind);
        const type = select(view, [], '');
        const params = jsonEditor(initial?.params || {}, 5);
        const schemaHelp = view.element('small', 'ra-help');
        const refreshTypes = (preferred?: string): void => {
            const candidates = componentsForKind(kind.value);
            type.replaceChildren();
            for (const component of candidates) {
                const option = view.element('option', undefined, component.name);
                option.value = component.name;
                type.append(option);
            }
            type.value = preferred && candidates.some(component => component.name === preferred)
                ? preferred
                : candidates[0]?.name || '';
            const selected = candidates.find(component => component.name === type.value);
            schemaHelp.textContent = selected
                ? `${selected.provider || 'built-in'} · ${selected.description || 'No description'}`
                : 'No registered component for this kind.';
            if (!initial?.params) params.value = JSON.stringify(defaultsFromSchema(selected), null, 2);
        };
        kind.onchange = () => refreshTypes();
        type.onchange = () => {
            const selected = componentsForKind(kind.value).find(component =>
                component.name === type.value);
            schemaHelp.textContent = selected
                ? `${selected.provider || 'built-in'} · ${selected.description || 'No description'}`
                : '';
            params.value = JSON.stringify(defaultsFromSchema(selected), null, 2);
        };
        refreshTypes(initial?.type);
        const node = view.element('section', 'ra-form-row');
        const row: ComponentRow = { node, kind, type, params };
        node.append(
            field(view, 'Kind', kind),
            field(view, 'Registered type', type, schemaHelp.textContent),
            schemaHelp,
            field(view, 'Parameters', params),
            view.button('Remove', () => {
                const index = componentRows.indexOf(row);
                if (index >= 0) componentRows.splice(index, 1);
                node.remove();
            }, 'danger'),
        );
        componentRows.push(row);
        componentHost.append(node);
    };

    const addStage = (initial?: Partial<{
        name: string;
        type: string;
        needs: string;
        params: object;
        components: object;
    }>): void => {
        const stageName = view.input('Stage name', initial?.name || `stage_${stageRows.length + 1}`);
        const stageTypes = bootstrap.components
            .filter(component => component.kind === 'stage')
            .map(component => component.name)
            .sort();
        const stageType = stageTypes.length
            ? select(view, stageTypes, initial?.type || stageTypes[0])
            : view.input('Stage type', initial?.type || 'train');
        const needs = view.input('Dependencies', initial?.needs || '');
        const params = jsonEditor(initial?.params || {}, 5);
        const components = jsonEditor(initial?.components || {}, 5);
        const node = view.element('section', 'ra-form-row');
        const row: StageRow = { node, name: stageName, type: stageType, needs, params, components };
        node.append(
            field(view, 'Name', stageName),
            field(view, 'Stage type', stageType),
            field(view, 'Needs', needs, 'Comma-separated stage names.'),
            field(view, 'Parameters', params),
            field(view, 'Stage-local component overrides', components),
            view.button('Remove', () => {
                const index = stageRows.indexOf(row);
                if (index >= 0) stageRows.splice(index, 1);
                node.remove();
            }, 'danger'),
        );
        stageRows.push(row);
        stageHost.append(node);
    };

    addComponent({ kind: 'model' });
    addStage({ name: 'train', type: 'train' });

    const creatorPayload = (): Record<string, unknown> => ({
        path: path.value.trim(),
        experiment_name: name.value.trim(),
        description: description.value.trim() || null,
        tags: view.split(tags.value),
        seeds: integerList(seeds.value),
        components: componentRows.map(row => ({
            kind: row.kind.value.trim(),
            type: row.type.value,
            params: parseObject(row.params, `Parameters for ${row.kind.value || 'component'}`),
        })),
        stages: stageRows.map(row => ({
            name: row.name.value.trim(),
            type: row.type.value.trim(),
            needs: view.split(row.needs.value),
            params: parseObject(row.params, `Parameters for ${row.name.value || 'stage'}`),
            components: parseObject(row.components, `Components for ${row.name.value || 'stage'}`),
        })),
        matrix: parseObject(matrix, 'Matrix axes'),
        accelerator: accelerator.value,
        devices: Number(devices.value || '1'),
        memory_gb: memory.value.trim() ? Number(memory.value) : null,
        artifact_root: artifactRoot.value.trim() || 'runs',
    });

    let createdContent = '';
    const preview = view.button('Preview config', async () => {
        const result = await runAction(
            view,
            creatorOutput,
            () => view.post<{ content: string }>('/api/config/create', creatorPayload()),
        ) as { content?: string };
        createdContent = result.content || '';
    }, 'primary');
    const save = view.button('Create and save', async () => {
        const result = await view.post<{ path: string; content: string }>('/api/config/create', creatorPayload());
        createdContent = result.content;
        await runAction(
            view,
            creatorOutput,
            () => view.put(`/api/files?path=${encodeURIComponent(result.path)}`, {
                content: result.content,
                revision: null,
            }),
        );
    }, 'primary');
    const openCreated = view.button('Open config', () => {
        if (!path.value.trim()) throw new Error('Set a config path first.');
        return view.openWorkspaceFile(path.value.trim());
    });

    const creator = view.element('div', 'ra-project-creator', undefined, [
        view.card(
            'Experiment',
            field(view, 'Path', path),
            field(view, 'Name', name),
            field(view, 'Description', description),
            field(view, 'Tags', tags),
            field(view, 'Seeds', seeds),
        ),
        view.card(
            'Resources and matrix',
            field(view, 'Accelerator', accelerator),
            field(view, 'Devices', devices),
            field(view, 'Memory', memory),
            field(view, 'Artifacts', artifactRoot),
            field(view, 'Matrix axes', matrix, 'JSON mapping from dotted config paths to value arrays.'),
        ),
        view.card(
            'Components',
            view.element('div', 'ra-actions', undefined, [view.button('Add component', () => addComponent())]),
            componentHost,
        ),
        view.card(
            'Stages',
            view.element('div', 'ra-actions', undefined, [view.button('Add stage', () => addStage())]),
            stageHost,
        ),
        view.card(
            'Generated configuration',
            view.element('div', 'ra-actions', undefined, [preview, save, openCreated]),
            creatorOutput,
            view.element('small', 'ra-help', createdContent ? 'The generated YAML is ready.' : ''),
        ),
    ]);

    const inspectPath = view.input('Config path', 'configs/experiment.yaml');
    const inspectContent = textArea('YAML content', '', 18);
    const overrides = textArea('Overrides, one per line', '', 5);
    const includeManifests = document.createElement('input');
    includeManifests.type = 'checkbox';
    const inspectOutput = view.output('Load a configuration, then inspect its rendered document and complete run plan.');
    const load = view.button('Load', async () => {
        const result = await view.get<{ content: string }>(`/api/files?path=${encodeURIComponent(inspectPath.value.trim())}`);
        inspectContent.value = result.content;
        inspectOutput.textContent = `Loaded ${inspectPath.value.trim()}`;
    });
    const inspect = view.button('Inspect and compile', () => runAction(
        view,
        inspectOutput,
        () => view.post('/api/config/inspect', {
            path: inspectPath.value.trim(),
            content: inspectContent.value,
            overrides: view.split(overrides.value),
            include_manifests: includeManifests.checked,
        }),
    ), 'primary');
    const manifestLabel = view.element('label', 'ra-check');
    manifestLabel.append(includeManifests, document.createTextNode(' Include all run manifests'));
    const inspector = view.splitPane(
        view.card(
            'Configuration source',
            field(view, 'Path', inspectPath),
            field(view, 'YAML', inspectContent),
            field(view, 'Overrides', overrides),
            manifestLabel,
            view.element('div', 'ra-actions', undefined, [load, inspect]),
        ),
        view.card('Rendered plan', inspectOutput),
    );

    view.content.replaceChildren(sectionTabs(view, [
        { id: 'diagnostics', label: 'Project', node: diagnostics },
        { id: 'creator', label: 'Config creator', node: creator },
        { id: 'inspect', label: 'Inspect config', node: inspector },
    ]));
}
