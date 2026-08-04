import type { ResearchAssistantWidget } from '../research-assistant-widget';

export async function renderAssistant(view: ResearchAssistantWidget): Promise<void> {
    const goal = document.createElement('textarea');
    goal.placeholder = 'Describe the research task. The assistant returns a typed, capability-bounded plan.';
    goal.value = 'Inspect selected runs and summarize their results.';
    const output = view.output('No plan generated.');
    const plan = view.button('Generate typed plan', async () => {
        output.textContent = view.pretty(await view.post('/api/workspace/assistant/plan', {
            goal: goal.value,
            run_ids: [...view.selectedRuns],
            artifact_ids: [...view.selectedArtifacts],
        }));
    }, 'primary');
    view.safeClick(plan, output);
    view.content.replaceChildren(view.card('Typed research planner', goal, plan, output));
}
