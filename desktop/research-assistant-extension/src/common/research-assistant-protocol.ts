export const researchAssistantServicePath = '/services/research-assistant';
export const ResearchAssistantService = Symbol('ResearchAssistantService');

export type ApiMethod = 'GET' | 'POST' | 'PUT' | 'DELETE';

export interface DesktopInitializeOptions {
    workspace?: string;
    python?: string;
    plugins?: string[];
}

export interface DesktopSidecarStatus {
    state: 'stopped' | 'starting' | 'running' | 'failed';
    workspace?: string;
    productVersion?: string;
    pid?: number;
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
