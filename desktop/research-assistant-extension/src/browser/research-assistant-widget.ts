import { MessageService } from '@theia/core';
import { OpenerService, open } from '@theia/core/lib/browser';
import { BaseWidget } from '@theia/core/lib/browser/widgets/widget';
import { inject, injectable, postConstruct } from '@theia/core/shared/inversify';
import { WorkspaceService } from '@theia/workspace/lib/browser';

import {
    ApiResponse,
    ResearchAssistantService,
} from '../common/research-assistant-protocol';
import { renderArtifacts } from './tabs/artifacts-tab';
import { renderAssistant } from './tabs/assistant-tab';
import { renderExecution } from './tabs/execution-tab';
import { renderJobs } from './tabs/jobs-tab';
import { renderModels } from './tabs/models-tab';
import { renderPipeline } from './tabs/pipeline-tab';
import { renderProject } from './tabs/project-tab';
import { renderMonitor } from './tabs/monitor-tab';
import { renderNotebooks } from './tabs/notebooks-tab';
import { renderReports } from './tabs/reports-tab';
import { renderResearch } from './tabs/research-tab';
import { renderWorkbench } from './tabs/workbench-tab';
import { renderRuns } from './tabs/runs-tab';

export const ResearchAssistantWidgetId = 'research-assistant.workspace';

type TabId =
    | 'runs'
    | 'artifacts'
    | 'project'
    | 'jobs'
    | 'models'
    | 'reports'
    | 'notebooks'
    | 'execution'
    | 'pipeline'
    | 'workbench'
    | 'monitor'
    | 'research'
    | 'assistant';

@injectable()
export class ResearchAssistantWidget extends BaseWidget {
    @inject(ResearchAssistantService)
    protected readonly service: ResearchAssistantService;

    @inject(MessageService)
    public readonly messages: MessageService;

    @inject(WorkspaceService)
    protected readonly workspaceService: WorkspaceService;

    @inject(OpenerService)
    protected readonly openerService: OpenerService;

    protected activeTab: TabId = 'runs';
    public selectedRuns = new Set<string>();
    public selectedArtifacts = new Set<string>();
    protected tabHost: HTMLElement;
    public content: HTMLElement;
    protected status: HTMLElement;
    protected tabCleanup: (() => void | Promise<void>) | undefined;

    @postConstruct()
    protected init(): void {
        this.id = ResearchAssistantWidgetId;
        this.title.label = 'Research';
        this.title.caption = 'ResearchAssistant workspace';
        this.title.iconClass = 'codicon codicon-beaker';
        this.title.closable = true;
        this.addClass('ra-theia-workspace');
        this.node.tabIndex = 0;

        const header = this.element('header', 'ra-header');
        const heading = this.element('div');
        heading.append(
            this.element('span', 'ra-eyebrow', 'STUDIES · RUNS · MODELS · ARTIFACTS'),
            this.element('h2', undefined, 'ResearchAssistant'),
        );
        this.status = this.element('span', 'ra-sidecar-status', 'Starting backend…');
        const refresh = this.button('Refresh', () => this.refresh());
        header.append(heading, this.status, refresh);

        this.tabHost = this.element('nav', 'ra-tabs');
        const tabs: Array<[TabId, string, string]> = [
            ['runs', 'Runs', 'run-all'],
            ['artifacts', 'Artifacts', 'database'],
            ['project', 'Project', 'settings-gear'],
            ['jobs', 'Jobs', 'server-process'],
            ['models', 'Models', 'type-hierarchy-sub'],
            ['reports', 'Reports', 'graph'],
            ['notebooks', 'Notebooks', 'notebook'],
            ['execution', 'Execution', 'play-circle'],
            ['pipeline', 'Pipeline', 'type-hierarchy'],
            ['workbench', 'Workbench', 'tools'],
            ['monitor', 'Monitor', 'pulse'],
            ['research', 'Research', 'beaker'],
            ['assistant', 'Assistant', 'sparkle'],
        ];
        for (const [id, label, icon] of tabs) {
            const button = this.button(label, () => this.showTab(id), `ra-tab codicon codicon-${icon}`);
            button.dataset.tab = id;
            this.tabHost.append(button);
        }
        this.content = this.element('main', 'ra-content');
        this.node.append(header, this.tabHost, this.content);
        void this.start();
    }

    async refresh(): Promise<void> {
        await this.showTab(this.activeTab, true);
    }

    async showTab(tab: TabId, force = false): Promise<void> {
        if (!force && tab === this.activeTab && this.content.dataset.loaded === tab) {
            return;
        }
        if (this.tabCleanup) {
            await this.tabCleanup();
            this.tabCleanup = undefined;
        }
        this.activeTab = tab;
        for (const button of Array.from(this.tabHost.querySelectorAll<HTMLButtonElement>('[data-tab]'))) {
            button.classList.toggle('active', button.dataset.tab === tab);
        }
        this.content.dataset.loaded = '';
        this.content.replaceChildren(this.element('div', 'ra-loading', 'Loading…'));
        try {
            await {
                runs: () => renderRuns(this),
                artifacts: () => renderArtifacts(this),
                project: () => renderProject(this),
                jobs: () => renderJobs(this),
                models: () => renderModels(this),
                reports: () => renderReports(this),
                notebooks: () => renderNotebooks(this),
                execution: () => renderExecution(this),
                pipeline: () => renderPipeline(this),
                workbench: () => renderWorkbench(this),
                monitor: () => renderMonitor(this),
                research: () => renderResearch(this),
                assistant: () => renderAssistant(this),
            }[tab]();
            this.content.dataset.loaded = tab;
        } catch (error) {
            this.renderError(error);
        }
    }

    protected async start(): Promise<void> {
        try {
            const state = await this.service.start();
            const location = state.mode === 'ssh' && state.target ? ` · ${state.target}` : '';
            this.status.textContent = `${state.productVersion || 'development'} · ${state.state}${location}`;
            this.status.classList.toggle('error', state.state === 'failed');
            await this.showTab(this.activeTab, true);
        } catch (error) {
            this.status.textContent = 'Backend failed';
            this.status.classList.add('error');
            this.renderError(error);
        }
    }

    public setTabCleanup(cleanup: () => void | Promise<void>): void {
        this.tabCleanup = cleanup;
    }

    public async get<T = unknown>(path: string): Promise<T> {
        const response = await this.service.request<T>({ path });
        return response.body;
    }

    public async post<T = unknown>(path: string, body: unknown): Promise<T> {
        const response: ApiResponse<T> = await this.service.request<T>({ method: 'POST', path, body });
        return response.body;
    }

    public async put<T = unknown>(path: string, body: unknown): Promise<T> {
        const response: ApiResponse<T> = await this.service.request<T>({ method: 'PUT', path, body });
        return response.body;
    }

    public async remove<T = unknown>(path: string): Promise<T> {
        const response: ApiResponse<T> = await this.service.request<T>({ method: 'DELETE', path });
        return response.body;
    }

    public async openWorkspaceFile(path: string): Promise<void> {
        const roots = await this.workspaceService.roots;
        const root = roots[0];
        if (!root) {
            throw new Error('Open a workspace before opening ResearchAssistant files.');
        }
        await open(this.openerService, root.resource.resolve(path));
    }

    public safeClick(button: HTMLButtonElement, output: HTMLElement): void {
        const original = button.onclick;
        button.onclick = null;
        button.addEventListener('click', async event => {
            try {
                if (original) {
                    await original.call(button, event as PointerEvent);
                }
            } catch (error) {
                output.textContent = error instanceof Error ? error.message : String(error);
                output.classList.add('error');
            }
        });
    }

    protected renderError(error: unknown): void {
        const message = error instanceof Error ? error.message : String(error);
        this.content.replaceChildren(this.element('pre', 'ra-output error', message));
    }

    public element<K extends keyof HTMLElementTagNameMap>(
        tag: K,
        className?: string,
        text?: string,
        children: Node[] = [],
    ): HTMLElementTagNameMap[K] {
        const node = document.createElement(tag);
        if (className) {
            node.className = className;
        }
        if (text !== undefined) {
            node.textContent = text;
        }
        node.append(...children);
        return node;
    }

    public button(
        text: string,
        action: () => unknown | Promise<unknown>,
        className = '',
    ): HTMLButtonElement {
        const button = this.element('button', `theia-button ra-button ${className}`.trim(), text);
        button.type = 'button';
        button.onclick = () => {
            void Promise.resolve(action()).catch(error => {
                this.messages.error(error instanceof Error ? error.message : String(error));
            });
        };
        return button;
    }

    public input(placeholder: string, value = ''): HTMLInputElement {
        const input = this.element('input', 'theia-input');
        input.placeholder = placeholder;
        input.value = value;
        return input;
    }

    public output(text: string): HTMLPreElement {
        return this.element('pre', 'ra-output', text);
    }

    public row(nodes: Node[]): HTMLElement {
        return this.element('div', 'ra-row', undefined, nodes);
    }

    public card(title: string, ...children: Node[]): HTMLElement {
        const card = this.element('section', 'ra-card');
        card.append(this.element('h3', undefined, title), ...children);
        return card;
    }

    public splitPane(left: Node, right: Node, extra = ''): HTMLElement {
        return this.element('div', `ra-split ${extra}`.trim(), undefined, [left, right]);
    }

    public pretty(value: unknown): string {
        return JSON.stringify(value, null, 2);
    }

    public split(value: string): string[] {
        return value.split(/[\n,]/).map(item => item.trim()).filter(Boolean);
    }
}
