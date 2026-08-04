import { ConnectionHandler, RpcConnectionHandler } from '@theia/core/lib/common/messaging';
import { BackendApplicationContribution } from '@theia/core/lib/node/backend-application';
import { ContainerModule } from '@theia/core/shared/inversify';

import {
    ResearchAssistantService,
    researchAssistantServicePath,
} from '../common/research-assistant-protocol';
import { ResearchAssistantBackendService } from './research-assistant-backend-service';

export default new ContainerModule(bind => {
    bind(ResearchAssistantBackendService).toSelf().inSingletonScope();
    bind(ResearchAssistantService).toService(ResearchAssistantBackendService);
    bind(BackendApplicationContribution).toService(ResearchAssistantBackendService);
    bind(ConnectionHandler).toDynamicValue(context =>
        new RpcConnectionHandler<ResearchAssistantService>(
            researchAssistantServicePath,
            () => context.container.get(ResearchAssistantBackendService),
        ),
    ).inSingletonScope();
});
