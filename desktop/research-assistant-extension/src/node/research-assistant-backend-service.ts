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
    RemoteDesktopDescriptor,
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
    connection_mode?: 'local' | 'ssh';
}

interface DesktopHealth {
    ok: boolean;
    version: string;
    workspace: string;
    connection_mode?: 'local' | 'ssh';
}

@injectable()
export class ResearchAssistantBackendService
implements ResearchAssistantService, BackendApplicationContribution {
    protected child: ChildProcessWithoutNullStreams | undefined;
    protected handshake: SidecarHandshake | undefined;
    protected endpoint: string | undefined;
    protected token: string | undefined;
    protected remote: RemoteDesktopDescriptor | undefined;
    protected current: DesktopSidecarStatus = { state: 'stopped' };
    protected startup: Promise<DesktopSidecarStatus> | undefined;
    protected stderrTail: string[] = [];
    protected stopping = false;
    protected readonly remoteSpecEnvironment = process.env.RA_REMOTE_SPEC;
    protected readonly remoteEndpointEnvironment = process.env.RA_REMOTE_ENDPOINT;
    protected readonly remoteTokenEnvironment = process.env.RA_REMOTE_TOKEN;

    initialize(): void {
        // Keep the bearer token in the Node service only. Terminals and other child
        // processes launched later must not inherit the desktop API credentials.
        delete process.env.RA_REMOTE_TOKEN;
        delete process.env.RA_REMOTE_ENDPOINT;
        delete process.env.RA_REMOTE_SPEC;
    }

    async start(options: DesktopInitializeOptions = {}): Promise<DesktopSidecarStatus> {
        if (this.current.state === 'running' && this.endpoint && this.token) {
            return this.current;
        }
        if (this.startup) {
            return this.startup;
        }
        this.startup = this.environmentRemote()
            ? this.startRemote()
            : this.startLocal(options);
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
        await this.start();
        const retries = this.remote?.reconnect ? 45 : 1;
        let lastError: unknown;
        for (let attempt = 0; attempt < retries; attempt += 1) {
            try {
                const response = await this.requestOnce<T>(request);
                if (this.remote && this.current.state === 'reconnecting') {
                    this.current = {
                        ...this.current,
                        state: 'running',
                        detail: undefined,
                    };
                }
                return response;
            } catch (error) {
                lastError = error;
                if (!this.remote || !this.isTransportError(error) || attempt + 1 >= retries) {
                    throw error;
                }
                this.current = {
                    ...this.current,
                    state: 'reconnecting',
                    detail: 'SSH transport is reconnecting',
                };
                await this.delay(Math.min(2000, 200 + attempt * 150));
            }
        }
        throw lastError;
    }

    async shutdown(): Promise<void> {
        this.stopping = true;
        const child = this.child;
        this.child = undefined;
        this.handshake = undefined;
        this.endpoint = undefined;
        this.token = undefined;
        this.remote = undefined;
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
        this.stopping = false;
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

    protected environmentRemote(): RemoteDesktopDescriptor | undefined {
        const raw = this.remoteSpecEnvironment;
        if (!raw) {
            return undefined;
        }
        try {
            const value = JSON.parse(raw) as RemoteDesktopDescriptor;
            if (value.version !== 1 || value.mode !== 'ssh' || !value.target || !value.workspace) {
                throw new Error('invalid remote descriptor');
            }
            return value;
        } catch (error) {
            throw new Error(`invalid RA_REMOTE_SPEC: ${String(error)}`);
        }
    }

    protected async startRemote(): Promise<DesktopSidecarStatus> {
        const remote = this.environmentRemote();
        const endpoint = this.remoteEndpointEnvironment;
        const token = this.remoteTokenEnvironment;
        if (!remote || !endpoint || !token) {
            throw new Error('remote desktop environment is incomplete');
        }
        this.remote = remote;
        this.endpoint = endpoint.replace(/\/$/, '');
        this.token = token;
        this.current = {
            state: 'starting',
            mode: 'ssh',
            workspace: remote.workspace,
            target: remote.target,
        };
        let lastError: unknown;
        for (let attempt = 0; attempt < 80; attempt += 1) {
            try {
                const health = await this.requestOnce<DesktopHealth>({
                    path: '/api/desktop/health',
                });
                this.current = {
                    state: 'running',
                    mode: 'ssh',
                    workspace: health.body.workspace || remote.workspace,
                    target: remote.target,
                    productVersion: health.body.version,
                };
                return this.current;
            } catch (error) {
                lastError = error;
                if (!this.isTransportError(error)) {
                    break;
                }
                await this.delay(250);
            }
        }
        this.current = {
            state: 'failed',
            mode: 'ssh',
            workspace: remote.workspace,
            target: remote.target,
            detail: String(lastError),
        };
        throw lastError;
    }

    protected async startLocal(options: DesktopInitializeOptions): Promise<DesktopSidecarStatus> {
        const workspace = options.workspace || process.env.RA_WORKSPACE || process.cwd();
        const python = options.python || process.env.RA_PYTHON || 'python3';
        const plugins = options.plugins || this.environmentPlugins();
        await this.shutdown();
        this.stopping = false;
        return this.startSidecar(workspace, python, plugins);
    }

    protected async requestOnce<T>(request: ApiRequest): Promise<ApiResponse<T>> {
        const endpoint = this.endpoint;
        const token = this.token;
        if (!endpoint || !token) {
            throw new Error(this.current.detail || 'ResearchAssistant sidecar did not start');
        }
        const response = await fetch(`${endpoint}${request.path}`, {
            method: request.method || 'GET',
            headers: {
                Authorization: `Bearer ${token}`,
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
        this.current = { state: 'starting', mode: 'local', workspace };
        const child = spawn(python, args, {
            env: process.env,
            stdio: ['pipe', 'pipe', 'pipe'],
        });
        this.child = child;
        child.stderr.setEncoding('utf8');
        child.stderr.on('data', chunk => this.captureStderr(String(chunk)));
        child.once('exit', (code, signal) => {
            if (this.child !== child || this.stopping) {
                return;
            }
            this.child = undefined;
            this.handshake = undefined;
            this.endpoint = undefined;
            this.token = undefined;
            const detail = `desktop sidecar exited (${signal || (code ?? 'unknown')})`;
            this.current = {
                state: code === 0 ? 'stopped' : 'failed',
                mode: 'local',
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
            this.endpoint = `http://${handshake.host}:${handshake.port}`;
            this.token = token;
            this.current = {
                state: 'running',
                mode: 'local',
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
                mode: 'local',
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

    protected isTransportError(error: unknown): boolean {
        return error instanceof TypeError
            || (error instanceof Error && /fetch failed|ECONN|socket|network/i.test(error.message));
    }

    protected delay(milliseconds: number): Promise<void> {
        return new Promise(resolve => setTimeout(resolve, milliseconds));
    }
}
