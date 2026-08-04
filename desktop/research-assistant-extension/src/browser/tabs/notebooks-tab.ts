import type { ResearchAssistantWidget } from '../research-assistant-widget';

interface NotebookContext {
    context_id: string;
    label: string;
    notebook_path?: string;
    run_ids: string[];
    artifact_ids: string[];
}

interface KernelSession {
    kernel_id: string;
    notebook_path: string;
    kernel_name?: string;
    state?: string;
}

export async function renderNotebooks(view: ResearchAssistantWidget): Promise<void> {
    const label = view.input('Context label', 'selected-run-analysis');
    const notebookPath = view.input('Notebook path', 'notebooks/selected-run-analysis.ipynb');
    const kernelName = view.input('Kernel', 'python3');
    const contexts = view.element('div', 'ra-virtual-list');
    const kernels = view.element('div', 'ra-virtual-list');
    const output = view.output('Create a context or start a kernel.');
    const code = document.createElement('textarea');
    code.placeholder = 'Python code';
    code.value = 'print(RUNS)';
    let activeKernel = '';

    const run = async (operation: () => Promise<unknown>, refresh = true): Promise<void> => {
        try {
            output.classList.remove('error');
            output.textContent = view.pretty(await operation());
            if (refresh) {
                await load();
            }
        } catch (error) {
            output.classList.add('error');
            output.textContent = error instanceof Error ? error.message : String(error);
        }
    };

    const renderContexts = (items: NotebookContext[]): void => {
        const fragment = document.createDocumentFragment();
        for (const item of items) {
            const actions = view.element('div', 'ra-actions');
            if (item.notebook_path) {
                actions.append(
                    view.button('Open', () => view.openWorkspaceFile(item.notebook_path!)),
                    view.button('Start kernel', () => run(() => view.post('/api/notebooks/kernels', {
                        notebook_path: item.notebook_path,
                        kernel_name: kernelName.value.trim() || null,
                        reuse: true,
                    }))),
                );
            }
            fragment.append(view.row([
                view.element('div', 'ra-identity', undefined, [
                    view.element('strong', undefined, item.label),
                    view.element('small', undefined, `${item.run_ids.length} runs · ${item.artifact_ids.length} artifacts`),
                ]),
                actions,
            ]));
        }
        contexts.replaceChildren(fragment);
    };

    const renderKernels = (items: KernelSession[]): void => {
        const fragment = document.createDocumentFragment();
        for (const item of items) {
            const id = item.kernel_id;
            const actions = view.element('div', 'ra-actions', undefined, [
                view.button('Use', () => {
                    activeKernel = id;
                    output.textContent = `Active kernel: ${id}`;
                }, activeKernel === id ? 'primary' : ''),
                view.button('Interrupt', () => run(() => view.post(`/api/notebooks/kernels/${encodeURIComponent(id)}/interrupt`, {}))),
                view.button('Restart', () => run(() => view.post(`/api/notebooks/kernels/${encodeURIComponent(id)}/restart`, {}))),
                view.button('Stop', () => run(() => view.remove(`/api/notebooks/kernels/${encodeURIComponent(id)}`)), 'danger'),
            ]);
            fragment.append(view.row([
                view.element('div', 'ra-identity', undefined, [
                    view.element('strong', undefined, id),
                    view.element('small', undefined, `${item.notebook_path} · ${item.kernel_name || 'python'} · ${item.state || 'running'}`),
                ]),
                actions,
            ]));
        }
        kernels.replaceChildren(fragment);
    };

    const load = async (): Promise<void> => {
        const [contextPayload, kernelPayload] = await Promise.all([
            view.get<{ contexts: NotebookContext[] }>('/api/workspace/notebook-contexts'),
            view.get<{ sessions: KernelSession[] }>('/api/notebooks/kernels'),
        ]);
        renderContexts(contextPayload.contexts || []);
        renderKernels(kernelPayload.sessions || []);
    };

    const createContext = view.button('Create context', () => run(() => view.post('/api/workspace/notebook-contexts', {
        artifact_root: 'runs',
        run_ids: [...view.selectedRuns],
        artifact_ids: [...view.selectedArtifacts],
        label: label.value.trim() || null,
        notebook_path: notebookPath.value.trim() || null,
        kernel_name: kernelName.value.trim() || 'python3',
    })), 'primary');
    const execute = view.button('Execute', () => {
        if (!activeKernel) {
            throw new Error('Select an active kernel.');
        }
        return run(() => view.post(`/api/notebooks/kernels/${encodeURIComponent(activeKernel)}/execute`, {
            cell_id: `desktop-${Date.now()}`,
            code: code.value,
            store_history: true,
        }), false);
    }, 'primary');
    const readLog = view.button('Read log', async () => {
        if (!activeKernel) {
            throw new Error('Select an active kernel.');
        }
        output.textContent = String(await view.get(`/api/notebooks/kernels/${encodeURIComponent(activeKernel)}/log`));
    });

    view.content.replaceChildren(
        view.splitPane(
            view.card('Notebook contexts', label, notebookPath, kernelName, createContext, contexts),
            view.card('Kernels and cells', kernels, code, view.element('div', 'ra-actions', undefined, [execute, readLog]), output),
        ),
    );
    await load();
}
