import {
    FrontendApplicationContribution,
    WebSocketConnectionProvider,
    WidgetFactory,
    bindViewContribution,
} from '@theia/core/lib/browser';
import { ContainerModule } from '@theia/core/shared/inversify';

import {
    ResearchAssistantService,
    researchAssistantServicePath,
} from '../common/research-assistant-protocol';
import { ResearchAssistantContribution } from './research-assistant-contribution';
import { ResearchAssistantWidget, ResearchAssistantWidgetId } from './research-assistant-widget';

import './style/execution.css';
import './style/research-assistant.css';

export default new ContainerModule(bind => {
    bind(ResearchAssistantService).toDynamicValue(context =>
        WebSocketConnectionProvider.createProxy<ResearchAssistantService>(
            context.container,
            researchAssistantServicePath,
        ),
    ).inSingletonScope();

    bind(ResearchAssistantWidget).toSelf();
    bind(WidgetFactory).toDynamicValue(context => ({
        id: ResearchAssistantWidgetId,
        createWidget: () => context.container.get<ResearchAssistantWidget>(ResearchAssistantWidget),
    }));
    bindViewContribution(bind, ResearchAssistantContribution);
    bind(FrontendApplicationContribution).toService(ResearchAssistantContribution);
});
