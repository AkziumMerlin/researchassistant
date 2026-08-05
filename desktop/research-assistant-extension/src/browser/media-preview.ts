import {
    LabelProvider,
    NavigatableWidgetOpenHandler,
} from '@theia/core/lib/browser';
import {
    Navigatable,
} from '@theia/core/lib/browser/navigatable';
import { BaseWidget } from '@theia/core/lib/browser/widgets/widget';
import URI from '@theia/core/lib/common/uri';
import { FileService } from '@theia/filesystem/lib/browser/file-service';
import { inject, injectable, postConstruct } from '@theia/core/shared/inversify';

export const ResearchAssistantMediaPreviewId = 'research-assistant.media-preview';

const MAX_PREVIEW_BYTES = 128 * 1024 * 1024;

const MEDIA_TYPES: Readonly<Record<string, string>> = {
    '.pdf': 'application/pdf',
    '.png': 'image/png',
    '.apng': 'image/apng',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.jfif': 'image/jpeg',
    '.gif': 'image/gif',
    '.webp': 'image/webp',
    '.avif': 'image/avif',
    '.bmp': 'image/bmp',
    '.svg': 'image/svg+xml',
    '.ico': 'image/x-icon',
};

function extension(uri: URI): string {
    const name = uri.path.base.toLocaleLowerCase();
    const separator = name.lastIndexOf('.');
    return separator >= 0 ? name.slice(separator) : '';
}

function mediaType(uri: URI): string | undefined {
    return MEDIA_TYPES[extension(uri)];
}

function resourceHash(value: string): string {
    let hash = 2166136261;
    for (let index = 0; index < value.length; index += 1) {
        hash ^= value.charCodeAt(index);
        hash = Math.imul(hash, 16777619);
    }
    return (hash >>> 0).toString(36);
}

function formatBytes(size: number): string {
    if (size < 1024) {
        return `${size} B`;
    }
    const units = ['KiB', 'MiB', 'GiB'];
    let value = size / 1024;
    let unit = units[0];
    for (let index = 1; index < units.length && value >= 1024; index += 1) {
        value /= 1024;
        unit = units[index];
    }
    return `${value >= 10 ? value.toFixed(1) : value.toFixed(2)} ${unit}`;
}

@injectable()
export class ResearchAssistantMediaPreviewWidget extends BaseWidget implements Navigatable {
    @inject(FileService)
    protected readonly fileService: FileService;

    @inject(LabelProvider)
    protected readonly labelProvider: LabelProvider;

    protected resourceUri: URI | undefined;
    protected objectUrl: string | undefined;
    protected currentImage: HTMLImageElement | undefined;
    protected loadGeneration = 0;

    protected toolbar: HTMLElement;
    protected imageControls: HTMLElement;
    protected stage: HTMLElement;
    protected metadata: HTMLElement;
    protected zoomLabel: HTMLElement;
    protected fitButton: HTMLButtonElement;
    protected checkerboardButton: HTMLButtonElement;

    protected zoom = 1;
    protected rotation = 0;
    protected fitToView = true;
    protected checkerboard = true;

    @postConstruct()
    protected init(): void {
        this.title.closable = true;
        this.addClass('ra-media-preview');
        this.node.tabIndex = 0;

        this.toolbar = document.createElement('div');
        this.toolbar.className = 'ra-media-preview-toolbar';

        this.imageControls = document.createElement('div');
        this.imageControls.className = 'ra-media-preview-controls';
        this.imageControls.append(
            this.button('zoom-out', 'Zoom out', () => this.zoomBy(0.8)),
        );
        this.zoomLabel = document.createElement('span');
        this.zoomLabel.className = 'ra-media-preview-zoom';
        this.zoomLabel.textContent = 'Fit';
        this.imageControls.append(this.zoomLabel);
        this.imageControls.append(
            this.button('zoom-in', 'Zoom in', () => this.zoomBy(1.25)),
        );
        this.fitButton = this.button('screen-full', 'Fit image to view', () => {
            this.fitToView = !this.fitToView;
            this.applyImageTransform();
        });
        this.imageControls.append(
            this.fitButton,
            this.button('discard', 'Rotate left', () => this.rotateBy(-90)),
            this.button('redo', 'Rotate right', () => this.rotateBy(90)),
        );
        this.checkerboardButton = this.button('symbol-color', 'Toggle transparency grid', () => {
            this.checkerboard = !this.checkerboard;
            this.stage.classList.toggle('ra-media-preview-checkerboard', this.checkerboard);
            this.checkerboardButton.classList.toggle('active', this.checkerboard);
        });
        this.checkerboardButton.classList.add('active');
        this.imageControls.append(this.checkerboardButton);

        this.metadata = document.createElement('span');
        this.metadata.className = 'ra-media-preview-metadata';
        this.metadata.textContent = 'No file loaded';

        const reload = this.button('refresh', 'Reload preview', () => void this.reload());
        reload.classList.add('ra-media-preview-reload');

        this.toolbar.append(this.imageControls, this.metadata, reload);

        this.stage = document.createElement('div');
        this.stage.className = 'ra-media-preview-stage ra-media-preview-checkerboard';
        this.stage.addEventListener('wheel', event => {
            if (!event.ctrlKey || !this.currentImage) {
                return;
            }
            event.preventDefault();
            this.zoomBy(event.deltaY < 0 ? 1.1 : 1 / 1.1);
        }, { passive: false });

        this.node.append(this.toolbar, this.stage);
    }

    async setResource(uri: URI): Promise<void> {
        this.resourceUri = uri;
        this.id = `${ResearchAssistantMediaPreviewId}:${resourceHash(uri.toString())}`;
        this.title.label = this.labelProvider.getName(uri) || uri.path.base;
        this.title.caption = uri.toString();
        this.title.iconClass = mediaType(uri) === 'application/pdf'
            ? 'codicon codicon-file-pdf'
            : 'codicon codicon-file-media';
        await this.reload();
    }

    getResourceUri(): URI | undefined {
        return this.resourceUri;
    }

    createMoveToUri(resourceUri: URI): URI | undefined {
        return resourceUri;
    }

    override dispose(): void {
        this.revokeObjectUrl();
        super.dispose();
    }

    protected async reload(): Promise<void> {
        const uri = this.resourceUri;
        const mime = uri && mediaType(uri);
        if (!uri || !mime) {
            this.showError('Unsupported preview resource.');
            return;
        }

        const generation = ++this.loadGeneration;
        this.currentImage = undefined;
        this.imageControls.hidden = true;
        this.metadata.textContent = 'Loading…';
        this.stage.replaceChildren(this.loadingNode());

        try {
            const content = await this.fileService.readFile(uri, {
                limits: {
                    size: MAX_PREVIEW_BYTES,
                    memory: MAX_PREVIEW_BYTES,
                },
            });
            if (generation !== this.loadGeneration || this.isDisposed) {
                return;
            }

            const source = content.value.buffer;
            const bytes = new Uint8Array(source.byteLength);
            bytes.set(source);
            const url = URL.createObjectURL(new Blob([bytes.buffer], { type: mime }));
            this.replaceObjectUrl(url);
            this.metadata.textContent = formatBytes(content.size);

            if (mime === 'application/pdf') {
                this.renderPdf(url, uri);
            } else {
                this.renderImage(url, uri, content.size);
            }
        } catch (error) {
            if (generation !== this.loadGeneration || this.isDisposed) {
                return;
            }
            const detail = error instanceof Error ? error.message : String(error);
            this.showError(detail);
        }
    }

    protected renderPdf(url: string, uri: URI): void {
        this.imageControls.hidden = true;
        this.stage.classList.remove('ra-media-preview-checkerboard');

        const frame = document.createElement('iframe');
        frame.className = 'ra-media-preview-pdf';
        frame.title = `PDF preview: ${this.labelProvider.getName(uri)}`;
        frame.src = `${url}#toolbar=1&navpanes=0&view=FitH`;
        frame.setAttribute('allowfullscreen', 'true');
        this.stage.replaceChildren(frame);
    }

    protected renderImage(url: string, uri: URI, size: number): void {
        this.imageControls.hidden = false;
        this.stage.classList.toggle('ra-media-preview-checkerboard', this.checkerboard);
        this.zoom = 1;
        this.rotation = 0;
        this.fitToView = true;

        const image = document.createElement('img');
        image.className = 'ra-media-preview-image';
        image.alt = this.labelProvider.getName(uri);
        image.draggable = false;
        image.src = url;
        image.addEventListener('load', () => {
            if (this.currentImage !== image) {
                return;
            }
            this.metadata.textContent = `${image.naturalWidth} × ${image.naturalHeight} · ${formatBytes(size)}`;
            this.applyImageTransform();
        });
        image.addEventListener('error', () => {
            if (this.currentImage === image) {
                this.showError('The image decoder could not render this file.');
            }
        });
        this.currentImage = image;
        this.stage.replaceChildren(image);
        this.applyImageTransform();
    }

    protected zoomBy(multiplier: number): void {
        if (!this.currentImage) {
            return;
        }
        this.fitToView = false;
        this.zoom = Math.min(16, Math.max(0.05, this.zoom * multiplier));
        this.applyImageTransform();
    }

    protected rotateBy(degrees: number): void {
        if (!this.currentImage) {
            return;
        }
        this.rotation = (this.rotation + degrees + 360) % 360;
        this.applyImageTransform();
    }

    protected applyImageTransform(): void {
        const image = this.currentImage;
        if (!image) {
            return;
        }
        this.fitButton.classList.toggle('active', this.fitToView);
        if (this.fitToView) {
            image.style.width = 'auto';
            image.style.height = 'auto';
            image.style.maxWidth = '100%';
            image.style.maxHeight = '100%';
            this.zoomLabel.textContent = 'Fit';
        } else {
            const naturalWidth = image.naturalWidth || image.width || 1;
            const naturalHeight = image.naturalHeight || image.height || 1;
            image.style.width = `${Math.max(1, Math.round(naturalWidth * this.zoom))}px`;
            image.style.height = `${Math.max(1, Math.round(naturalHeight * this.zoom))}px`;
            image.style.maxWidth = 'none';
            image.style.maxHeight = 'none';
            this.zoomLabel.textContent = `${Math.round(this.zoom * 100)}%`;
        }
        image.style.transform = `rotate(${this.rotation}deg)`;
    }

    protected button(icon: string, title: string, action: () => void): HTMLButtonElement {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = `ra-media-preview-button codicon codicon-${icon}`;
        button.title = title;
        button.setAttribute('aria-label', title);
        button.addEventListener('click', action);
        return button;
    }

    protected loadingNode(): HTMLElement {
        const node = document.createElement('div');
        node.className = 'ra-media-preview-message';
        node.append(
            Object.assign(document.createElement('span'), {
                className: 'codicon codicon-loading codicon-modifier-spin',
            }),
            document.createTextNode('Loading preview…'),
        );
        return node;
    }

    protected showError(message: string): void {
        this.currentImage = undefined;
        this.imageControls.hidden = true;
        this.metadata.textContent = 'Preview unavailable';
        const node = document.createElement('div');
        node.className = 'ra-media-preview-message ra-media-preview-error';
        const icon = document.createElement('span');
        icon.className = 'codicon codicon-error';
        const text = document.createElement('span');
        text.textContent = message;
        node.append(icon, text);
        this.stage.replaceChildren(node);
    }

    protected replaceObjectUrl(url: string): void {
        this.revokeObjectUrl();
        this.objectUrl = url;
    }

    protected revokeObjectUrl(): void {
        if (this.objectUrl) {
            URL.revokeObjectURL(this.objectUrl);
            this.objectUrl = undefined;
        }
    }
}

@injectable()
export class ResearchAssistantMediaPreviewOpenHandler
extends NavigatableWidgetOpenHandler<ResearchAssistantMediaPreviewWidget> {
    readonly id = ResearchAssistantMediaPreviewId;

    @inject(FileService)
    protected readonly fileService: FileService;

    async canHandle(uri: URI): Promise<number> {
        if (!mediaType(uri)) {
            return 0;
        }
        try {
            const stat = await this.fileService.resolve(uri);
            return stat.isFile ? 900 : 0;
        } catch {
            return 0;
        }
    }
}
