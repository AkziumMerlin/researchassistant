export const researchAssistantServicePath = '/services/research-assistant';
export const ResearchAssistantService = Symbol('ResearchAssistantService');

export type ApiMethod = 'GET' | 'POST' | 'PUT' | 'DELETE';

export interface RemoteDesktopDescriptor {
    version: 1;
    mode: 'ssh';
    workspaceId: string;
    target: string;
    workspace: string;
    condaEnv?: string;
    remotePython?: string;
    plugins: string[];
    localPort: number;
    reconnect: boolean;
    sshOptions: string[];
}

export interface DesktopInitializeOptions {
    workspace?: string;
    python?: string;
    plugins?: string[];
}

export interface DesktopSidecarStatus {
    state: 'stopped' | 'starting' | 'running' | 'reconnecting' | 'failed';
    mode?: 'local' | 'ssh';
    workspace?: string;
    productVersion?: string;
    pid?: number;
    target?: string;
    detail?: string;
}

export interface ApiRequest {
    method?: ApiMethod;
    path: string;
    body?: unknown;
}

export interface ApiResponse<T = unknown> {
    status: number;
    body: T;
}

export interface ResearchAssistantService {
    start(options?: DesktopInitializeOptions): Promise<DesktopSidecarStatus>;
    status(): Promise<DesktopSidecarStatus>;
    request<T = unknown>(request: ApiRequest): Promise<ApiResponse<T>>;
    shutdown(): Promise<void>;
}
