import { ChildProcessWithoutNullStreams, spawn } from 'node:child_process';
import { randomBytes } from 'node:crypto';
import * as readline from 'node:readline';

import { BackendApplicationContribution } from '@theia/core/lib/node/backend-application';
import { injectable } from '@theia/core/shared/inversify';

import {
    ApiRequest,
    ApiResponse,
    DesktopInitializeOptions,
    DesktopSidecarStatus,
    ResearchAssistantService,
} from '../common/research-assistant-protocol';

interface SidecarHandshake {
    protocol: string;
    version: number;
    product_version: string;
    host: string;
    port: number;
    token: string;
    workspace: string;
    pid: number;
}

@injectable()
export class ResearchAssistantBackendService
implements ResearchAssistantService, BackendApplicationContribution {
    protected child: ChildProcessWithoutNullStreams | undefined;
    protected handshake: SidecarHandshake | undefined;
    protected current: DesktopSidecarStatus = { state: 'stopped' };
    protected startup: Promise<DesktopSidecarStatus> | undefined;
    protected stderrTail: string[] = [];

    initialize(): void {
        // The sidecar is started lazily by the frontend after the workspace shell is ready.
    }

    async start(options: DesktopInitializeOptions = {}): Promise<DesktopSidecarStatus> {
        const workspace = options.workspace || process.env.RA_WORKSPACE || process.cwd();
        const python = options.python || process.env.RA_PYTHON || 'python3';
        const plugins = options.plugins || this.environmentPlugins();
        if (this.handshake?.workspace === workspace && this.child && !this.child.killed) {
            return this.current;
        }
        if (this.startup) {
            return this.startup;
        }
        await this.shutdown();
        this.startup = this.startSidecar(workspace, python, plugins);
        try {
            return await this.startup;
        } finally {
            this.startup = undefined;
        }
    }

    async status(): Promise<DesktopSidecarStatus> {
        return this.current;
    }

    async request<T = unknown>(request: ApiRequest): Promise<ApiResponse<T>> {
        if (!request.path.startsWith('/api/')) {
            throw new Error(`ResearchAssistant API path must start with /api/: ${request.path}`);
        }
        if (!this.handshake) {
            await this.start();
        }
        const handshake = this.handshake;
        if (!handshake) {
            throw new Error(this.current.detail || 'ResearchAssistant sidecar did not start');
        }
        const response = await fetch(`http://${handshake.host}:${handshake.port}${request.path}`, {
            method: request.method || 'GET',
            headers: {
                Authorization: `Bearer ${handshake.token}`,
                ...(request.body === undefined ? {} : { 'Content-Type': 'application/json' }),
            },
            body: request.body === undefined ? undefined : JSON.stringify(request.body),
        });
        const text = await response.text();
        let body: unknown = text;
        if (text) {
            try {
                body = JSON.parse(text);
            } catch {
                body = text;
            }
        } else {
            body = null;
        }
        if (!response.ok) {
            const detail = typeof body === 'object' && body && 'detail' in body
                ? String((body as { detail: unknown }).detail)
                : String(body || response.statusText);
            throw new Error(detail);
        }
        return { status: response.status, body: body as T };
    }

    async shutdown(): Promise<void> {
        const child = this.child;
        this.child = undefined;
        this.handshake = undefined;
        this.startup = undefined;
        if (child && !child.killed) {
            child.kill('SIGTERM');
            await new Promise<void>(resolve => {
                const timer = setTimeout(() => {
                    if (!child.killed) {
                        child.kill('SIGKILL');
                    }
                    resolve();
                }, 3000);
                child.once('exit', () => {
                    clearTimeout(timer);
                    resolve();
                });
            });
        }
        this.current = { state: 'stopped' };
    }

    async onStop(): Promise<void> {
        await this.shutdown();
    }

    protected environmentPlugins(): string[] {
        try {
            const value = JSON.parse(process.env.RA_PLUGINS || '[]');
            return Array.isArray(value) ? value.map(String) : [];
        } catch {
            return [];
        }
    }

    protected async startSidecar(
        workspace: string,
        python: string,
        plugins: string[],
    ): Promise<DesktopSidecarStatus> {
        const token = randomBytes(32).toString('base64url');
        const args = [
            '-m',
            'research_assistant.desktop_server',
            '--root',
            workspace,
            '--token',
            token,
        ];
        for (const plugin of plugins) {
            args.push('--plugin', plugin);
        }
        this.stderrTail = [];
        this.current = { state: 'starting', workspace };
        const child = spawn(python, args, {
            env: process.env,
            stdio: ['pipe', 'pipe', 'pipe'],
        });
        this.child = child;
        child.stderr.setEncoding('utf8');
        child.stderr.on('data', chunk => this.captureStderr(String(chunk)));
        child.once('exit', (code, signal) => {
            if (this.child !== child) {
                return;
            }
            this.child = undefined;
            this.handshake = undefined;
            const detail = `desktop sidecar exited (${signal || (code ?? 'unknown')})`;
            this.current = {
                state: code === 0 ? 'stopped' : 'failed',
                workspace,
                detail: this.stderrTail.length ? `${detail}: ${this.stderrTail.join('\n')}` : detail,
            };
        });

        try {
            const handshake = await this.readHandshake(child);
            if (handshake.protocol !== 'research-assistant/desktop-sidecar' || handshake.version !== 1) {
                throw new Error('unsupported ResearchAssistant desktop sidecar protocol');
            }
            if (handshake.token !== token) {
                throw new Error('desktop sidecar returned an invalid session token');
            }
            this.handshake = handshake;
            this.current = {
                state: 'running',
                workspace: handshake.workspace,
                productVersion: handshake.product_version,
                pid: handshake.pid,
            };
            return this.current;
        } catch (error) {
            if (!child.killed) {
                child.kill('SIGTERM');
            }
            const detail = error instanceof Error ? error.message : String(error);
            this.current = {
                state: 'failed',
                workspace,
                detail: this.stderrTail.length ? `${detail}: ${this.stderrTail.join('\n')}` : detail,
            };
            throw error;
        }
    }

    protected readHandshake(child: ChildProcessWithoutNullStreams): Promise<SidecarHandshake> {
        return new Promise((resolve, reject) => {
            const lines = readline.createInterface({ input: child.stdout });
            const timer = setTimeout(() => {
                lines.close();
                reject(new Error('timed out waiting for the ResearchAssistant sidecar'));
            }, 20000);
            const fail = (error: Error): void => {
                clearTimeout(timer);
                lines.close();
                reject(error);
            };
            child.once('error', fail);
            child.once('exit', code => fail(new Error(`desktop sidecar exited before startup (${code})`)));
            lines.once('line', line => {
                clearTimeout(timer);
                try {
                    resolve(JSON.parse(line) as SidecarHandshake);
                } catch (error) {
                    fail(new Error(`invalid desktop sidecar handshake: ${String(error)}`));
                } finally {
                    lines.close();
                }
            });
        });
    }

    protected captureStderr(chunk: string): void {
        this.stderrTail.push(...chunk.split(/\r?\n/).filter(Boolean));
        if (this.stderrTail.length > 40) {
            this.stderrTail.splice(0, this.stderrTail.length - 40);
        }
    }
}
