import type { ResearchAssistantWidget } from '../research-assistant-widget';
import {
    field,
    runAction,
    sectionTabs,
    select,
    textArea,
} from './tooling-common';

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

interface NotebookCell {
    id: string;
    cell_type: 'code' | 'markdown' | 'raw';
    source: string | string[];
    metadata: Record<string, unknown>;
    outputs?: unknown[];
    execution_count?: number | null;
}

interface NotebookDocument {
    cells: NotebookCell[];
    metadata: Record<string, unknown>;
    nbformat: number;
    nbformat_minor: number;
}

interface NotebookPayload {
    path: string;
    revision: string;
    notebook: NotebookDocument;
}

function sourceText(source: string | string[]): string {
    return Array.isArray(source) ? source.join('') : source;
}

function newCell(type: NotebookCell['cell_type'] = 'code'): NotebookCell {
    return {
        id: `cell-${Date.now()}-${Math.random().toString(16).slice(2)}`,
        cell_type: type,
        source: '',
        metadata: {},
        ...(type === 'code' ? { outputs: [], execution_count: null } : {}),
    };
}

export async function renderNotebooks(view: ResearchAssistantWidget): Promise<void> {
    let activeKernel = '';
    let activateEditor = (): void => undefined;
    let notebook: NotebookDocument | undefined;
    let revision: string | null = null;
    let dirty = false;
    const label = view.input('Context label', 'selected-run-analysis');
    const contextNotebookPath = view.input('Notebook path', 'notebooks/selected-run-analysis.ipynb');
    const kernelName = view.input('Kernel', 'python3');
    const contexts = view.element('div', 'ra-virtual-list');
    const kernels = view.element('div', 'ra-virtual-list');
    const contextOutput = view.output('Create a context or start a kernel.');

    const run = async (operation: () => Promise<unknown>, refresh = true): Promise<void> => {
        await runAction(view, contextOutput, operation, refresh ? loadRuntime : undefined);
    };

    const renderContexts = (items: NotebookContext[]): void => {
        const fragment = document.createDocumentFragment();
        for (const item of items) {
            const actions = view.element('div', 'ra-actions');
            if (item.notebook_path) {
                actions.append(
                    view.button('Open editor', async () => {
                        contextNotebookPath.value = item.notebook_path!;
                        editorPath.value = item.notebook_path!;
                        await loadNotebook();
                        activateEditor();
                    }),
                    view.button('Open Monaco', () => view.openWorkspaceFile(item.notebook_path!)),
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
                    contextOutput.textContent = `Active kernel: ${id}`;
                    renderKernels(items);
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

    const loadRuntime = async (): Promise<void> => {
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
        notebook_path: contextNotebookPath.value.trim() || null,
        kernel_name: kernelName.value.trim() || 'python3',
    })), 'primary');
    const runtime = view.splitPane(
        view.card('Notebook contexts', label, contextNotebookPath, kernelName, createContext, contexts),
        view.card('Kernel sessions', kernels, contextOutput),
    );

    const editorPath = view.input('Notebook path', 'notebooks/analysis.ipynb');
    const editorKernel = view.input('Kernel', 'python3');
    const editorOutput = view.output('Create or load a notebook to edit cells.');
    const saveStatus = view.element('span', 'ra-summary', 'Not loaded');
    const cellsHost = view.element('div', 'ra-notebook-cells');
    const editorSection = view.element('div', 'ra-tool-stack');

    const executeCell = async (cell: NotebookCell): Promise<void> => {
        if (!activeKernel) {
            const started = await view.post<KernelSession>('/api/notebooks/kernels', {
                notebook_path: editorPath.value.trim(),
                kernel_name: editorKernel.value.trim() || null,
                reuse: true,
            });
            activeKernel = started.kernel_id;
            await loadRuntime();
        }
        const result = await view.post<{ message_id: string }>(
            `/api/notebooks/kernels/${encodeURIComponent(activeKernel)}/execute`,
            {
                cell_id: cell.id,
                code: sourceText(cell.source),
                store_history: true,
            },
        );
        editorOutput.textContent = view.pretty(result);
        const deadline = Date.now() + 30000;
        while (Date.now() < deadline) {
            await new Promise(resolve => setTimeout(resolve, 200));
            const payload = await view.get<{ events: Array<{ type: string; content?: Record<string, unknown>; execution_count?: number }>; state?: string }>(
                `/api/notebooks/kernels/${encodeURIComponent(activeKernel)}/events?`
                + `cell_id=${encodeURIComponent(cell.id)}`
                + `&parent_id=${encodeURIComponent(result.message_id)}&limit=2000`,
            );
            const outputs: unknown[] = [];
            for (const event of payload.events || []) {
                const content = event.content || {};
                if (event.type === 'clear_output') outputs.splice(0);
                if (event.type === 'stream') {
                    outputs.push({ output_type: 'stream', name: content.name || 'stdout', text: content.text || '' });
                } else if (event.type === 'execute_result' || event.type === 'display_data') {
                    outputs.push({
                        output_type: event.type,
                        data: content.data || {},
                        metadata: content.metadata || {},
                        ...(event.type === 'execute_result' ? { execution_count: content.execution_count || event.execution_count || null } : {}),
                    });
                } else if (event.type === 'error') {
                    outputs.push({
                        output_type: 'error',
                        ename: content.ename || 'Error',
                        evalue: content.evalue || '',
                        traceback: content.traceback || [],
                    });
                }
            }
            cell.outputs = outputs;
            const complete = payload.events.some(event => event.type === 'execution_complete');
            if (complete || payload.state === 'idle') {
                const count = [...payload.events].reverse().find(event => event.execution_count)?.execution_count;
                if (count !== undefined) cell.execution_count = count;
                editorOutput.textContent = view.pretty(payload.events);
                dirty = true;
                saveStatus.textContent = 'Modified';
                renderCells();
                return;
            }
        }
        throw new Error('Kernel execution did not complete within 30 seconds.');
    };

    const markDirty = (): void => {
        dirty = true;
        saveStatus.textContent = 'Modified';
    };

    const confirmDiscard = (): boolean => !dirty
        || window.confirm('Discard unsaved notebook changes?');

    const renderCells = (): void => {
        cellsHost.replaceChildren();
        if (!notebook) return;
        notebook.cells.forEach((cell, index) => {
            const type = select(view, ['code', 'markdown', 'raw'], cell.cell_type);
            const source = textArea(`${cell.cell_type} cell`, sourceText(cell.source), cell.cell_type === 'code' ? 9 : 6);
            source.className = 'ra-cell-source';
            source.oninput = () => {
                cell.source = source.value;
                dirty = true;
                saveStatus.textContent = 'Modified';
            };
            type.onchange = () => {
                cell.cell_type = type.value as NotebookCell['cell_type'];
                if (cell.cell_type === 'code') {
                    cell.outputs ??= [];
                    cell.execution_count ??= null;
                } else {
                    delete cell.outputs;
                    delete cell.execution_count;
                }
                dirty = true;
                saveStatus.textContent = 'Modified';
                renderCells();
            };
            source.onkeydown = event => {
                if (cell.cell_type !== 'code') return;
                if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
                    event.preventDefault();
                    void executeCell(cell);
                } else if (event.shiftKey && event.key === 'Enter') {
                    event.preventDefault();
                    void executeCell(cell).then(() => {
                        const next = cellsHost.querySelectorAll<HTMLTextAreaElement>('.ra-cell-source')[
                            Math.min(index + 1, notebook?.cells.length ? notebook.cells.length - 1 : 0)
                        ];
                        next?.focus();
                    });
                }
            };
            const actions = view.element('div', 'ra-actions', undefined, [
                view.button('Run', () => executeCell(cell), cell.cell_type === 'code' ? 'primary' : ''),
                view.button('↑', () => {
                    if (!notebook || index === 0) return;
                    [notebook.cells[index - 1], notebook.cells[index]] = [notebook.cells[index], notebook.cells[index - 1]];
                    markDirty();
                    renderCells();
                }),
                view.button('↓', () => {
                    if (!notebook || index + 1 >= notebook.cells.length) return;
                    [notebook.cells[index], notebook.cells[index + 1]] = [notebook.cells[index + 1], notebook.cells[index]];
                    markDirty();
                    renderCells();
                }),
                view.button('Add below', () => {
                    notebook?.cells.splice(index + 1, 0, newCell('code'));
                    markDirty();
                    renderCells();
                }),
                view.button('Delete', () => {
                    notebook?.cells.splice(index, 1);
                    markDirty();
                    renderCells();
                }, 'danger'),
            ]);
            const header = view.element('div', 'ra-cell-header', undefined, [
                view.element('strong', undefined, `${index + 1} · ${cell.id}`),
                type,
                actions,
            ]);
            const output = cell.outputs?.length
                ? view.output(view.pretty(cell.outputs))
                : view.element('small', 'ra-help', cell.cell_type === 'code' ? 'No stored outputs.' : '');
            cellsHost.append(view.element('section', 'ra-notebook-cell', undefined, [header, source, output]));
        });
        if (!notebook.cells.length) {
            cellsHost.append(view.element('div', 'ra-empty', 'Notebook has no cells.'));
        }
    };

    const loadNotebook = async (): Promise<void> => {
        if (!confirmDiscard()) return;
        const result = await view.get<NotebookPayload>(`/api/notebooks/file?path=${encodeURIComponent(editorPath.value.trim())}`);
        notebook = result.notebook;
        revision = result.revision;
        dirty = false;
        saveStatus.textContent = 'Loaded';
        editorOutput.textContent = `Loaded ${result.path} · ${notebook.cells.length} cells`;
        renderCells();
    };
    const createNotebook = async (): Promise<void> => {
        if (!confirmDiscard()) return;
        const result = await view.post<NotebookPayload>('/api/notebooks/file', {
            path: editorPath.value.trim(),
            kernel_name: editorKernel.value.trim() || 'python3',
        });
        notebook = result.notebook;
        revision = result.revision;
        dirty = false;
        saveStatus.textContent = 'Created';
        editorOutput.textContent = `Created ${result.path}`;
        renderCells();
    };
    const saveNotebook = async (): Promise<void> => {
        if (!notebook) throw new Error('Create or load a notebook first.');
        const result = await view.put<NotebookPayload>(`/api/notebooks/file?path=${encodeURIComponent(editorPath.value.trim())}`, {
            notebook,
            revision,
        });
        notebook = result.notebook;
        revision = result.revision;
        dirty = false;
        saveStatus.textContent = 'Saved';
        editorOutput.textContent = `Saved ${result.path}`;
        renderCells();
    };
    const runAll = async (): Promise<void> => {
        if (!notebook) throw new Error('Create or load a notebook first.');
        for (const cell of notebook.cells) {
            if (cell.cell_type === 'code' && sourceText(cell.source).trim()) {
                await executeCell(cell);
            }
        }
        editorOutput.textContent = `Submitted ${notebook.cells.filter(cell => cell.cell_type === 'code').length} code cells.`;
    };
    const readLog = async (): Promise<void> => {
        if (!activeKernel) throw new Error('Select or start a kernel first.');
        editorOutput.textContent = String(await view.get(`/api/notebooks/kernels/${encodeURIComponent(activeKernel)}/log?limit=2000000`));
    };

    editorSection.append(
        view.element('div', 'ra-toolbar', undefined, [
            editorPath,
            editorKernel,
            view.button('Create', createNotebook),
            view.button('Load', loadNotebook),
            view.button('Save', saveNotebook, 'primary'),
            view.button('Add code', () => {
                if (!notebook) throw new Error('Create or load a notebook first.');
                notebook.cells.push(newCell('code'));
                markDirty();
                renderCells();
            }),
            view.button('Add markdown', () => {
                if (!notebook) throw new Error('Create or load a notebook first.');
                notebook.cells.push(newCell('markdown'));
                markDirty();
                renderCells();
            }),
            view.button('Run all', runAll, 'primary'),
            view.button('Kernel log', readLog),
            view.button('Open raw JSON', () => view.openWorkspaceFile(editorPath.value.trim())),
            saveStatus,
        ]),
        view.splitPane(view.card('Notebook cells', cellsHost), view.card('Execution output', editorOutput)),
    );

    const tabs = sectionTabs(view, [
        { id: 'runtime', label: 'Contexts & kernels', node: runtime },
        { id: 'editor', label: 'Notebook editor', node: editorSection },
    ]);
    activateEditor = () => {
        tabs.querySelector<HTMLButtonElement>('[data-section="editor"]')?.click();
    };
    view.content.replaceChildren(tabs);
    await loadRuntime();
}
