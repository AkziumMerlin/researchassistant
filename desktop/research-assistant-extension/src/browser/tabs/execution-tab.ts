import type { ResearchAssistantWidget } from '../research-assistant-widget';

export async function renderExecution(view: ResearchAssistantWidget): Promise<void> {
    const payload = await view.get<{ launches: Array<Record<string, unknown>> }>('/api/launches');
    const rows = view.element('div', 'ra-virtual-list');
    const output = view.output('Select a launch action.');
    for (const launch of payload.launches || []) {
        const id = String(launch.launch_id || launch.id || 'launch');
        const state = String(launch.state || 'unknown');
        rows.append(view.row([
            view.element('div', 'ra-identity', undefined, [
                view.element('strong', undefined, id),
                view.element('small', undefined, String(launch.config_path || launch.path || '')),
            ]),
            view.element('span', `ra-state ${state}`, state),
            view.button('Inspect', async () => {
                output.textContent = view.pretty(await view.get(`/api/launches/${encodeURIComponent(id)}`));
            }),
        ]));
    }
    view.content.replaceChildren(
        view.splitPane(view.card('Durable launches', rows), view.card('Launch detail', output)),
    );
}
