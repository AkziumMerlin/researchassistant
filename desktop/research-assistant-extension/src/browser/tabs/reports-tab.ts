import type { ResearchAssistantWidget } from '../research-assistant-widget';

export async function renderReports(view: ResearchAssistantWidget): Promise<void> {
    const output = view.output('Loading metric index…');
    const rebuild = view.button('Rebuild metric index', async () => {
        output.textContent = view.pretty(await view.post('/api/analytics/catalog', {
            artifact_root: 'runs',
            rebuild: true,
        }));
    }, 'primary');
    view.safeClick(rebuild, output);
    output.textContent = view.pretty(await view.post('/api/analytics/catalog', {
        artifact_root: 'runs',
        rebuild: false,
    }));
    view.content.replaceChildren(view.card('Reports and indexed metrics', rebuild, output));
}
