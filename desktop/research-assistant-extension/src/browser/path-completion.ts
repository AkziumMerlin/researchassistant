import { FrontendApplicationContribution } from '@theia/core/lib/browser';
import { inject, injectable } from '@theia/core/shared/inversify';
import { FileService } from '@theia/filesystem/lib/browser/file-service';
import { FileStat } from '@theia/filesystem/lib/common/files';
import { WorkspaceService } from '@theia/workspace/lib/browser';

const PATH_HINT = /(?:^|\b)(?:path|file|folder|directory|workspace|config|yaml|yml|json|toml|script|entrypoint|runner|checkpoint|weights|notebook|artifact|manifest|template|source|output|wrapper|cwd)(?:\b|$)/i;
const FILE_VALUE = /(?:^|[/\\])[^/\\]+\.(?:py|ya?ml|json|toml|ini|cfg|ipynb|pt|pth|ckpt|npz|npy|csv|tsv|parquet|h5|hdf5|tex|pdf|png|jpe?g|gif|webp|svg|txt|md)$/i;
const REMOTE_SCHEME = 'ra-remote';
const MAX_RESULTS = 80;

interface CompletionCandidate {
    value: string;
    name: string;
    directory: boolean;
}

interface CompletionRequest {
    directory: string;
    prefix: string;
    rawPrefix: string;
}

function longestCommonPrefix(values: string[]): string {
    if (!values.length) return '';
    let prefix = values[0];
    for (const value of values.slice(1)) {
        let index = 0;
        const limit = Math.min(prefix.length, value.length);
        while (index < limit && prefix[index] === value[index]) index += 1;
        prefix = prefix.slice(0, index);
        if (!prefix) break;
    }
    return prefix;
}

@injectable()
export class ResearchAssistantPathCompletionContribution implements FrontendApplicationContribution {
    @inject(FileService)
    protected readonly fileService: FileService;

    @inject(WorkspaceService)
    protected readonly workspaceService: WorkspaceService;

    protected active: PathCompletionSession | undefined;
    protected readonly onFocus = (event: FocusEvent): void => {
        const target = event.target;
        if (!(target instanceof HTMLInputElement)) return;
        if (!target.closest('.ra-theia-workspace')) return;
        if (!this.isPathInput(target)) return;
        this.activate(target);
    };

    onStart(): void {
        document.addEventListener('focusin', this.onFocus, true);
    }

    onStop(): void {
        document.removeEventListener('focusin', this.onFocus, true);
        this.active?.dispose();
        this.active = undefined;
    }

    protected activate(input: HTMLInputElement): void {
        if (this.active?.input === input) {
            this.active.refresh();
            return;
        }
        this.active?.dispose();
        this.active = new PathCompletionSession(
            input,
            this.fileService,
            this.workspaceService,
            () => {
                if (this.active?.input === input) this.active = undefined;
            },
        );
        this.active.refresh();
    }

    protected isPathInput(input: HTMLInputElement): boolean {
        if (!['', 'text', 'search'].includes(input.type)) return false;
        if (input.dataset.raPath === 'false') return false;
        if (input.dataset.raPath === 'true') return true;
        const cue = [
            input.placeholder,
            input.name,
            input.getAttribute('aria-label') || '',
            input.value,
        ].join(' ');
        return PATH_HINT.test(cue) || FILE_VALUE.test(input.value);
    }
}

class PathCompletionSession {
    readonly input: HTMLInputElement;
    protected readonly fileService: FileService;
    protected readonly workspaceService: WorkspaceService;
    protected readonly onDispose: () => void;
    protected readonly popup: HTMLDivElement;
    protected candidates: CompletionCandidate[] = [];
    protected selected = 0;
    protected generation = 0;
    protected timer: number | undefined;
    protected disposed = false;

    constructor(
        input: HTMLInputElement,
        fileService: FileService,
        workspaceService: WorkspaceService,
        onDispose: () => void,
    ) {
        this.input = input;
        this.fileService = fileService;
        this.workspaceService = workspaceService;
        this.onDispose = onDispose;
        this.popup = document.createElement('div');
        this.popup.className = 'ra-path-completion';
        this.popup.setAttribute('role', 'listbox');
        this.popup.hidden = true;
        document.body.append(this.popup);

        input.autocomplete = 'off';
        input.setAttribute('aria-autocomplete', 'list');
        input.addEventListener('input', this.onInput);
        input.addEventListener('keydown', this.onKeyDown);
        input.addEventListener('blur', this.onBlur);
        window.addEventListener('resize', this.position, true);
        window.addEventListener('scroll', this.position, true);
    }

    readonly refresh = (): void => {
        if (this.disposed) return;
        if (this.timer !== undefined) window.clearTimeout(this.timer);
        this.timer = window.setTimeout(() => {
            this.timer = undefined;
            void this.load();
        }, 60);
    };

    dispose(): void {
        if (this.disposed) return;
        this.disposed = true;
        if (this.timer !== undefined) window.clearTimeout(this.timer);
        this.input.removeEventListener('input', this.onInput);
        this.input.removeEventListener('keydown', this.onKeyDown);
        this.input.removeEventListener('blur', this.onBlur);
        window.removeEventListener('resize', this.position, true);
        window.removeEventListener('scroll', this.position, true);
        this.input.removeAttribute('aria-expanded');
        this.input.removeAttribute('aria-controls');
        this.input.removeAttribute('aria-activedescendant');
        this.popup.remove();
        this.onDispose();
    }

    protected readonly onInput = (): void => this.refresh();

    protected readonly onBlur = (): void => {
        window.setTimeout(() => {
            if (!this.popup.matches(':hover') && document.activeElement !== this.input) {
                this.hide();
            }
        }, 120);
    };

    protected readonly onKeyDown = (event: KeyboardEvent): void => {
        if (event.key === 'Escape') {
            this.hide();
            return;
        }
        if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
            if (!this.candidates.length) return;
            event.preventDefault();
            const delta = event.key === 'ArrowDown' ? 1 : -1;
            this.selected = (this.selected + delta + this.candidates.length) % this.candidates.length;
            this.render();
            return;
        }
        if (event.key === 'Enter' && !this.popup.hidden && this.candidates.length) {
            event.preventDefault();
            this.accept(this.candidates[this.selected]);
            return;
        }
        if (event.key === 'Tab' && !this.popup.hidden && this.candidates.length) {
            event.preventDefault();
            if (this.candidates.length === 1) {
                this.accept(this.candidates[0]);
                return;
            }
            const prefix = longestCommonPrefix(this.candidates.map(candidate => candidate.value));
            if (prefix.length > this.input.value.length) {
                this.setValue(prefix);
                this.refresh();
            }
        }
    };

    protected async load(): Promise<void> {
        const generation = ++this.generation;
        const request = this.parse(this.input.value);
        if (!request) {
            this.hide();
            return;
        }
        try {
            const roots = await this.workspaceService.roots;
            const root = roots.find(candidate => candidate.resource.scheme === REMOTE_SCHEME) ?? roots[0];
            if (!root) {
                this.hide();
                return;
            }
            const directory = request.directory
                ? root.resource.resolve(request.directory)
                : root.resource;
            const stat = await this.fileService.resolve(directory);
            if (generation !== this.generation || this.disposed) return;
            const children = stat.children ?? [];
            const includeHidden = request.prefix.startsWith('.');
            this.candidates = children
                .filter(child => includeHidden || !child.name.startsWith('.'))
                .filter(child => child.name.toLocaleLowerCase().startsWith(request.prefix.toLocaleLowerCase()))
                .filter(child => this.accepts(child))
                .sort((left, right) => {
                    if (left.isDirectory !== right.isDirectory) return left.isDirectory ? -1 : 1;
                    return left.name.localeCompare(right.name, undefined, { sensitivity: 'base' });
                })
                .slice(0, MAX_RESULTS)
                .map(child => ({
                    value: `${request.rawPrefix}${child.name}${child.isDirectory ? '/' : ''}`,
                    name: child.name,
                    directory: child.isDirectory,
                }));
            this.selected = Math.min(this.selected, Math.max(0, this.candidates.length - 1));
            this.render();
        } catch {
            if (generation === this.generation) this.hide();
        }
    }

    protected parse(value: string): CompletionRequest | undefined {
        const normalized = value.replaceAll('\\', '/');
        if (normalized.startsWith('/') || /^[A-Za-z]:\//.test(normalized)) return undefined;
        const segments = normalized.split('/');
        if (segments.includes('..')) return undefined;
        const slash = normalized.lastIndexOf('/');
        const rawPrefix = slash >= 0 ? normalized.slice(0, slash + 1) : '';
        const directory = rawPrefix.replace(/^\.\//, '');
        const prefix = slash >= 0 ? normalized.slice(slash + 1) : normalized;
        return { directory, prefix, rawPrefix };
    }

    protected accepts(child: FileStat): boolean {
        if (child.isDirectory) return true;
        const cue = `${this.input.placeholder} ${this.input.name}`.toLocaleLowerCase();
        if (/(?:directory|folder|cwd|workspace)/.test(cue)) return false;
        const extensions = this.extensions(cue);
        if (!extensions.length) return true;
        const lower = child.name.toLocaleLowerCase();
        return extensions.some(extension => lower.endsWith(extension));
    }

    protected extensions(cue: string): string[] {
        const explicit = this.input.dataset.raPathExtensions;
        if (explicit) {
            return explicit.split(',').map(value => value.trim().toLocaleLowerCase()).filter(Boolean);
        }
        if (/python|entrypoint|runner|script/.test(cue)) return ['.py'];
        if (/yaml|yml|config|wrapper/.test(cue)) return ['.yaml', '.yml'];
        if (/notebook/.test(cue)) return ['.ipynb'];
        if (/checkpoint|weights/.test(cue)) return ['.pt', '.pth', '.ckpt'];
        if (/json|manifest/.test(cue)) return ['.json'];
        return [];
    }

    protected render(): void {
        this.popup.replaceChildren();
        if (!this.candidates.length || document.activeElement !== this.input) {
            this.hide();
            return;
        }
        this.popup.id ||= `ra-path-completion-${Math.random().toString(36).slice(2)}`;
        this.input.setAttribute('aria-controls', this.popup.id);
        this.input.setAttribute('aria-expanded', 'true');
        for (const [index, candidate] of this.candidates.entries()) {
            const item = document.createElement('button');
            item.type = 'button';
            item.className = `ra-path-completion-item${index === this.selected ? ' selected' : ''}`;
            item.id = `${this.popup.id}-${index}`;
            item.setAttribute('role', 'option');
            item.setAttribute('aria-selected', String(index === this.selected));
            const icon = document.createElement('span');
            icon.className = `codicon codicon-${candidate.directory ? 'folder' : 'file'}`;
            const label = document.createElement('span');
            label.className = 'ra-path-completion-label';
            label.textContent = candidate.name;
            const suffix = document.createElement('span');
            suffix.className = 'ra-path-completion-kind';
            suffix.textContent = candidate.directory ? 'directory' : 'file';
            item.append(icon, label, suffix);
            item.addEventListener('mousemove', () => {
                if (this.selected !== index) {
                    this.selected = index;
                    this.render();
                }
            });
            item.addEventListener('mousedown', event => {
                event.preventDefault();
                this.accept(candidate);
            });
            this.popup.append(item);
        }
        this.input.setAttribute('aria-activedescendant', `${this.popup.id}-${this.selected}`);
        this.popup.hidden = false;
        this.position();
        this.popup.querySelector('.selected')?.scrollIntoView({ block: 'nearest' });
    }

    protected accept(candidate: CompletionCandidate): void {
        this.setValue(candidate.value);
        if (candidate.directory) {
            this.input.focus();
            this.refresh();
        } else {
            this.hide();
            this.input.focus();
        }
    }

    protected setValue(value: string): void {
        this.input.value = value;
        this.input.dispatchEvent(new Event('input', { bubbles: true }));
    }

    protected hide(): void {
        this.popup.hidden = true;
        this.input.setAttribute('aria-expanded', 'false');
        this.input.removeAttribute('aria-activedescendant');
    }

    protected readonly position = (): void => {
        if (this.popup.hidden || this.disposed) return;
        const rect = this.input.getBoundingClientRect();
        const viewportHeight = document.documentElement.clientHeight;
        const below = viewportHeight - rect.bottom;
        const maxHeight = Math.max(120, Math.min(360, below > 180 ? below - 8 : rect.top - 8));
        this.popup.style.left = `${Math.max(4, rect.left)}px`;
        this.popup.style.width = `${Math.max(240, rect.width)}px`;
        this.popup.style.maxHeight = `${maxHeight}px`;
        if (below > 180 || below >= rect.top) {
            this.popup.style.top = `${rect.bottom + 4}px`;
            this.popup.style.bottom = 'auto';
        } else {
            this.popup.style.top = 'auto';
            this.popup.style.bottom = `${viewportHeight - rect.top + 4}px`;
        }
    };
}
