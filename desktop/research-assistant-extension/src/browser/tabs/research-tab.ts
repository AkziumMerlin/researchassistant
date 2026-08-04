import type { ResearchAssistantWidget } from '../research-assistant-widget';

interface ActionSpec {
    title: string;
    description: string;
    initial: unknown;
    actions: Array<[string, string, 'GET' | 'POST']>;
}

function parse(editor: HTMLTextAreaElement): unknown {
    return JSON.parse(editor.value);
}

export async function renderResearch(view: ResearchAssistantWidget): Promise<void> {
    const output = view.output('Run an adaptive-search, dataset, selection, statistics, research-log or publication action.');
    const grid = view.element('div', 'ra-research-grid');

    const run = async (
        method: 'GET' | 'POST',
        path: string,
        editor?: HTMLTextAreaElement,
    ): Promise<void> => {
        output.classList.remove('error');
        try {
            const result = method === 'GET'
                ? await view.get(path)
                : await view.post(path, editor ? parse(editor) : {});
            output.textContent = view.pretty(result);
        } catch (error) {
            output.classList.add('error');
            output.textContent = error instanceof Error ? error.message : String(error);
        }
    };

    const cards: ActionSpec[] = [
        {
            title: 'Adaptive HPO',
            description: 'Persist validation-only proposals and optionally launch them.',
            initial: {
                spec: {
                    name: 'search',
                    base_config: 'configs/experiment.yaml',
                    search_space: {
                        'components.model.params.width': {
                            type: 'categorical',
                            choices: [32, 64, 96],
                        },
                    },
                    objectives: [{ metric: 'loss', split: 'validation' }],
                    sampler: 'tpe',
                    max_trials: 20,
                    parallelism: 2,
                    seed: 0,
                },
                count: 1,
                launch: false,
            },
            actions: [
                ['Status', '/api/research/hpo/status', 'POST'],
                ['Propose', '/api/research/hpo/propose', 'POST'],
                ['Step', '/api/research/hpo/step', 'POST'],
            ],
        },
        {
            title: 'Datasets',
            description: 'Register immutable snapshots, validate checksums and materialize them.',
            initial: {
                spec: {
                    name: 'dataset',
                    version: '1',
                    source: 'data',
                    splits: { train: ['train/**'], validation: ['validation/**'], test: ['test/**'] },
                },
            },
            actions: [
                ['List', '/api/research/datasets', 'GET'],
                ['Register', '/api/research/datasets/register', 'POST'],
                ['Validate', '/api/research/datasets/validate', 'POST'],
                ['Materialize', '/api/research/datasets/materialize', 'POST'],
            ],
        },
        {
            title: 'Selection',
            description: 'Preview and lock validation-only model/checkpoint selection.',
            initial: {
                spec: {
                    name: 'final',
                    artifact_root: 'runs',
                    selection_metric: 'loss',
                    selection_split: 'validation',
                    target_metrics: ['loss'],
                    test_splits: ['test'],
                    direction: 'minimize',
                    group_by: ['study_id', 'dataset'],
                    min_seeds: 1,
                },
                overwrite: false,
            },
            actions: [
                ['List locks', '/api/research/selections', 'GET'],
                ['Preview', '/api/research/selection/preview', 'POST'],
                ['Lock', '/api/research/selection/lock', 'POST'],
                ['Evaluate', '/api/research/selection/evaluate', 'POST'],
            ],
        },
        {
            title: 'Statistics',
            description: 'Run paired comparisons, bootstrap intervals and multiple-test correction.',
            initial: {
                spec: {
                    name: 'comparison',
                    artifact_root: 'runs',
                    metric: 'loss',
                    split: 'test',
                    group_by: 'model',
                    paired_by: ['seed', 'dataset'],
                    correction: 'holm',
                    bootstrap_samples: 1000,
                    permutation_samples: 1000,
                    seed: 0,
                },
                output_path: 'reports/statistics',
            },
            actions: [['Run', '/api/research/statistics/run', 'POST']],
        },
        {
            title: 'Hypotheses',
            description: 'Record hypotheses, evidence and decisions with immutable references.',
            initial: {
                title: 'Research hypothesis',
                statement: 'State the expected relation.',
                expected_outcome: 'Describe the expected observation.',
                decision_criteria: 'Declare the acceptance criterion.',
                status: 'active',
            },
            actions: [
                ['List hypotheses', '/api/research/hypotheses', 'GET'],
                ['Create hypothesis', '/api/research/hypotheses', 'POST'],
                ['Add evidence', '/api/research/evidence', 'POST'],
                ['List decisions', '/api/research/decisions', 'GET'],
                ['Record decision', '/api/research/decisions', 'POST'],
                ['Export log', '/api/research/export', 'GET'],
            ],
        },
        {
            title: 'Publication',
            description: 'Preview and build a checksum-locked research bundle.',
            initial: {
                spec: {
                    name: 'paper',
                    title: 'Research report',
                    artifact_root: 'runs',
                    run_ids: [],
                    dataset_ids: [],
                    include_research_log: true,
                    strict_consistency: true,
                    template: 'generic',
                },
                output_path: 'publications/paper',
            },
            actions: [
                ['Preview', '/api/research/publication/preview', 'POST'],
                ['Build', '/api/research/publication/build', 'POST'],
            ],
        },
    ];

    for (const spec of cards) {
        const editor = view.element('textarea', 'ra-spec-editor');
        editor.value = JSON.stringify(spec.initial, null, 2);
        const description = view.element('p', 'ra-help', spec.description);
        const actions = view.element('div', 'ra-actions');
        for (const [label, path, method] of spec.actions) {
            actions.append(view.button(label, () => run(method, path, editor), label === 'Run' || label === 'Build' ? 'primary' : ''));
        }
        grid.append(view.card(spec.title, description, editor, actions));
    }

    view.content.replaceChildren(grid, view.card('Research result', output));
}
