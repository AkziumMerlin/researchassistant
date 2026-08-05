import {
    FrontendApplicationContribution,
    WebSocketConnectionProvider,
    WidgetFactory,
    bindViewContribution,
} from '@theia/core/lib/browser';
import { ContainerModule } from '@theia/core/shared/inversify';
import { FileServiceContribution } from '@theia/filesystem/lib/browser/file-service';
import { WorkspaceService } from '@theia/workspace/lib/browser';

import {
    ResearchAssistantService,
    researchAssistantServicePath,
} from '../common/research-assistant-protocol';
import { ResearchAssistantContribution } from './research-assistant-contribution';
import { ResearchAssistantWidget, ResearchAssistantWidgetId } from './research-assistant-widget';
import {
    ResearchAssistantRemoteFileServiceContribution,
    ResearchAssistantRemoteFileSystemProvider,
} from './remote-file-system-provider';
import { ResearchAssistantWorkspaceService } from './remote-workspace-service';

import './style/execution.css';
import './style/research-assistant.css';
import './style/sci-fi-theme.css';

export default new ContainerModule((bind, _, __, rebind) => {
    bind(ResearchAssistantService).toDynamicValue(context =>
        WebSocketConnectionProvider.createProxy<ResearchAssistantService>(
            context.container,
            researchAssistantServicePath,
        ),
    ).inSingletonScope();

    bind(ResearchAssistantRemoteFileSystemProvider).toSelf().inSingletonScope();
    bind(ResearchAssistantRemoteFileServiceContribution).toSelf().inSingletonScope();
    bind(FileServiceContribution).toService(ResearchAssistantRemoteFileServiceContribution);

    bind(ResearchAssistantWorkspaceService).toSelf().inSingletonScope();
    rebind(WorkspaceService).toService(ResearchAssistantWorkspaceService);

    bind(ResearchAssistantWidget).toSelf();
    bind(WidgetFactory).toDynamicValue(context => ({
        id: ResearchAssistantWidgetId,
        createWidget: () => context.container.get<ResearchAssistantWidget>(ResearchAssistantWidget),
    }));
    bindViewContribution(bind, ResearchAssistantContribution);
    bind(FrontendApplicationContribution).toService(ResearchAssistantContribution);
});
