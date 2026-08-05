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

function replaceOptions(selectNode: HTMLSelectElement, symbols: PythonSymbol[]): void {
    selectNode.replaceChildren();
    for (const symbol of symbols) {
        const option = document.createElement('option');
        option.value = symbol.name;
        option.textContent = `${symbol.name} · ${symbol.kind} · line ${symbol.line}`;
        selectNode.append(option);
    }
}

export async function renderLegacy(view: ResearchAssistantWidget): Promise<void> {
    const catalogOutput = view.output('Loading project registrations…');
    const refreshCatalog = async (): Promise<void> => {
        const result = await view.get<RegistrationCatalog>('/api/legacy/registrations');
        catalogOutput.textContent = view.pretty(result);
        catalogOutput.classList.remove('error');
    };

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
        { id: 'python', label: 'Python files', node: pythonRegistration },
        { id: 'config', label: 'Legacy configs', node: legacyConfig },
        { id: 'catalog', label: 'Catalog', node: catalog },
    ]));
    await refreshCatalog();
}
