import type { ResearchAssistantWidget } from '../research-assistant-widget';
import { field, runAction, sectionTabs, select, textArea } from './tooling-common';

interface PythonSymbol {
    name: string;
    kind: 'class' | 'function' | 'async-function';
    line: number;
    description: string;
}

interface PythonDiscovery {
    path: string;
    symbols: PythonSymbol[];
}

interface RegistrationCatalog {
    catalog_path: string;
    version: number;
    python: Array<{
        kind: string;
        name: string;
        path: string;
        symbol: string;
        provider?: string;
    }>;
    legacy_configs: Array<{
        name: string;
        path: string;
        entrypoint: string;
        output: string;
    }>;
}

interface LegacyConfigResult {
    registration: {
        name: string;
        output: string;
    };
    command: string;
}

interface ProjectImportCandidate {
    id: string;
    category: 'python' | 'legacy-config';
    path: string;
    selected: boolean;
    confidence: 'high' | 'medium' | 'low';
    reason: string;
    symbol?: string;
    kind?: string;
    name: string;
    output?: string;
    already_registered: boolean;
}

interface ProjectImportPlan {
    project_root: string;
    entrypoint?: string;
    candidates: ProjectImportCandidate[];
    warnings: string[];
    summary: {
        python: number;
        legacy_configs: number;
        recommended: number;
        already_registered: number;
        warnings: number;
    };
}

interface ProjectImportResult {
    manifest_path: string;
    items: Array<{
        id: string;
        category: string;
        path: string;
        name: string;
        state: 'imported' | 'skipped' | 'failed';
        message: string;
        output?: string;
    }>;
    summary: {
        imported: number;
        skipped: number;
        failed: number;
    };
}

function replaceOptions(selectNode: HTMLSelectElement, symbols: PythonSymbol[]): void {
    selectNode.replaceChildren();
    for (const symbol of symbols) {
        const option = document.createElement('option');
        option.value = symbol.name;
        option.textContent = `${symbol.name} · ${symbol.kind} · line ${symbol.line}`;
        selectNode.append(option);
    }
}

function toggle(label: string, checked = true): HTMLLabelElement {
    const node = document.createElement('label');
    node.className = 'ra-field';
    const input = document.createElement('input');
    input.type = 'checkbox';
    input.checked = checked;
    const text = document.createElement('span');
    text.className = 'ra-field-label';
    text.textContent = label;
    node.append(text, input);
    return node;
}

export async function renderLegacy(view: ResearchAssistantWidget): Promise<void> {
    const catalogOutput = view.output('Loading project registrations…');
    const refreshCatalog = async (): Promise<void> => {
        const result = await view.get<RegistrationCatalog>('/api/legacy/registrations');
        catalogOutput.textContent = view.pretty(result);
        catalogOutput.classList.remove('error');
    };

    const includePythonField = toggle('Discover Python components');
    const includeConfigsField = toggle('Discover legacy YAML configs');
    const includePython = includePythonField.querySelector('input') as HTMLInputElement;
    const includeConfigs = includeConfigsField.querySelector('input') as HTMLInputElement;
    const importCandidates = view.element('div', 'ra-stack');
    const importOutput = view.output(
        'Scan inspects Python through AST only. Project source is not imported or executed.',
    );
    let importPlan: ProjectImportPlan | undefined;

    const checkedCandidateIds = (): string[] => Array.from(
        importCandidates.querySelectorAll<HTMLInputElement>('input[data-candidate-id]:checked'),
    ).filter(input => !input.disabled).map(input => input.dataset.candidateId || '').filter(Boolean);

    const renderImportPlan = (plan: ProjectImportPlan): void => {
        importCandidates.replaceChildren();
        if (!plan.candidates.length) {
            importCandidates.append(view.element('p', 'ra-help', 'No import candidates found.'));
            return;
        }
        for (const candidate of plan.candidates) {
            const row = view.element('label', 'ra-field');
            const input = document.createElement('input');
            input.type = 'checkbox';
            input.dataset.candidateId = candidate.id;
            input.checked = candidate.selected && !candidate.already_registered;
            input.disabled = candidate.already_registered;
            const title = candidate.category === 'python'
                ? `${candidate.kind}/${candidate.name} ← ${candidate.path}#${candidate.symbol}`
                : `${candidate.name} ← ${candidate.path}`;
            const state = candidate.already_registered
                ? 'already registered'
                : `${candidate.confidence} confidence · ${candidate.reason}`;
            const text = view.element('span', 'ra-field-label', `${title} · ${state}`);
            row.append(input, text);
            importCandidates.append(row);
        }
    };

    const scanProject = async (): Promise<ProjectImportPlan> => {
        const result = await view.post<ProjectImportPlan>('/api/project/import/scan', {
            include_python: includePython.checked,
            include_configs: includeConfigs.checked,
        });
        importPlan = result;
        renderImportPlan(result);
        return result;
    };

    const scanImport = view.button('Scan project', () => runAction(
        view,
        importOutput,
        async () => {
            const result = await scanProject();
            return {
                root: result.project_root,
                runner: result.entrypoint || null,
                summary: result.summary,
                warnings: result.warnings,
            };
        },
    ), 'primary');

    const selectRecommended = view.button('Select recommended', () => {
        if (!importPlan) throw new Error('Scan the project first.');
        for (const input of Array.from(
            importCandidates.querySelectorAll<HTMLInputElement>('input[data-candidate-id]'),
        )) {
            const candidate = importPlan.candidates.find(row => row.id === input.dataset.candidateId);
            input.checked = Boolean(candidate?.selected) && !input.disabled;
        }
    });

    const selectAll = view.button('Select all', () => {
        if (!importPlan) throw new Error('Scan the project first.');
        for (const input of Array.from(
            importCandidates.querySelectorAll<HTMLInputElement>('input[data-candidate-id]'),
        )) {
            input.checked = !input.disabled;
        }
    });

    const importChecked = view.button('Import checked', () => runAction(
        view,
        importOutput,
        async () => {
            if (!importPlan) throw new Error('Scan the project first.');
            const candidateIds = checkedCandidateIds();
            if (!candidateIds.length) throw new Error('Select at least one new candidate.');
            return view.post<ProjectImportResult>('/api/project/import/apply', {
                candidate_ids: candidateIds,
                import_all: false,
                replace: false,
                include_python: includePython.checked,
                include_configs: includeConfigs.checked,
            });
        },
        async () => {
            await refreshCatalog();
            importPlan = await scanProject();
        },
    ), 'primary');

    const projectImport = view.card(
        'Import an existing project',
        view.element(
            'p',
            'ra-help',
            'Detect conventional model and dataset factories, find old experiment YAMLs, preview '
            + 'the plan, and register the checked items as one idempotent operation.',
        ),
        includePythonField,
        includeConfigsField,
        view.element('div', 'ra-actions', undefined, [
            scanImport,
            selectRecommended,
            selectAll,
            importChecked,
        ]),
        importCandidates,
        importOutput,
    );

    const pythonPath = view.input('Python path', 'models/kno.py');
    const symbol = select(view, [], '');
    const kind = select(
        view,
        ['model', 'dataset', 'optimizer', 'loss', 'scheduler', 'transform', 'value', 'stage'],
        'model',
    );
    const componentName = view.input('Registered name', 'local/kno');
    const componentDescription = textArea('Description', '', 3);
    const pythonOutput = view.output(
        'Discovery parses the source AST and does not execute the Python file.',
    );
    let discovered: PythonSymbol[] = [];

    const discover = view.button('Discover symbols', () => runAction(
        view,
        pythonOutput,
        async () => {
            const result = await view.get<PythonDiscovery>(
                `/api/legacy/python/discover?path=${encodeURIComponent(pythonPath.value.trim())}`,
            );
            discovered = result.symbols;
            replaceOptions(symbol, discovered);
            if (!discovered.length) {
                throw new Error('No public top-level classes or functions were found.');
            }
            const selected = discovered[0];
            symbol.value = selected.name;
            componentName.value = `local/${selected.name.toLowerCase().replaceAll('_', '-')}`;
            componentDescription.value = selected.description;
            return result;
        },
    ), 'primary');

    const registerPython = view.button('Register component', () => runAction(
        view,
        pythonOutput,
        () => {
            if (!symbol.value) {
                throw new Error('Discover and select a Python symbol first.');
            }
            return view.post('/api/legacy/python/register', {
                path: pythonPath.value.trim(),
                symbol: symbol.value,
                kind: kind.value,
                name: componentName.value.trim(),
                description: componentDescription.value.trim(),
                catalog: 'component',
                editor: null,
                replace: false,
            });
        },
        refreshCatalog,
    ), 'primary');

    symbol.onchange = () => {
        const selected = discovered.find(candidate => candidate.name === symbol.value);
        if (!selected) return;
        componentName.value = `local/${selected.name.toLowerCase().replaceAll('_', '-')}`;
        componentDescription.value = selected.description;
    };

    const pythonRegistration = view.card(
        'Register a Python class or function',
        view.element(
            'p',
            'ra-help',
            'The source is inspected without import. It is executed only after explicit registration. '
            + 'Constructor or function parameters become the component schema.',
        ),
        field(view, 'Project-relative .py path', pythonPath),
        field(view, 'Symbol', symbol),
        field(view, 'Component kind', kind),
        field(view, 'Registered type', componentName),
        field(view, 'Description', componentDescription),
        view.element('div', 'ra-actions', undefined, [discover, registerPython]),
        pythonOutput,
    );

    const configPath = view.input(
        'Legacy config path',
        'configs/rpb64_baseline_sweep_smoke.yaml',
    );
    const entrypoint = view.input('Python entrypoint', 'examples/train_from_yaml.py');
    const wrapperPath = view.input(
        'Wrapper path',
        'configs/registered/rpb64_baseline_sweep_smoke.yaml',
    );
    const configName = view.input('Experiment name (optional)');
    const workingDirectory = view.input('Working directory', '.');
    const argumentsInput = textArea('One runner argument per line', '', 4);
    const configDescription = textArea('Description', '', 3);
    const configOutput = view.output(
        'The original YAML remains unchanged. ResearchAssistant creates a small current-format wrapper.',
    );
    let generatedWrapper = wrapperPath.value;

    const registerConfig = view.button('Register legacy config', () => runAction(
        view,
        configOutput,
        async () => {
            const result = await view.post<LegacyConfigResult>('/api/legacy/config/register', {
                path: configPath.value.trim(),
                entrypoint: entrypoint.value.trim() || null,
                output: wrapperPath.value.trim(),
                name: configName.value.trim() || null,
                arguments: view.split(argumentsInput.value),
                working_directory: workingDirectory.value.trim() || '.',
                description: configDescription.value.trim(),
                replace: false,
            });
            generatedWrapper = result.registration.output;
            return result;
        },
        refreshCatalog,
    ), 'primary');

    const openWrapper = view.button('Open wrapper', () => {
        const path = generatedWrapper || wrapperPath.value.trim();
        if (!path) throw new Error('Set a wrapper path first.');
        return view.openWorkspaceFile(path);
    });

    const legacyConfig = view.card(
        'Register an existing YAML experiment',
        view.element(
            'p',
            'ra-help',
            'The wrapper delegates execution to the project’s original runner, including its '
            + 'existing model registry and config semantics.',
        ),
        field(view, 'Old YAML', configPath),
        field(view, 'Runner', entrypoint),
        field(view, 'Generated wrapper', wrapperPath),
        field(view, 'Name', configName),
        field(view, 'Working directory', workingDirectory),
        field(view, 'Additional arguments', argumentsInput),
        field(view, 'Description', configDescription),
        view.element('div', 'ra-actions', undefined, [registerConfig, openWrapper]),
        configOutput,
    );

    const catalog = view.card(
        'Project registration catalog',
        view.element(
            'p',
            'ra-help',
            'Registrations are stored in .research-assistant/registrations.yaml and loaded by CLI, '
            + 'local desktop sessions, SSH sidecars, and workers.',
        ),
        view.element('div', 'ra-actions', undefined, [
            view.button('Refresh catalog', refreshCatalog),
        ]),
        catalogOutput,
    );

    view.content.replaceChildren(sectionTabs(view, [
        { id: 'import', label: 'Import project', node: projectImport },
        { id: 'python', label: 'Python files', node: pythonRegistration },
        { id: 'config', label: 'Legacy configs', node: legacyConfig },
        { id: 'catalog', label: 'Catalog', node: catalog },
    ]));
    await refreshCatalog();
}
