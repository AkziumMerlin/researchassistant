import type { ResearchAssistantWidget } from '../research-assistant-widget';

export type JsonObject = Record<string, unknown>;

export function jsonEditor(value: unknown, rows = 10): HTMLTextAreaElement {
    const area = document.createElement('textarea');
    area.className = 'ra-spec-editor';
    area.spellcheck = false;
    area.rows = rows;
    area.value = JSON.stringify(value, null, 2);
    return area;
}

export function textArea(placeholder: string, value = '', rows = 5): HTMLTextAreaElement {
    const area = document.createElement('textarea');
    area.placeholder = placeholder;
    area.value = value;
    area.rows = rows;
    return area;
}

export function parseObject(area: HTMLTextAreaElement, label = 'JSON'): JsonObject {
    let value: unknown;
    try {
        value = JSON.parse(area.value || '{}');
    } catch (error) {
        throw new Error(`${label} is not valid JSON: ${String(error)}`);
    }
    if (!value || typeof value !== 'object' || Array.isArray(value)) {
        throw new Error(`${label} must contain a JSON object.`);
    }
    return value as JsonObject;
}

export function parseArray(area: HTMLTextAreaElement, label = 'JSON'): unknown[] {
    let value: unknown;
    try {
        value = JSON.parse(area.value || '[]');
    } catch (error) {
        throw new Error(`${label} is not valid JSON: ${String(error)}`);
    }
    if (!Array.isArray(value)) {
        throw new Error(`${label} must contain a JSON array.`);
    }
    return value;
}

export function numberValue(input: HTMLInputElement, fallback: number): number {
    const value = Number(input.value);
    if (!Number.isFinite(value)) {
        throw new Error(`${input.placeholder || 'Numeric field'} must be a number.`);
    }
    return value || fallback;
}

export function field(
    view: ResearchAssistantWidget,
    label: string,
    control: HTMLElement,
    help?: string,
): HTMLLabelElement {
    const node = view.element('label', 'ra-field');
    node.append(view.element('span', 'ra-field-label', label), control);
    if (help) {
        node.append(view.element('small', 'ra-help', help));
    }
    return node;
}

export function select(
    view: ResearchAssistantWidget,
    values: readonly string[],
    selected?: string,
): HTMLSelectElement {
    const node = view.element('select', 'theia-select');
    for (const value of values) {
        const option = view.element('option', undefined, value || '—');
        option.value = value;
        node.append(option);
    }
    node.value = selected ?? values[0] ?? '';
    return node;
}

export async function runAction(
    view: ResearchAssistantWidget,
    output: HTMLElement,
    action: () => Promise<unknown>,
    after?: () => Promise<void> | void,
): Promise<unknown> {
    output.classList.remove('error');
    output.textContent = 'Working…';
    try {
        const result = await action();
        output.textContent = typeof result === 'string' ? result : view.pretty(result);
        await after?.();
        return result;
    } catch (error) {
        output.classList.add('error');
        output.textContent = error instanceof Error ? error.message : String(error);
        throw error;
    }
}

export function sectionTabs(
    view: ResearchAssistantWidget,
    sections: Array<{ id: string; label: string; node: HTMLElement }>,
): HTMLElement {
    const host = view.element('div', 'ra-section-tabs');
    const tabs = view.element('nav', 'ra-subtabs');
    const body = view.element('div', 'ra-section-body');
    const show = (id: string): void => {
        for (const button of Array.from(tabs.querySelectorAll<HTMLButtonElement>('[data-section]'))) {
            button.classList.toggle('active', button.dataset.section === id);
        }
        const section = sections.find(candidate => candidate.id === id) || sections[0];
        body.replaceChildren(section.node);
    };
    for (const section of sections) {
        const button = view.button(section.label, () => show(section.id), 'ra-subtab');
        button.dataset.section = section.id;
        tabs.append(button);
    }
    host.append(tabs, body);
    if (sections.length) show(sections[0].id);
    return host;
}

export function storageJson<T>(key: string, fallback: T): T {
    try {
        const raw = localStorage.getItem(key);
        return raw ? JSON.parse(raw) as T : fallback;
    } catch {
        return fallback;
    }
}

export function saveStorageJson(key: string, value: unknown): void {
    localStorage.setItem(key, JSON.stringify(value));
}
