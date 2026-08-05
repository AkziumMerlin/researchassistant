import { URI } from '@theia/core';
import { injectable } from '@theia/core/shared/inversify';
import { FileStat } from '@theia/filesystem/lib/common/files';
import { WorkspaceData, WorkspaceService } from '@theia/workspace/lib/browser';
import * as jsoncparser from 'jsonc-parser';

const REMOTE_SCHEME = 'ra-remote';

/**
 * Preserves ResearchAssistant virtual roots in mixed local/remote workspaces.
 *
 * Theia 1.73 assumes every workspace folder is a local file URI in both
 * WorkspaceData.transformToAbsolute and transformToRelative. That breaks a
 * generated `ra-remote://` root as soon as the user adds or removes a local
 * folder: the normal spliceRoots path rewrites the remote URI as a local path.
 * Keep non-file URIs unchanged while applying Theia-compatible relative-path
 * handling to ordinary local folders.
 */
@injectable()
export class ResearchAssistantWorkspaceService extends WorkspaceService {
    protected override async computeRoots(): Promise<FileStat[]> {
        const roots: FileStat[] = [];
        if (!this._workspace) {
            return roots;
        }
        if (this._workspace.isDirectory) {
            return [this._workspace];
        }

        const workspaceData = await this.getWorkspaceDataFromFile();
        if (!workspaceData) {
            return roots;
        }
        for (const folder of workspaceData.folders) {
            const resource = new URI(folder.path).normalizePath();
            const resolved = await this.toValidRoot(resource);
            const root = resolved ?? FileStat.dir(resource);
            const configuredName = typeof folder.name === 'string' ? folder.name.trim() : '';
            if (configuredName) {
                roots.push({ ...root, name: configuredName });
            } else if (resource.scheme === REMOTE_SCHEME) {
                roots.push({ ...root, name: resource.authority || 'Remote workspace' });
            } else {
                roots.push(root);
            }
        }
        return roots;
    }

    protected override async getWorkspaceDataFromFile(): Promise<WorkspaceData | undefined> {
        if (!this._workspace || !await this.fileService.exists(this._workspace.resource)) {
            return undefined;
        }
        if (this._workspace.isDirectory) {
            return {
                folders: [{ path: this._workspace.resource.toString() }],
            };
        }
        if (!this.isWorkspaceFile(this._workspace)) {
            this.logger.warn(`Not a valid workspace file: ${this.labelProvider.getLongName(this._workspace)}`);
            return undefined;
        }

        const data = await this.readWorkspaceData(this._workspace);
        if (!data) {
            this.logger.error(
                `Unable to retrieve workspace data from the file: '${this.labelProvider.getLongName(this._workspace)}'. `
                + 'Please check if the file is corrupted.',
            );
            return undefined;
        }
        return this.transformWorkspaceDataToAbsolute(data, this._workspace);
    }

    protected override async writeWorkspaceFile(
        workspaceFile: FileStat | undefined,
        workspaceData: WorkspaceData,
    ): Promise<FileStat | undefined> {
        if (!workspaceFile) {
            return undefined;
        }

        const previousData = await this.readWorkspaceData(workspaceFile);
        const previousAbsolute = previousData
            ? this.transformWorkspaceDataToAbsolute(previousData, workspaceFile)
            : undefined;
        const previousNames = new Map<string, string>();
        for (const folder of previousAbsolute?.folders ?? []) {
            if (typeof folder.name === 'string' && folder.name.trim()) {
                previousNames.set(this.folderKey(folder.path), folder.name.trim());
            }
        }

        const folders = workspaceData.folders.map(folder => {
            const name = typeof folder.name === 'string' && folder.name.trim()
                ? folder.name.trim()
                : previousNames.get(this.folderKey(folder.path));
            const path = this.transformFolderToPortablePath(folder.path, workspaceFile);
            return name ? { path, name } : { path };
        });
        const portableData: WorkspaceData = Object.assign({}, workspaceData, { folders });
        await this.fileService.write(
            workspaceFile.resource,
            `${JSON.stringify(portableData, undefined, 2)}\n`,
        );
        return this.fileService.resolve(workspaceFile.resource);
    }

    protected async readWorkspaceData(workspaceFile: FileStat): Promise<WorkspaceData | undefined> {
        try {
            const content = await this.fileService.read(workspaceFile.resource);
            const data = jsoncparser.parse(content.value) as unknown;
            return WorkspaceData.is(data) ? data : undefined;
        } catch {
            return undefined;
        }
    }

    protected transformWorkspaceDataToAbsolute(
        data: WorkspaceData,
        workspaceFile: FileStat,
    ): WorkspaceData {
        const folders = data.folders.flatMap(folder => {
            const path = this.transformFolderToAbsolutePath(folder.path, workspaceFile);
            return path ? [{ ...folder, path }] : [];
        });
        return Object.assign({}, data, { folders });
    }

    protected transformFolderToAbsolutePath(path: string, workspaceFile: FileStat): string | undefined {
        const resource = new URI(path);

        // Absolute URI values are already fully qualified. In particular, a local
        // folder outside the cached workspace directory is serialized as
        // `file:///...`; resolving that string as a relative path produces a bogus
        // `.../file:/...` location and an apparently empty Navigator root.
        if (resource.scheme) {
            return resource.normalizePath().toString();
        }
        if (this.isAbsoluteFileSystemPath(path)) {
            return URI.fromFilePath(path).normalizePath().toString();
        }

        const absolute = workspaceFile.resource
            .withScheme('file')
            .parent
            .resolveToAbsolute(path);
        return absolute?.normalizePath().toString();
    }

    protected transformFolderToPortablePath(path: string, workspaceFile: FileStat): string {
        if (this.isExternalWorkspaceUri(path)) {
            return new URI(path).normalizePath().toString();
        }

        const resource = new URI(path);
        const folderUri = resource.scheme === 'file'
            ? resource.normalizePath()
            : this.isAbsoluteFileSystemPath(path)
                ? URI.fromFilePath(path).normalizePath()
                : workspaceFile.resource.withScheme('file').parent.resolveToAbsolute(path)?.normalizePath();
        if (!folderUri) {
            return path;
        }

        const workspaceParent = workspaceFile.resource.withScheme('file').parent;
        return workspaceParent.relative(folderUri)?.toString() ?? folderUri.toString();
    }

    protected folderKey(path: string): string {
        return new URI(path).normalizePath().toString();
    }

    protected isExternalWorkspaceUri(path: string): boolean {
        if (!/^[A-Za-z][A-Za-z0-9+.-]*:\/\//.test(path)) {
            return false;
        }
        return new URI(path).scheme !== 'file';
    }

    protected isAbsoluteFileSystemPath(path: string): boolean {
        return path.startsWith('/') || /^[A-Za-z]:[\\/]/.test(path);
    }
}
