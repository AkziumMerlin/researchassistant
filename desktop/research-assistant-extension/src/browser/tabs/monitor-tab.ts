import type { ResearchAssistantWidget } from '../research-assistant-widget';

interface ProcessRow {
    pid: number;
    name?: string;
    command?: string;
    user?: string;
    cpu_percent?: number;
    memory_rss_bytes?: number;
    memory_percent?: number;
    gpu_memory_mb?: number;
    runtime_seconds?: number;
    state?: string;
    ra?: Record<string, unknown>;
}

interface MonitorSnapshot {
    host: {
        hostname?: string;
        cpu_percent?: number;
        memory?: { percent?: number; used_bytes?: number; total_bytes?: number };
        load_1?: number;
        process_count?: number;
    };
    gpus: {
        available?: boolean;
        error?: string;
        devices?: Array<Record<string, unknown>>;
    };
    processes: ProcessRow[];
    process_total: number;
    timestamp?: string;
}

function gibibytes(value: number | undefined): string {
    return `${((value || 0) / (1024 ** 3)).toFixed(2)} GiB`;
}

export async function renderMonitor(view: ResearchAssistantWidget): Promise<void> {
    const scope = view.element('select', 'theia-select');
    for (const value of ['all', 'user', 'gpu', 'ra']) {
        const option = view.element('option', undefined, value);
        option.value = value;
        scope.append(option);
    }
    scope.value = 'user';
    const sort = view.element('select', 'theia-select');
    for (const value of ['cpu', 'memory', 'gpu', 'runtime', 'pid']) {
        const option = view.element('option', undefined, value);
        option.value = value;
        sort.append(option);
    }
    const search = view.input('Filter PID, command, run or user');
    const summary = view.element('span', 'ra-summary', 'Loading system state…');
    const host = view.element('div', 'ra-monitor-summary');
    const gpus = view.element('div', 'ra-monitor-gpus');
    const processes = view.element('div', 'ra-virtual-list ra-monitor-processes');
    const detail = view.output('Select a process to inspect its ResearchAssistant context and logs.');

    const inspect = async (pid: number): Promise<void> => {
        detail.textContent = view.pretty(await view.get(`/api/system-monitor/processes/${pid}`));
    };

    const signal = async (pid: number, name: string): Promise<void> => {
        if (!window.confirm(`Send SIG${name} to process ${pid}?`)) return;
        detail.textContent = view.pretty(await view.post(
            `/api/system-monitor/processes/${pid}/signal`,
            { signal: name },
        ));
        await load();
    };

    const renderProcesses = (rows: ProcessRow[]): void => {
        const fragment = document.createDocumentFragment();
        for (const process of rows) {
            const identity = view.element('div', 'ra-identity');
            identity.append(
                view.element('strong', undefined, `${process.pid} · ${process.name || 'process'}`),
                view.element('small', undefined, process.command || process.user || ''),
            );
            const usage = view.element(
                'span',
                'ra-monitor-usage',
                `CPU ${(process.cpu_percent || 0).toFixed(1)}% · RAM ${gibibytes(process.memory_rss_bytes)} · GPU ${(process.gpu_memory_mb || 0).toFixed(0)} MiB`,
            );
            const actions = view.element('div', 'ra-actions');
            actions.append(
                view.button('Inspect', () => inspect(process.pid)),
                view.button('INT', () => signal(process.pid, 'INT')),
                view.button('TERM', () => signal(process.pid, 'TERM')),
                view.button('KILL', () => signal(process.pid, 'KILL'), 'danger'),
            );
            fragment.append(view.row([identity, usage, actions]));
        }
        processes.replaceChildren(fragment);
    };

    const load = async (): Promise<void> => {
        const query = new URLSearchParams({
            scope: scope.value,
            sort: sort.value,
            limit: '500',
        });
        if (search.value.trim()) query.set('search', search.value.trim());
        const snapshot = await view.get<MonitorSnapshot>(`/api/system-monitor/snapshot?${query}`);
        const memory = snapshot.host.memory || {};
        host.replaceChildren(
            view.card(
                snapshot.host.hostname || 'Host',
                view.element('strong', undefined, `CPU ${(snapshot.host.cpu_percent || 0).toFixed(1)}%`),
                view.element('span', undefined, `Load ${(snapshot.host.load_1 || 0).toFixed(2)}`),
            ),
            view.card(
                'Memory',
                view.element('strong', undefined, `${(memory.percent || 0).toFixed(1)}%`),
                view.element('span', undefined, `${gibibytes(memory.used_bytes)} / ${gibibytes(memory.total_bytes)}`),
            ),
            view.card(
                'Processes',
                view.element('strong', undefined, String(snapshot.process_total || 0)),
                view.element('span', undefined, `sample ${snapshot.timestamp || 'now'}`),
            ),
        );
        gpus.replaceChildren();
        if (snapshot.gpus.available) {
            for (const device of snapshot.gpus.devices || []) {
                gpus.append(view.card(
                    `GPU ${String(device.index ?? '?')} · ${String(device.name ?? 'device')}`,
                    view.element('strong', undefined, `${Number(device.utilization_percent || 0).toFixed(1)}% util`),
                    view.element('span', undefined, `${Number(device.memory_used_mb || 0).toFixed(0)} / ${Number(device.memory_total_mb || 0).toFixed(0)} MiB`),
                ));
            }
        } else {
            gpus.append(view.element('span', 'ra-empty', snapshot.gpus.error || 'No NVIDIA GPU reported.'));
        }
        renderProcesses(snapshot.processes || []);
        summary.textContent = `${snapshot.process_total || 0} process(es)`;
    };

    search.onkeydown = event => {
        if (event.key === 'Enter') void load();
    };
    scope.onchange = () => void load();
    sort.onchange = () => void load();
    const toolbar = view.element('div', 'ra-toolbar');
    toolbar.append(scope, sort, search, view.button('Refresh', load), summary);
    view.content.replaceChildren(
        toolbar,
        host,
        gpus,
        view.splitPane(view.card('Processes', processes), view.card('Process context', detail)),
    );
    await load();
}
