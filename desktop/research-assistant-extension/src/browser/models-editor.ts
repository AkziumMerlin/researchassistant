import type { ResearchAssistantWidget } from './research-assistant-widget';

type JsonObject = Record<string, unknown>;

interface ComponentSpec {
    name: string;
    description?: string;
    catalog?: string;
    provider?: string;
    metadata?: JsonObject;
    schema?: { properties?: Record<string, JsonObject> };
}

interface GraphPosition {
    x: number;
    y: number;
}

interface GraphNode extends JsonObject {
    id: string;
    kind: 'module' | 'python' | 'composite' | 'repeat' | 'switch';
    type?: string;
    target?: string;
    template?: string;
    inputs: Record<string, string>;
    params: JsonObject;
    output_ports: string[];
    position: GraphPosition;
}

interface GraphTemplate extends JsonObject {
    input_names: string[];
    nodes: GraphNode[];
    outputs: Record<string, string>;
}

interface ArchitectureGraph extends GraphTemplate {
    variables: JsonObject;
    variable_specs: JsonObject;
    subgraphs: Record<string, GraphTemplate>;
}

interface ArchitectureFile {
    path: string;
    name: string;
}

interface FilePayload {
    path: string;
    content: string;
    revision: string;
}

const ROOT_TEMPLATE = '__root__';

function fuzzyScore(query: string, value: string): number {
    if (!query) return 0;
    let cursor = -1;
    let gaps = 0;
    for (const character of query) {
        const next = value.indexOf(character, cursor + 1);
        if (next < 0) return -1;
        if (cursor >= 0) gaps += next - cursor - 1;
        cursor = next;
    }
    return Math.max(0, 100 - gaps);
}

function componentScore(component: ComponentSpec, query: string): number {
    const terms = query.toLowerCase().split(/\s+/).filter(Boolean);
    if (!terms.length) return 0;
    const name = component.name.toLowerCase();
    const shortName = name.split('/').at(-1) || name;
    const category = String(component.metadata?.category || '').toLowerCase();
    const provider = String(component.provider || '').toLowerCase();
    const description = String(component.description || '').toLowerCase();
    const haystack = `${name} ${shortName} ${category} ${provider} ${description}`;
    let score = 0;
    for (const term of terms) {
        if (shortName === term || name === term) score += 1200;
        else if (shortName.startsWith(term)) score += 900 - shortName.length;
        else if (name.startsWith(term)) score += 800 - name.length * 0.1;
        else if (shortName.includes(term)) score += 650 - shortName.indexOf(term);
        else if (name.includes(term)) score += 560 - name.indexOf(term) * 0.1;
        else if (category.includes(term)) score += 430;
        else if (provider.includes(term)) score += 400;
        else if (description.includes(term)) score += 320;
        else {
            const fuzzy = fuzzyScore(term, haystack);
            if (fuzzy < 0) return -1;
            score += 120 + fuzzy;
        }
    }
    return score;
}
const IDENTIFIER = /^[A-Za-z][A-Za-z0-9_-]*$/;

function object(value: unknown): JsonObject {
    return value && typeof value === 'object' && !Array.isArray(value) ? value as JsonObject : {};
}

function outputs(value: unknown, fallback: string): Record<string, string> {
    if (Array.isArray(value)) {
        return Object.fromEntries(value.map((source, index) => [index === 0 ? 'output' : `output_${index + 1}`, String(source)]));
    }
    const result = object(value);
    return Object.keys(result).length ? Object.fromEntries(Object.entries(result).map(([key, source]) => [key, String(source)])) : { output: fallback };
}

function inputs(value: unknown): Record<string, string> {
    if (Array.isArray(value)) {
        return Object.fromEntries(value.map((source, index) => [index === 0 ? 'input' : `input_${index + 1}`, String(source)]));
    }
    const result = object(value);
    return Object.fromEntries(Object.entries(result).map(([key, source]) => [key, String(source)]));
}

function normalizeNode(value: unknown, index: number): GraphNode {
    const source = object(value);
    const id = String(source.id || `node_${index + 1}`);
    const kind = ['module', 'python', 'composite', 'repeat', 'switch'].includes(String(source.kind))
        ? String(source.kind) as GraphNode['kind']
        : 'module';
    return {
        ...source,
        id,
        kind,
        inputs: inputs(source.inputs),
        params: object(source.params),
        output_ports: Array.isArray(source.output_ports) && source.output_ports.length
            ? source.output_ports.map(String)
            : ['output'],
        position: {
            x: Number(object(source.position).x ?? 260 + (index % 5) * 210),
            y: Number(object(source.position).y ?? 55 + Math.floor(index / 5) * 130),
        },
    };
}

function normalizeTemplate(value: unknown): GraphTemplate {
    const source = object(value);
    const inputNames = Array.isArray(source.input_names) && source.input_names.length
        ? source.input_names.map(String)
        : ['input'];
    const nodes = Array.isArray(source.nodes) ? source.nodes.map(normalizeNode) : [];
    return {
        ...source,
        input_names: inputNames,
        nodes,
        outputs: outputs(source.outputs, nodes.at(-1)?.id || inputNames[0]),
    };
}

function normalizeGraph(value: unknown): ArchitectureGraph {
    const root = normalizeTemplate(value);
    const source = object(value);
    const subgraphs = Object.fromEntries(
        Object.entries(object(source.subgraphs)).map(([name, template]) => [name, normalizeTemplate(template)]),
    );
    return {
        ...root,
        variables: object(source.variables),
        variable_specs: object(source.variable_specs),
        subgraphs,
    };
}

function initialGraph(): ArchitectureGraph {
    return normalizeGraph({
        variables: {},
        variable_specs: {},
        input_names: ['input'],
        nodes: [{
            id: 'identity',
            kind: 'python',
            target: 'torch.nn:Identity',
            inputs: { input: 'input' },
            params: {},
            output_ports: ['output'],
            call_style: 'positional',
            position: { x: 260, y: 70 },
        }],
        outputs: { output: 'identity' },
        subgraphs: {},
    });
}

export class ModelsEditor {
    protected graph = initialGraph();
    protected revision: string | undefined;
    protected selectedNode: string | undefined;
    protected selectedTemplate = ROOT_TEMPLATE;
    protected path = 'architectures/model.json';
    protected readonly host: HTMLElement;
    protected readonly files: HTMLElement;
    protected readonly palette: HTMLElement;
    protected readonly canvas: HTMLElement;
    protected readonly canvasNodes: HTMLElement;
    protected readonly edges: SVGSVGElement;
    protected readonly inspector: HTMLElement;
    protected readonly status: HTMLElement;
    protected readonly pathInput: HTMLInputElement;
    protected readonly templateSelect: HTMLSelectElement;
    protected readonly componentSearch: HTMLInputElement;
    protected readonly componentCategory: HTMLSelectElement;
    protected readonly componentProvider: HTMLSelectElement;
    protected readonly componentStatus: HTMLElement;

    constructor(
        protected readonly view: ResearchAssistantWidget,
        protected readonly components: ComponentSpec[],
        architectures: ArchitectureFile[],
    ) {
        this.host = view.element('div', 'ra-model-editor');
        this.files = view.element('div', 'ra-model-files');
        this.palette = view.element('div', 'ra-model-palette-list');
        this.canvas = view.element('div', 'ra-model-canvas');
        this.canvasNodes = view.element('div', 'ra-model-canvas-nodes');
        this.edges = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        this.edges.classList.add('ra-model-edges');
        this.inspector = view.element('div', 'ra-model-inspector');
        this.status = view.element('span', 'ra-model-status', 'New architecture');
        this.pathInput = view.input('architectures/model.json', this.path);
        this.templateSelect = view.element('select', 'theia-select');
        this.componentSearch = view.input('Search name, provider, category or description');
        this.componentCategory = view.element('select', 'theia-select');
        this.componentProvider = view.element('select', 'theia-select');
        this.componentStatus = view.element('small', 'ra-help');
        this.build(architectures);
        this.renderAll();
    }

    get node(): HTMLElement {
        return this.host;
    }

    protected build(architectures: ArchitectureFile[]): void {
        const fileToolbar = this.view.element('div', 'ra-model-toolbar');
        fileToolbar.append(
            this.pathInput,
            this.view.button('New', () => this.newDocument()),
            this.view.button('Save', () => this.save()),
            this.view.button('Validate', () => this.validate()),
        );
        this.pathInput.onchange = () => {
            this.path = this.pathInput.value.trim();
        };

        for (const architecture of architectures) {
            const button = this.view.element('button', 'ra-model-file');
            button.type = 'button';
            button.textContent = architecture.path;
            button.onclick = () => void this.load(architecture.path);
            this.files.append(button);
        }
        if (!architectures.length) {
            this.files.append(this.view.element('div', 'ra-empty', 'No architecture documents yet.'));
        }

        const paletteToolbar = this.view.element('div', 'ra-model-palette-toolbar');
        const categories = [...new Set(this.components.map(component =>
            String(component.metadata?.category || 'Modules')))].sort();
        const providers = [...new Set(this.components.map(component =>
            String(component.provider || 'unknown')))].sort();
        this.populateFilter(this.componentCategory, 'All categories', categories);
        this.populateFilter(this.componentProvider, 'All providers', providers);
        this.componentSearch.oninput = () => this.renderPalette();
        this.componentCategory.onchange = () => this.renderPalette();
        this.componentProvider.onchange = () => this.renderPalette();
        this.componentSearch.onkeydown = event => this.componentSearchKeydown(event);
        this.host.addEventListener('keydown', event => {
            if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
                event.preventDefault();
                this.componentSearch.focus();
                this.componentSearch.select();
            }
        });
        paletteToolbar.append(
            this.componentSearch,
            this.componentCategory,
            this.componentProvider,
            this.componentStatus,
        );

        const templateToolbar = this.view.element('div', 'ra-model-template-toolbar');
        this.templateSelect.onchange = () => {
            this.selectedTemplate = this.templateSelect.value;
            this.selectedNode = undefined;
            this.renderGraph();
            this.renderInspector();
        };
        templateToolbar.append(
            this.templateSelect,
            this.view.button('Add subgraph', () => this.addSubgraph()),
            this.view.button('Delete subgraph', () => this.deleteSubgraph()),
        );

        const canvasToolbar = this.view.element('div', 'ra-model-canvas-toolbar');
        canvasToolbar.append(
            templateToolbar,
            this.view.button('Python', () => this.addControl('python')),
            this.view.button('Composite', () => this.addControl('composite')),
            this.view.button('Repeat', () => this.addControl('repeat')),
            this.view.button('Switch', () => this.addControl('switch')),
        );
        this.canvas.append(this.edges, this.canvasNodes);

        const sidebar = this.view.element('aside', 'ra-model-sidebar');
        sidebar.append(
            this.view.element('h3', undefined, 'Architecture files'),
            this.files,
            this.view.element('h3', undefined, 'Components'),
            paletteToolbar,
            this.palette,
        );
        const center = this.view.element('section', 'ra-model-center');
        center.append(canvasToolbar, this.canvas);
        const inspectorPane = this.view.element('aside', 'ra-model-inspector-pane');
        inspectorPane.append(this.view.element('h3', undefined, 'Inspector'), this.inspector);
        const footer = this.view.element('footer', 'ra-model-footer');
        footer.append(this.status);
        this.host.append(fileToolbar, sidebar, center, inspectorPane, footer);
    }

    protected currentTemplate(): GraphTemplate {
        return this.selectedTemplate === ROOT_TEMPLATE
            ? this.graph
            : this.graph.subgraphs[this.selectedTemplate];
    }

    protected async load(path: string): Promise<void> {
        const payload = await this.view.get<FilePayload>(`/api/files?path=${encodeURIComponent(path)}`);
        this.graph = normalizeGraph(JSON.parse(payload.content));
        this.path = payload.path;
        this.pathInput.value = payload.path;
        this.revision = payload.revision;
        this.selectedTemplate = ROOT_TEMPLATE;
        this.selectedNode = undefined;
        this.status.textContent = `Loaded ${payload.path}`;
        this.renderAll();
    }

    protected newDocument(): void {
        this.graph = initialGraph();
        this.revision = undefined;
        this.selectedTemplate = ROOT_TEMPLATE;
        this.selectedNode = 'identity';
        this.status.textContent = 'New unsaved architecture';
        this.renderAll();
    }

    protected async save(): Promise<void> {
        const path = this.pathInput.value.trim();
        if (!path || !path.endsWith('.json')) {
            throw new Error('Architecture path must be a workspace-relative .json file.');
        }
        const payload = await this.view.put<FilePayload>(
            `/api/files?path=${encodeURIComponent(path)}`,
            { content: JSON.stringify(this.graph, null, 2) + '\n', revision: this.revision },
        );
        this.path = payload.path;
        this.revision = payload.revision;
        this.status.textContent = `Saved ${payload.path}`;
    }

    protected async validate(): Promise<void> {
        const result = await this.view.post<JsonObject>('/api/torch/parameterized-graph/validate', { params: this.graph });
        this.status.textContent = `Valid · ${String(result.nodes)} nodes · ${String(result.subgraphs)} subgraphs`;
        this.status.classList.add('valid');
    }

    protected renderAll(): void {
        this.renderTemplates();
        this.renderPalette();
        this.renderGraph();
        this.renderInspector();
    }

    protected renderTemplates(): void {
        this.templateSelect.replaceChildren();
        const root = this.view.element('option', undefined, 'Root graph');
        root.value = ROOT_TEMPLATE;
        this.templateSelect.append(root);
        for (const name of Object.keys(this.graph.subgraphs).sort()) {
            const option = this.view.element('option', undefined, name);
            option.value = name;
            this.templateSelect.append(option);
        }
        this.templateSelect.value = this.selectedTemplate;
    }

    protected populateFilter(
        target: HTMLSelectElement,
        emptyLabel: string,
        values: string[],
    ): void {
        const empty = this.view.element('option', undefined, emptyLabel);
        empty.value = '';
        target.append(empty);
        for (const value of values) {
            const option = this.view.element('option', undefined, value);
            option.value = value;
            target.append(option);
        }
    }

    protected componentSearchKeydown(event: KeyboardEvent): void {
        const buttons = Array.from(
            this.palette.querySelectorAll<HTMLButtonElement>('.ra-model-palette-item'),
        );
        if (!buttons.length) return;
        const active = document.activeElement instanceof HTMLButtonElement
            ? buttons.indexOf(document.activeElement)
            : -1;
        if (event.key === 'ArrowDown') {
            event.preventDefault();
            buttons[Math.min(buttons.length - 1, active + 1)]?.focus();
        } else if (event.key === 'ArrowUp') {
            event.preventDefault();
            buttons[Math.max(0, active < 0 ? 0 : active - 1)]?.focus();
        } else if (event.key === 'Enter') {
            event.preventDefault();
            buttons[Math.max(0, active)]?.click();
        } else if (event.key === 'Escape') {
            this.componentSearch.value = '';
            this.componentCategory.value = '';
            this.componentProvider.value = '';
            this.renderPalette();
        }
    }

    protected renderPalette(): void {
        const query = this.componentSearch.value.trim().toLowerCase();
        const categoryFilter = this.componentCategory.value;
        const providerFilter = this.componentProvider.value;
        this.palette.replaceChildren();
        const matches = this.components.map(component => ({
            component,
            category: String(component.metadata?.category || 'Modules'),
            provider: String(component.provider || 'unknown'),
            score: componentScore(component, query),
        })).filter(item =>
            item.score >= 0
            && (!categoryFilter || item.category === categoryFilter)
            && (!providerFilter || item.provider === providerFilter)
        ).sort((left, right) =>
            right.score - left.score || left.component.name.localeCompare(right.component.name)
        );
        const grouped = new Map<string, typeof matches>();
        for (const item of matches.slice(0, 250)) {
            grouped.set(item.category, [...(grouped.get(item.category) || []), item]);
        }
        for (const [category, components] of [...grouped].sort(([left], [right]) =>
            left.localeCompare(right))) {
            this.palette.append(this.view.element('div', 'ra-model-palette-group', category));
            for (const item of components) {
                const component = item.component;
                const button = this.view.element('button', 'ra-model-palette-item');
                button.type = 'button';
                button.title = `${component.name} · ${item.provider}`;
                button.append(
                    this.view.element(
                        'strong',
                        undefined,
                        component.name.split('/').at(-1) || component.name,
                    ),
                    this.view.element(
                        'small',
                        undefined,
                        `${item.provider} · ${component.description || component.name}`,
                    ),
                );
                button.onclick = () => this.addComponent(component);
                this.palette.append(button);
            }
        }
        this.componentStatus.textContent = matches.length > 250
            ? `250 of ${matches.length} components · Ctrl+K`
            : `${matches.length} component(s) · Ctrl+K`;
        if (!matches.length) {
            this.palette.append(this.view.element('div', 'ra-empty', 'No components match.'));
        }
    }

    protected renderGraph(): void {
        this.canvasNodes.replaceChildren();
        const template = this.currentTemplate();
        for (const [index, name] of template.input_names.entries()) {
            this.canvasNodes.append(this.nodeCard(name, 'model input', { x: 25, y: 55 + index * 100 }, true));
        }
        for (const node of template.nodes) {
            this.canvasNodes.append(this.nodeCard(node.id, this.nodeLabel(node), node.position, false, node));
        }
        this.drawEdges();
        this.status.classList.remove('valid');
    }

    protected nodeCard(
        title: string,
        subtitle: string,
        position: GraphPosition,
        input: boolean,
        node?: GraphNode,
    ): HTMLElement {
        const card = this.view.element('div', `ra-model-node${input ? ' input' : ''}${node?.id === this.selectedNode ? ' selected' : ''}`);
        card.style.left = `${position.x}px`;
        card.style.top = `${position.y}px`;
        card.append(
            this.view.element('strong', undefined, title),
            this.view.element('small', undefined, subtitle),
            this.view.element('span', undefined, `out: ${(node?.output_ports || ['output']).join(', ')}`),
        );
        if (node) {
            card.onclick = () => {
                this.selectedNode = node.id;
                this.renderGraph();
                this.renderInspector();
            };
            card.onpointerdown = event => this.beginDrag(event, node, card);
        }
        return card;
    }

    protected beginDrag(event: PointerEvent, node: GraphNode, card: HTMLElement): void {
        if ((event.target as HTMLElement).closest('button,input,textarea,select')) {
            return;
        }
        card.setPointerCapture(event.pointerId);
        const startX = event.clientX;
        const startY = event.clientY;
        const origin = { ...node.position };
        card.onpointermove = move => {
            node.position.x = Math.max(5, origin.x + move.clientX - startX);
            node.position.y = Math.max(5, origin.y + move.clientY - startY);
            card.style.left = `${node.position.x}px`;
            card.style.top = `${node.position.y}px`;
            this.drawEdges();
        };
        card.onpointerup = () => {
            card.onpointermove = null;
            card.onpointerup = null;
        };
    }

    protected drawEdges(): void {
        this.edges.replaceChildren();
        const template = this.currentTemplate();
        const positions = new Map<string, GraphPosition>();
        template.input_names.forEach((name, index) => positions.set(name, { x: 25, y: 55 + index * 100 }));
        template.nodes.forEach(node => positions.set(node.id, node.position));
        for (const node of template.nodes) {
            for (const source of Object.values(node.inputs)) {
                const from = positions.get(source.split('.', 1)[0]);
                if (!from) {
                    continue;
                }
                const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
                const x1 = from.x + 180;
                const y1 = from.y + 35;
                const x2 = node.position.x;
                const y2 = node.position.y + 35;
                const bend = Math.max(45, Math.abs(x2 - x1) * .4);
                path.setAttribute('d', `M${x1} ${y1} C${x1 + bend} ${y1},${x2 - bend} ${y2},${x2} ${y2}`);
                path.setAttribute('class', 'ra-model-edge');
                this.edges.append(path);
            }
        }
    }

    protected renderInspector(): void {
        this.inspector.replaceChildren();
        const template = this.currentTemplate();
        const selected = template.nodes.find(node => node.id === this.selectedNode);
        if (!selected) {
            const inputsEditor = this.jsonEditor(template.input_names, value => {
                if (!Array.isArray(value) || !value.length) throw new Error('input_names must be a non-empty array.');
                template.input_names = value.map(String);
                this.renderGraph();
            });
            const outputsEditor = this.jsonEditor(template.outputs, value => {
                template.outputs = outputs(value, template.input_names[0]);
                this.renderGraph();
            });
            const variablesEditor = this.jsonEditor(this.graph.variables, value => {
                this.graph.variables = object(value);
            });
            this.inspector.append(
                this.field('Input names', inputsEditor),
                this.field('Outputs', outputsEditor),
                this.field('Variables', variablesEditor),
                this.view.element('p', 'ra-help', 'Select a node to edit its complete typed definition.'),
            );
            return;
        }
        const editor = this.jsonEditor(selected, value => {
            const normalized = normalizeNode(value, template.nodes.indexOf(selected));
            if (!IDENTIFIER.test(normalized.id)) throw new Error('Node id must begin with a letter.');
            const index = template.nodes.indexOf(selected);
            template.nodes[index] = normalized;
            this.selectedNode = normalized.id;
            this.renderGraph();
        });
        const remove = this.view.button('Delete node', () => {
            template.nodes = template.nodes.filter(node => node.id !== selected.id);
            for (const node of template.nodes) {
                node.inputs = Object.fromEntries(Object.entries(node.inputs).filter(([, source]) => source.split('.', 1)[0] !== selected.id));
            }
            template.outputs = Object.fromEntries(Object.entries(template.outputs).filter(([, source]) => source.split('.', 1)[0] !== selected.id));
            if (!Object.keys(template.outputs).length) template.outputs = { output: template.input_names[0] };
            this.selectedNode = undefined;
            this.renderGraph();
            this.renderInspector();
        }, 'danger');
        this.inspector.append(this.field('Node definition', editor), remove);
    }

    protected jsonEditor(value: unknown, apply: (value: unknown) => void): HTMLTextAreaElement {
        const editor = this.view.element('textarea', 'ra-model-json');
        editor.value = JSON.stringify(value, null, 2);
        editor.onchange = () => {
            apply(JSON.parse(editor.value));
            this.status.textContent = 'Modified · not validated';
            this.status.classList.remove('valid');
        };
        return editor;
    }

    protected field(label: string, input: HTMLElement): HTMLElement {
        const field = this.view.element('label', 'ra-model-field');
        field.append(this.view.element('span', undefined, label), input);
        return field;
    }

    protected addComponent(component: ComponentSpec): void {
        const properties = component.schema?.properties || {};
        const params = Object.fromEntries(
            Object.entries(properties).filter(([, schema]) => 'default' in schema).map(([name, schema]) => [name, schema.default]),
        );
        this.appendNode({
            id: this.nextId(component.name.split('/').at(-1) || 'module'),
            kind: 'module',
            type: component.name,
            inputs: { input: this.defaultSource() },
            params,
            output_ports: ['output'],
            call_style: 'positional',
            position: this.nextPosition(),
        });
    }

    protected addControl(kind: GraphNode['kind']): void {
        const firstSubgraph = Object.keys(this.graph.subgraphs)[0];
        const node: GraphNode = normalizeNode({
            id: this.nextId(kind),
            kind,
            inputs: { input: this.defaultSource() },
            params: {},
            output_ports: ['output'],
            position: this.nextPosition(),
        }, this.currentTemplate().nodes.length);
        if (kind === 'python') Object.assign(node, { target: 'torch.nn:Identity', call_style: 'positional' });
        if (kind === 'composite') Object.assign(node, { template: firstSubgraph || '' });
        if (kind === 'repeat') Object.assign(node, { template: firstSubgraph || '', count: 1, weights: 'independent', index_name: 'index', carry: {} });
        if (kind === 'switch') Object.assign(node, { selector: true, branches: {}, default_branch: firstSubgraph || null });
        this.appendNode(node);
    }

    protected appendNode(node: GraphNode): void {
        const template = this.currentTemplate();
        template.nodes.push(node);
        if (Object.keys(template.outputs).length === 1 && Object.values(template.outputs)[0] === template.input_names[0]) {
            template.outputs = { output: node.id };
        }
        this.selectedNode = node.id;
        this.renderGraph();
        this.renderInspector();
    }

    protected defaultSource(): string {
        const template = this.currentTemplate();
        const previous = template.nodes.at(-1);
        return previous ? previous.id : template.input_names[0];
    }

    protected nextPosition(): GraphPosition {
        const count = this.currentTemplate().nodes.length;
        return { x: 260 + (count % 5) * 210, y: 55 + Math.floor(count / 5) * 130 };
    }

    protected nextId(raw: string): string {
        const base = raw.replace(/\W/g, '_').replace(/^_+/, '').toLowerCase() || 'node';
        const ids = new Set(this.currentTemplate().nodes.map(node => node.id));
        let candidate = IDENTIFIER.test(base) ? base : `node_${base}`;
        let index = 2;
        while (ids.has(candidate)) candidate = `${base}_${index++}`;
        return candidate;
    }

    protected nodeLabel(node: GraphNode): string {
        if (node.kind === 'module') return node.type || 'module';
        if (node.kind === 'python') return node.target || 'Python module';
        if (node.kind === 'composite') return `Composite · ${node.template || 'unset'}`;
        if (node.kind === 'repeat') return `Repeat · ${node.template || 'unset'}`;
        return 'Switch';
    }

    protected addSubgraph(): void {
        const name = window.prompt('Subgraph name', 'block');
        if (!name) return;
        if (!IDENTIFIER.test(name) || name in this.graph.subgraphs) throw new Error('Subgraph name must be unique and begin with a letter.');
        this.graph.subgraphs[name] = normalizeTemplate({ input_names: ['input'], nodes: [], outputs: { output: 'input' } });
        this.selectedTemplate = name;
        this.selectedNode = undefined;
        this.renderAll();
    }

    protected deleteSubgraph(): void {
        if (this.selectedTemplate === ROOT_TEMPLATE) return;
        const name = this.selectedTemplate;
        if (!window.confirm(`Delete subgraph ${name}?`)) return;
        delete this.graph.subgraphs[name];
        this.selectedTemplate = ROOT_TEMPLATE;
        this.selectedNode = undefined;
        this.renderAll();
    }
}
