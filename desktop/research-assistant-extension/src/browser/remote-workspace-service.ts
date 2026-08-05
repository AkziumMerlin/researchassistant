import { URI } from '@theia/core';
import { injectable } from '@theia/core/shared/inversify';
import { FileStat } from '@theia/filesystem/lib/common/files';
import { WorkspaceService } from '@theia/workspace/lib/browser';

const REMOTE_SCHEME = 'ra-remote';

interface WorkspaceFolderEntry {
    path?: unknown;
    name?: unknown;
}

interface WorkspaceDocument {
    folders?: unknown;
}

/**
 * Preserves ResearchAssistant virtual roots when Theia reads a workspace file.
 *
 * Theia 1.73 converts every `folders[].path` entry to the `file` scheme in
 * WorkspaceData.transformToAbsolute. That is correct for normal workspace
 * files, but it turns `ra-remote://...` into a local path and leaves Explorer
 * pointed at an empty generated directory. Handle only ResearchAssistant
 * remote roots here and delegate all ordinary workspaces to Theia unchanged.
 */
@injectable()
export class ResearchAssistantWorkspaceService extends WorkspaceService {
    protected override async computeRoots(): Promise<FileStat[]> {
        const remoteRoots = await this.computeRemoteRoots();
        return remoteRoots ?? super.computeRoots();
    }

    protected async computeRemoteRoots(): Promise<FileStat[] | undefined> {
        if (!this._workspace || this._workspace.isDirectory || !this.isWorkspaceFile(this._workspace)) {
            return undefined;
        }

        let document: WorkspaceDocument;
        try {
            const workspaceFile = await this.fileService.read(this._workspace.resource);
            document = JSON.parse(workspaceFile.value) as WorkspaceDocument;
        } catch {
            return undefined;
        }
        if (!Array.isArray(document.folders)) {
            return undefined;
        }

        const folders = document.folders.filter(
            (value): value is WorkspaceFolderEntry => typeof value === 'object' && value !== null,
        );
        if (!folders.some(folder => this.isRemotePath(folder.path))) {
            return undefined;
        }

        const roots: FileStat[] = [];
        for (const folder of folders) {
            if (!this.isRemotePath(folder.path)) {
                continue;
            }
            const resource = new URI(folder.path).normalizePath();
            const resolved = await this.toValidRoot(resource);
            const root = resolved ?? FileStat.dir(resource);
            const name = typeof folder.name === 'string' && folder.name.trim()
                ? folder.name.trim()
                : resource.authority || 'Remote workspace';
            roots.push({ ...root, name });
        }
        return roots;
    }

    protected isRemotePath(value: unknown): value is string {
        return typeof value === 'string' && new URI(value).scheme === REMOTE_SCHEME;
    }
}
