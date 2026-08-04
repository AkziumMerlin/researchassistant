import type { ResearchAssistantWidget } from '../research-assistant-widget';

interface ArtifactRow {
    artifact_id: string;
    name: string;
    kind: string;
    path: string;
    run_id?: string;
}

export async function renderArtifacts(view: ResearchAssistantWidget): Promise<void> {
    const payload = await view.get<{ artifacts: ArtifactRow[] }>('/api/workbench/artifacts?limit=5000');
    const rows = payload.artifacts || [];
    const query = view.input('Filter artifact, path, kind or run');
    const list = view.element('div', 'ra-virtual-list');
    const output = view.output('Select one artifact for lineage or two for comparison.');
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
                view.element('small', undefined, `${item.kind} · ${item.path}`),
            );
            const lineage = view.button('Lineage', async () => {
                output.textContent = view.pretty(await view.get(
                    `/api/workspace/artifacts/${encodeURIComponent(item.artifact_id)}/lineage?artifact_root=runs`,
                ));
            });
            view.safeClick(lineage, output);
            fragment.append(view.row([checkbox, identity, lineage]));
        }
        list.replaceChildren(fragment);
    };
    query.addEventListener('input', render);
    render();
    const compare = view.button('Compare selected', async () => {
        const ids = [...view.selectedArtifacts];
        if (ids.length !== 2) {
            throw new Error('Select exactly two artifacts.');
        }
        output.textContent = view.pretty(await view.post('/api/workbench/artifacts/compare', {
            left_id: ids[0],
            right_id: ids[1],
            key: null,
        }));
    }, 'primary');
    view.safeClick(compare, output);
    view.content.replaceChildren(
        view.element('div', 'ra-toolbar', undefined, [query, selected, compare]),
        view.splitPane(view.card('Artifacts', list), view.card('Artifact detail', output)),
    );
}
