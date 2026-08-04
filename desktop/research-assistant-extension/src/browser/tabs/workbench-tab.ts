import type { ResearchAssistantWidget } from '../research-assistant-widget';
import {
    field,
    runAction,
    sectionTabs,
    select,
    textArea,
} from './tooling-common';

interface WorkbenchCapabilities {
    trusted_dev: boolean;
    workspace: string;
    python: string;
    conda_prefix?: string;
    features: Record<string, boolean>;
}

interface WorkspaceRow {
    name: string;
    path: string;
    python?: string;
    conda_env?: string;
    ssh_target?: string;
}

interface AnalysisSession {
    session_id: string;
    label?: string;
    state?: string;
    command?: string[];
    created_at?: string;
    pid?: number;
}

export async function renderWorkbench(view: ResearchAssistantWidget): Promise<void> {
    const [capabilities, workspaceCapabilities, plugins] = await Promise.all([
        view.get<WorkbenchCapabilities>('/api/workbench/capabilities'),
        view.get<Record<string, unknown>>('/api/workspace/capabilities'),
        view.get<Record<string, unknown>>('/api/workspace/plugins'),
    ]);

    const workspaceList = view.element('div', 'ra-virtual-list');
    const workspaceName = view.input('Name');
    const workspacePath = view.input('Path', capabilities.workspace);
    const workspacePython = view.input('Python (optional)');
    const workspaceConda = view.input('Conda env (optional)');
    const workspaceSsh = view.input('SSH target (optional)');
    const workspaceOutput = view.output('Manage reusable local and SSH workspace descriptors.');
    const loadWorkspaces = async (): Promise<void> => {
        const payload = await view.get<{ workspaces: WorkspaceRow[] }>('/api/workbench/workspaces');
        const fragment = document.createDocumentFragment();
        for (const item of payload.workspaces || []) {
            fragment.append(view.row([
                view.element('div', 'ra-identity', undefined, [
                    view.element('strong', undefined, item.name),
                    view.element('small', undefined, `${item.path} · ${item.conda_env || item.python || 'default Python'} · ${item.ssh_target || 'local'}`),
                ]),
                view.button('Remove', () => runAction(view, workspaceOutput, () => view.post('/api/workbench/workspaces/remove', {
                    name: item.name,
                }), loadWorkspaces), 'danger'),
            ]));
        }
        workspaceList.replaceChildren(fragment);
    };
    const workspaces = view.splitPane(
        view.card(
            'Workspace catalog',
            view.element('div', 'ra-actions', undefined, [view.button('Refresh', loadWorkspaces)]),
            workspaceList,
        ),
        view.card(
            'Add workspace',
            field(view, 'Name', workspaceName),
            field(view, 'Path', workspacePath),
            field(view, 'Python', workspacePython),
            field(view, 'Conda env', workspaceConda),
            field(view, 'SSH target', workspaceSsh),
            view.button('Save workspace', () => runAction(view, workspaceOutput, () => view.post('/api/workbench/workspaces', {
                name: workspaceName.value.trim(),
                path: workspacePath.value.trim(),
                python: workspacePython.value.trim() || null,
                conda_env: workspaceConda.value.trim() || null,
                ssh_target: workspaceSsh.value.trim() || null,
            }), loadWorkspaces), 'primary'),
            workspaceOutput,
        ),
    );

    const environmentPython = view.input('Python interpreter', capabilities.python);
    const environmentOutput = view.output('Inspect the active interpreter or available Conda environments.');
    const environments = view.splitPane(
        view.card(
            'Python and Conda',
            field(view, 'Interpreter', environmentPython),
            view.element('div', 'ra-actions', undefined, [
                view.button('List environments', () => runAction(view, environmentOutput, () => view.get('/api/workbench/environments')), 'primary'),
                view.button('Inspect interpreter', () => runAction(view, environmentOutput, () => view.post('/api/workbench/environments/inspect', {
                    python: environmentPython.value.trim(),
                }))),
            ]),
        ),
        view.card('Environment details', environmentOutput),
    );

    const sessions = view.element('div', 'ra-virtual-list');
    const script = view.input('Script path');
    const scriptArgs = view.input('Arguments');
    const sessionCwd = view.input('Working directory', '.');
    const sessionPython = view.input('Python', capabilities.python);
    const sessionLabel = view.input('Label');
    const scratchpad = textArea('Trusted inline Python scratchpad', 'print("analysis")', 10);
    const analysisOutput = view.output('Detached analysis sessions survive closing the desktop window.');
    const loadSessions = async (): Promise<void> => {
        const payload = await view.get<{ sessions: AnalysisSession[] }>('/api/workbench/analysis/sessions?limit=1000');
        const fragment = document.createDocumentFragment();
        for (const session of payload.sessions || []) {
            const id = session.session_id;
            fragment.append(view.row([
                view.element('div', 'ra-identity', undefined, [
                    view.element('strong', undefined, session.label || id),
                    view.element('small', undefined, `${id} · pid ${session.pid || '—'} · ${session.created_at || ''}`),
                ]),
                view.element('span', `ra-state ${session.state || 'unknown'}`, session.state || 'unknown'),
                view.element('div', 'ra-actions', undefined, [
                    view.button('Inspect', () => runAction(view, analysisOutput, () => view.get(`/api/workbench/analysis/sessions/${encodeURIComponent(id)}`))),
                    view.button('stdout', () => runAction(view, analysisOutput, () => view.get(`/api/workbench/analysis/sessions/${encodeURIComponent(id)}/logs?stream=stdout&tail_bytes=2000000`))),
                    view.button('stderr', () => runAction(view, analysisOutput, () => view.get(`/api/workbench/analysis/sessions/${encodeURIComponent(id)}/logs?stream=stderr&tail_bytes=2000000`))),
                    view.button('Stop', () => runAction(view, analysisOutput, () => view.post('/api/workbench/analysis/stop', {
                        session_id: id,
                    }), loadSessions), 'danger'),
                ]),
            ]));
        }
        sessions.replaceChildren(fragment);
    };
    const analysis = view.element('div', 'ra-tool-stack', undefined, [
        view.splitPane(
            view.card(
                'Start detached script',
                field(view, 'Script', script),
                field(view, 'Arguments', scriptArgs),
                field(view, 'Working directory', sessionCwd),
                field(view, 'Python', sessionPython),
                field(view, 'Label', sessionLabel),
                view.button('Start script', () => runAction(view, analysisOutput, () => view.post('/api/workbench/analysis/script', {
                    script: script.value.trim(),
                    args: view.split(scriptArgs.value),
                    cwd: sessionCwd.value.trim() || '.',
                    python: sessionPython.value.trim() || capabilities.python,
                    profile: false,
                    label: sessionLabel.value.trim() || null,
                }), loadSessions), 'primary'),
            ),
            view.card(
                'Trusted scratchpad',
                scratchpad,
                view.button('Run scratchpad', () => runAction(view, analysisOutput, () => view.post('/api/workbench/analysis/scratchpad', {
                    code: scratchpad.value,
                    cwd: sessionCwd.value.trim() || '.',
                    python: sessionPython.value.trim() || capabilities.python,
                    label: sessionLabel.value.trim() || null,
                }), loadSessions), 'primary'),
                view.element('small', 'ra-help', capabilities.trusted_dev
                    ? 'Trusted developer mode is enabled.'
                    : 'Inline scratchpads and new processes require RA_TRUSTED_DEV=1.'),
            ),
        ),
        view.splitPane(
            view.card('Analysis sessions', view.button('Refresh', loadSessions), sessions),
            view.card('Session output', analysisOutput),
        ),
    ]);

    const devOutput = view.output(
        capabilities.trusted_dev
            ? 'Trusted developer operations are enabled.'
            : 'Read-only Git diagnostics are available; write operations require RA_TRUSTED_DEV=1.',
    );
    const diffPath = view.input('Diff path (optional)');
    const searchQuery = view.input('Search text');
    const searchRoot = view.input('Search root', '.');
    const searchPattern = view.input('File pattern', '*');
    const branchName = view.input('Branch name');
    const branchStart = view.input('Start point (optional)');
    const commitMessage = view.input('Commit message');
    const commitPaths = view.input('Paths to commit', '.');
    const pushWithCommit = document.createElement('input');
    pushWithCommit.type = 'checkbox';
    const taskSelect = view.element('select', 'theia-select');
    const loadTasks = async (): Promise<void> => {
        const payload = await view.get<{ tasks: Array<{ name: string } | string>; trusted: boolean }>('/api/workbench/dev/tasks');
        taskSelect.replaceChildren();
        for (const item of payload.tasks || []) {
            const name = typeof item === 'string' ? item : item.name;
            const option = view.element('option', undefined, name);
            option.value = name;
            taskSelect.append(option);
        }
        devOutput.textContent = view.pretty(payload);
    };
    const developer = view.element('div', 'ra-report-grid', undefined, [
        view.card(
            'Diagnostics and Git',
            view.element('div', 'ra-actions', undefined, [
                view.button('Diagnostics', () => runAction(view, devOutput, () => view.get('/api/workbench/dev/diagnostics'))),
                view.button('Git status', () => runAction(view, devOutput, () => view.get('/api/workbench/dev/git/status')), 'primary'),
                view.button('Git log', () => runAction(view, devOutput, () => view.get('/api/workbench/dev/git/log?limit=100'))),
                view.button('Branches', () => runAction(view, devOutput, () => view.get('/api/workbench/dev/git/branches'))),
            ]),
            field(view, 'Optional path', diffPath),
            view.element('div', 'ra-actions', undefined, [
                view.button('Working diff', () => runAction(view, devOutput, () => view.post('/api/workbench/dev/git/diff', {
                    staged: false,
                    path: diffPath.value.trim() || null,
                }))),
                view.button('Staged diff', () => runAction(view, devOutput, () => view.post('/api/workbench/dev/git/diff', {
                    staged: true,
                    path: diffPath.value.trim() || null,
                }))),
            ]),
        ),
        view.card(
            'Workspace search',
            field(view, 'Query', searchQuery),
            field(view, 'Root', searchRoot),
            field(view, 'Pattern', searchPattern),
            view.button('Search', () => runAction(view, devOutput, () => view.post('/api/workbench/dev/search', {
                query: searchQuery.value,
                root: searchRoot.value.trim() || '.',
                pattern: searchPattern.value.trim() || '*',
                case_sensitive: false,
                max_results: 1000,
            })), 'primary'),
        ),
        view.card(
            'Trusted Git writes',
            field(view, 'Branch', branchName),
            field(view, 'Start point', branchStart),
            view.element('div', 'ra-actions', undefined, [
                view.button('Create branch', () => runAction(view, devOutput, () => view.post('/api/workbench/dev/git/branch', {
                    name: branchName.value.trim(),
                    start_point: branchStart.value.trim() || null,
                }))),
                view.button('Switch branch', () => runAction(view, devOutput, () => view.post('/api/workbench/dev/git/switch', {
                    name: branchName.value.trim(),
                    start_point: null,
                }))),
            ]),
            field(view, 'Commit message', commitMessage),
            field(view, 'Paths', commitPaths),
            view.element('label', 'ra-check', undefined, [pushWithCommit, document.createTextNode(' Push after commit')]),
            view.element('div', 'ra-actions', undefined, [
                view.button('Commit', () => runAction(view, devOutput, () => view.post('/api/workbench/dev/git/commit', {
                    message: commitMessage.value.trim(),
                    paths: view.split(commitPaths.value),
                    push: pushWithCommit.checked,
                })), 'primary'),
                view.button('Push current branch', () => runAction(view, devOutput, () => view.post('/api/workbench/dev/git/push', {}))),
            ]),
            view.element('small', 'ra-help', capabilities.trusted_dev
                ? 'Write operations are enabled.'
                : 'Backend will reject write operations until RA_TRUSTED_DEV=1.'),
        ),
        view.card(
            'Project tasks',
            taskSelect,
            view.element('div', 'ra-actions', undefined, [
                view.button('Load tasks', loadTasks),
                view.button('Run selected task', () => {
                    if (!taskSelect.value) throw new Error('Select a task.');
                    return runAction(view, devOutput, () => view.post('/api/workbench/dev/tasks/run', {
                        name: taskSelect.value,
                    }), loadSessions);
                }, 'primary'),
            ]),
        ),
        view.card('Developer output', devOutput),
    ]);

    const capabilityOutput = view.output(view.pretty({
        workbench: capabilities,
        workspace: workspaceCapabilities,
        plugins,
    }));
    const overview = view.splitPane(
        view.card(
            'Workbench backend',
            view.element('div', 'ra-kv-grid', undefined, [
                view.element('strong', undefined, 'Workspace'),
                view.element('span', undefined, capabilities.workspace),
                view.element('strong', undefined, 'Python'),
                view.element('span', undefined, capabilities.python),
                view.element('strong', undefined, 'Conda prefix'),
                view.element('span', undefined, capabilities.conda_prefix || 'none'),
                view.element('strong', undefined, 'Trusted developer mode'),
                view.element('span', undefined, String(capabilities.trusted_dev)),
            ]),
        ),
        view.card('Capability map', capabilityOutput),
    );

    view.content.replaceChildren(sectionTabs(view, [
        { id: 'overview', label: 'Overview', node: overview },
        { id: 'workspaces', label: 'Workspaces', node: workspaces },
        { id: 'environments', label: 'Environments', node: environments },
        { id: 'analysis', label: 'Analysis', node: analysis },
        { id: 'developer', label: 'Developer', node: developer },
    ]));
    await Promise.all([loadWorkspaces(), loadSessions(), loadTasks()]);
}
