import type { ResearchAssistantWidget } from '../research-assistant-widget';

export async function renderNotebooks(view: ResearchAssistantWidget): Promise<void> {
    const payload = await view.get<{ contexts: Array<Record<string, unknown>> }>(
        '/api/workspace/notebook-contexts',
    );
    const rows = view.element('div', 'ra-virtual-list');
    for (const item of payload.contexts || []) {
        const notebookPath = typeof item.notebook_path === 'string' ? item.notebook_path : undefined;
        rows.append(view.row([
            view.element('div', 'ra-identity', undefined, [
                view.element('strong', undefined, String(item.label || item.context_id || 'context')),
                view.element(
                    'small',
                    undefined,
                    `${(item.run_ids as unknown[] | undefined)?.length || 0} runs · ${(item.artifact_ids as unknown[] | undefined)?.length || 0} artifacts`,
                ),
            ]),
            notebookPath
                ? view.button('Open notebook', () => view.openWorkspaceFile(notebookPath), 'primary')
                : view.element('span'),
        ]));
    }
    view.content.replaceChildren(view.card('Notebook contexts', rows));
}
