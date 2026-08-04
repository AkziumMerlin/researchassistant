import type { ResearchAssistantWidget } from '../research-assistant-widget';

interface AssistantPlan {
    provider?: string;
    summary?: string;
    actions?: unknown[];
    [key: string]: unknown;
}

export async function renderAssistant(view: ResearchAssistantWidget): Promise<void> {
    const goal = document.createElement('textarea');
    goal.placeholder = 'Describe the research task. The assistant returns a typed, capability-bounded plan.';
    goal.value = 'Inspect selected runs and summarize their results.';
    const output = view.output('No plan generated.');
    let planValue: AssistantPlan | undefined;

    const request = (): Record<string, unknown> => ({
        goal: goal.value,
        run_ids: [...view.selectedRuns],
        artifact_ids: [...view.selectedArtifacts],
    });

    const plan = view.button('Generate typed plan', async () => {
        planValue = await view.post<AssistantPlan>('/api/workspace/assistant/plan', request());
        output.classList.remove('error');
        output.textContent = view.pretty(planValue);
    }, 'primary');
    const apply = view.button('Apply validated plan', async () => {
        if (!planValue) {
            throw new Error('Generate a plan first.');
        }
        output.classList.remove('error');
        output.textContent = view.pretty(await view.post('/api/workspace/assistant/apply', {
            request: request(),
            plan: planValue,
        }));
    });
    view.content.replaceChildren(
        view.card(
            'Typed research planner',
            goal,
            view.element('div', 'ra-actions', undefined, [plan, apply]),
            output,
        ),
    );
}
