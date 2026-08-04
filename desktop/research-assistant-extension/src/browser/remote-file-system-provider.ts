import {
    Disposable,
    Emitter,
    Event,
    URI,
} from '@theia/core';
import {
    FileService,
    FileServiceContribution,
} from '@theia/filesystem/lib/browser/file-service';
import {
    FileChange,
    FileChangeType,
    FileDeleteOptions,
    FileOverwriteOptions,
    FileSystemProvider,
    FileSystemProviderCapabilities,
    FileType,
    FileWriteOptions,
    Stat,
    WatchOptions,
} from '@theia/filesystem/lib/common/files';
import { inject, injectable } from '@theia/core/shared/inversify';

import { ResearchAssistantService } from '../common/research-assistant-protocol';

interface RemoteStat {
    path: string;
    type: 'file' | 'directory' | 'symlink' | 'unknown';
    ctime_ms: number;
    mtime_ms: number;
    size: number;
}

interface RemoteDirectory {
    entries: Array<{ name: string; type: RemoteStat['type'] }>;
}

interface RemoteRead {
    content_base64: string;
}

interface RemoteSnapshot {
    entries: Array<{
        path: string;
        type: RemoteStat['type'];
        mtime_ms: number;
        size: number;
    }>;
    truncated: boolean;
}

interface WatchState {
    references: number;
    timer: ReturnType<typeof setInterval>;
    resource: URI;
    recursive: boolean;
    snapshot: Map<string, string>;
    running: boolean;
}

const REMOTE_SCHEME = 'ra-remote';

@injectable()
export class ResearchAssistantRemoteFileSystemProvider implements FileSystemProvider {
    readonly capabilities = FileSystemProviderCapabilities.FileReadWrite
        | FileSystemProviderCapabilities.FileFolderCopy
        | FileSystemProviderCapabilities.PathCaseSensitive;
    readonly onDidChangeCapabilities = Event.None;
    protected readonly fileChangeEmitter = new Emitter<readonly FileChange[]>();
    readonly onDidChangeFile = this.fileChangeEmitter.event;
    readonly onFileWatchError = Event.None;

    @inject(ResearchAssistantService)
    protected readonly service: ResearchAssistantService;

    protected readonly watches = new Map<string, WatchState>();

    watch(resource: URI, opts: WatchOptions): Disposable {
        const key = `${resource.toString()}::${opts.recursive}`;
        const existing = this.watches.get(key);
        if (existing) {
            existing.references += 1;
            return Disposable.create(() => this.releaseWatch(key));
        }
        const state: WatchState = {
            references: 1,
            resource,
            recursive: opts.recursive,
            snapshot: new Map(),
            running: false,
            timer: setInterval(() => void this.pollWatch(key), 5000),
        };
        this.watches.set(key, state);
        void this.pollWatch(key, true);
        return Disposable.create(() => this.releaseWatch(key));
    }

    async stat(resource: URI): Promise<Stat> {
        const response = await this.service.request<RemoteStat>({
            path: `/api/desktop/files/stat?path=${encodeURIComponent(this.path(resource))}`,
        });
        return this.toStat(response.body);
    }

    async mkdir(resource: URI): Promise<void> {
        await this.service.request({
            method: 'POST',
            path: '/api/desktop/files/mkdir',
            body: { path: this.path(resource) },
        });
        this.emit(resource, FileChangeType.ADDED);
    }

    async readdir(resource: URI): Promise<[string, FileType][]> {
        const response = await this.service.request<RemoteDirectory>({
            path: `/api/desktop/files/readdir?path=${encodeURIComponent(this.path(resource))}`,
        });
        return response.body.entries.map(entry => [entry.name, this.toFileType(entry.type)]);
    }

    async delete(resource: URI, opts: FileDeleteOptions): Promise<void> {
        await this.service.request({
            method: 'POST',
            path: '/api/desktop/files/delete',
            body: { path: this.path(resource), recursive: opts.recursive },
        });
        this.emit(resource, FileChangeType.DELETED);
        this.emit(resource.parent, FileChangeType.UPDATED);
    }

    async rename(from: URI, to: URI, opts: FileOverwriteOptions): Promise<void> {
        await this.service.request({
            method: 'POST',
            path: '/api/desktop/files/rename',
            body: {
                source: this.path(from),
                target: this.path(to),
                overwrite: opts.overwrite,
            },
        });
        this.fileChangeEmitter.fire([
            { resource: from, type: FileChangeType.DELETED },
            { resource: to, type: FileChangeType.ADDED },
            { resource: from.parent, type: FileChangeType.UPDATED },
            { resource: to.parent, type: FileChangeType.UPDATED },
        ]);
    }

    async copy(from: URI, to: URI, opts: FileOverwriteOptions): Promise<void> {
        await this.service.request({
            method: 'POST',
            path: '/api/desktop/files/copy',
            body: {
                source: this.path(from),
                target: this.path(to),
                overwrite: opts.overwrite,
            },
        });
        this.emit(to, FileChangeType.ADDED);
        this.emit(to.parent, FileChangeType.UPDATED);
    }

    async readFile(resource: URI): Promise<Uint8Array> {
        const response = await this.service.request<RemoteRead>({
            path: `/api/desktop/files/read?path=${encodeURIComponent(this.path(resource))}`,
        });
        return this.decodeBase64(response.body.content_base64);
    }

    async writeFile(resource: URI, content: Uint8Array, opts: FileWriteOptions): Promise<void> {
        await this.service.request({
            method: 'POST',
            path: '/api/desktop/files/write',
            body: {
                path: this.path(resource),
                content_base64: this.encodeBase64(content),
                create: opts.create,
                overwrite: opts.overwrite,
            },
        });
        this.emit(resource, opts.create ? FileChangeType.ADDED : FileChangeType.UPDATED);
        this.emit(resource.parent, FileChangeType.UPDATED);
    }

    protected path(resource: URI): string {
        if (resource.scheme !== REMOTE_SCHEME) {
            throw new Error(`unsupported remote resource scheme: ${resource.scheme}`);
        }
        return resource.path.toString().replace(/^\/+/, '');
    }

    protected toStat(value: RemoteStat): Stat {
        return {
            type: this.toFileType(value.type),
            ctime: value.ctime_ms,
            mtime: value.mtime_ms,
            size: value.size,
        };
    }

    protected toFileType(value: RemoteStat['type']): FileType {
        switch (value) {
            case 'file':
                return FileType.File;
            case 'directory':
                return FileType.Directory;
            case 'symlink':
                return FileType.SymbolicLink;
            default:
                return FileType.Unknown;
        }
    }

    protected emit(resource: URI, type: FileChangeType): void {
        this.fileChangeEmitter.fire([{ resource, type }]);
    }

    protected encodeBase64(content: Uint8Array): string {
        const chunks: string[] = [];
        const size = 0x8000;
        for (let offset = 0; offset < content.length; offset += size) {
            chunks.push(String.fromCharCode(...content.subarray(offset, offset + size)));
        }
        return btoa(chunks.join(''));
    }

    protected decodeBase64(content: string): Uint8Array {
        const binary = atob(content);
        const result = new Uint8Array(binary.length);
        for (let index = 0; index < binary.length; index += 1) {
            result[index] = binary.charCodeAt(index);
        }
        return result;
    }

    protected releaseWatch(key: string): void {
        const state = this.watches.get(key);
        if (!state) {
            return;
        }
        state.references -= 1;
        if (state.references <= 0) {
            clearInterval(state.timer);
            this.watches.delete(key);
        }
    }

    protected async pollWatch(key: string, initialize = false): Promise<void> {
        const state = this.watches.get(key);
        if (!state || state.running) {
            return;
        }
        state.running = true;
        try {
            const response = await this.service.request<RemoteSnapshot>({
                method: 'POST',
                path: '/api/desktop/files/snapshot',
                body: {
                    path: this.path(state.resource),
                    // Poll only the watched directory. Recursive workspace scans are too
                    // expensive for large research repositories; local mutations emit
                    // precise events and explicit Refresh remains available.
                    recursive: false,
                    limit: 5000,
                },
            });
            if (response.body.truncated) {
                return;
            }
            const next = new Map<string, string>();
            for (const entry of response.body.entries) {
                next.set(entry.path, `${entry.type}:${entry.mtime_ms}:${entry.size}`);
            }
            if (!initialize && state.snapshot.size) {
                const changes: FileChange[] = [];
                for (const [path, signature] of next) {
                    const previous = state.snapshot.get(path);
                    if (previous === undefined) {
                        changes.push({ resource: this.uri(state.resource, path), type: FileChangeType.ADDED });
                    } else if (previous !== signature) {
                        changes.push({ resource: this.uri(state.resource, path), type: FileChangeType.UPDATED });
                    }
                }
                for (const path of state.snapshot.keys()) {
                    if (!next.has(path)) {
                        changes.push({ resource: this.uri(state.resource, path), type: FileChangeType.DELETED });
                    }
                }
                if (changes.length) {
                    this.fileChangeEmitter.fire(changes);
                }
            }
            state.snapshot = next;
        } catch {
            // A temporary SSH disconnect is handled by the service retry loop. A later
            // snapshot will reconcile the Explorer without invalidating the provider.
        } finally {
            state.running = false;
        }
    }

    protected uri(root: URI, relativePath: string): URI {
        return root.withPath(`/${relativePath}`);
    }
}

@injectable()
export class ResearchAssistantRemoteFileServiceContribution implements FileServiceContribution {
    @inject(ResearchAssistantRemoteFileSystemProvider)
    protected readonly provider: ResearchAssistantRemoteFileSystemProvider;

    registerFileSystemProviders(service: FileService): void {
        service.registerProvider(REMOTE_SCHEME, this.provider);
    }
}
