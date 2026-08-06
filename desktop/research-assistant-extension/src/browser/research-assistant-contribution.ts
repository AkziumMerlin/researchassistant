import { Command, CommandRegistry } from '@theia/core';
import {
    AbstractViewContribution,
    FrontendApplicationContribution,
} from '@theia/core/lib/browser';
import { injectable } from '@theia/core/shared/inversify';

import { ResearchAssistantWidget, ResearchAssistantWidgetId } from './research-assistant-widget';

export namespace ResearchAssistantCommands {
    export const OPEN_ID = 'research-assistant.open';
    export const REFRESH: Command = {
        id: 'research-assistant.refresh',
        label: 'ResearchAssistant: Refresh Active View',
        category: 'ResearchAssistant',
    };
}

@injectable()
export class ResearchAssistantContribution
extends AbstractViewContribution<ResearchAssistantWidget>
implements FrontendApplicationContribution {
    constructor() {
        super({
            widgetId: ResearchAssistantWidgetId,
            widgetName: 'ResearchAssistant',
            defaultWidgetOptions: { area: 'main', rank: 500 },
            toggleCommandId: ResearchAssistantCommands.OPEN_ID,
            toggleKeybinding: 'ctrlcmd+shift+r',
        });
    }

    override registerCommands(commands: CommandRegistry): void {
        super.registerCommands(commands);
        commands.registerCommand(ResearchAssistantCommands.REFRESH, {
            execute: async () => {
                const widget = await this.openView({ activate: true });
                await widget.refresh();
            },
        });
    }

    async initializeLayout(): Promise<void> {
        await this.openView({ activate: false });
    }

    async onDidInitializeLayout(): Promise<void> {
        const widget = this.tryGetWidget();
        if (
            widget?.isAttached
            && this.shell.getAreaFor(widget) !== 'main'
        ) {
            await this.shell.addWidget(widget, { area: 'main' });
        }
    }
}
