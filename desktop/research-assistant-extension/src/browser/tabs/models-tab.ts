import { ModelsEditor } from '../models-editor';
import type { ResearchAssistantWidget } from '../research-assistant-widget';

interface ComponentSpec {
    name: string;
    description?: string;
    catalog?: string;
    provider?: string;
    metadata?: Record<string, unknown>;
    schema?: { properties?: Record<string, Record<string, unknown>> };
}

interface ArchitectureFile {
    path: string;
    name: string;
}

export async function renderModels(view: ResearchAssistantWidget): Promise<void> {
    const [bootstrap, architectures] = await Promise.all([
        view.get<{ components: ComponentSpec[] }>('/api/bootstrap'),
        view.get<{ architectures: ArchitectureFile[] }>('/api/architectures'),
    ]);
    const components = (bootstrap.components || []).filter(item => item.catalog === 'graph-node');
    const editor = new ModelsEditor(view, components, architectures.architectures || []);
    view.content.replaceChildren(editor.node);
}
