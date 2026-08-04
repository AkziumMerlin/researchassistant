import type { ResearchAssistantWidget } from '../research-assistant-widget';

export async function renderModels(view: ResearchAssistantWidget): Promise<void> {
    const [bootstrap, architectures] = await Promise.all([
        view.get<{ components: Array<Record<string, unknown>> }>('/api/bootstrap'),
        view.get<{ architectures: Array<{ path: string; name: string }> }>('/api/architectures'),
    ]);
    const components = (bootstrap.components || []).filter(item => item.catalog === 'graph-node');
    const search = view.input('Search registered PyTorch components');
    const componentList = view.element('div', 'ra-component-list');
    const renderComponents = (): void => {
        const needle = search.value.trim().toLowerCase();
        const fragment = document.createDocumentFragment();
        for (const item of components) {
            const name = String(item.name || 'component');
            const description = String(item.description || '');
            const category = String((item.metadata as Record<string, unknown> | undefined)?.category || 'Modules');
            if (needle && !`${name} ${description} ${category} ${String(item.provider || '')}`.toLowerCase().includes(needle)) {
                continue;
            }
            const card = view.element('button', 'ra-component');
            card.type = 'button';
            card.append(
                view.element('strong', undefined, name.split('/').at(-1) || name),
                view.element('span', undefined, category),
                view.element('small', undefined, description),
            );
            card.addEventListener('click', () => {
                view.messages.info(`${name}: ${description || 'No description'}`);
            });
            fragment.append(card);
        }
        componentList.replaceChildren(fragment);
    };
    search.addEventListener('input', renderComponents);
    renderComponents();

    const files = view.element('div', 'ra-virtual-list');
    for (const architecture of architectures.architectures || []) {
        files.append(view.row([
            view.element('span', 'ra-path', architecture.path),
            view.button('Open', () => view.openWorkspaceFile(architecture.path)),
        ]));
    }
    view.content.replaceChildren(
        view.splitPane(
            view.card('Registered components', search, componentList),
            view.card('Architecture documents', files),
            'models',
        ),
    );
}
