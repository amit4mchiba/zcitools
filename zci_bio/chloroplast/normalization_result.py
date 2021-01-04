from step_project.common.table.steps import TableStep
from common_utils.file_utils import get_settings
from common_utils.exceptions import ZCItoolsValueError
from common_utils.cache import cache_args
from common_utils.terminal_layout import StringColumns
from ..utils.phylogenetic_tree import PhylogeneticTree


class _TreeDiffs:
    def __init__(self, norm_result, seq_type):
        self.seq_type = seq_type
        get_tree = norm_result.trees.get
        on_wg = ('oW', 'oG', 'nW', 'nG')

        # Robinson-Foulds distance, ETE3 used
        mr_bayes_trees = [get_tree(f'{seq_type}{on}_04_{wg}_MrBayes') for on, wg in on_wg]
        raxml_trees = [get_tree(f'{seq_type}{on}_04_{wg}_RAxML') for on, wg in on_wg]

        self.m2r_diffs = [m.distance_robinson_foulds(r, False) for m, r in zip(mr_bayes_trees, raxml_trees)]
        self.rf_m_diffs = [o.distance_robinson_foulds(n, False) for o, n in zip(mr_bayes_trees[:2], mr_bayes_trees[2:])]
        self.rf_r_diffs = [o.distance_robinson_foulds(n, False) for o, n in zip(raxml_trees[:2], raxml_trees[2:])]

        # Branch score distance, DendroPy used
        # mr_bayes_trees = [get_tree(f'{seq_type}{on}_04_{wg}_MrBayes', 'dendropy') for on, wg in on_wg]
        # raxml_trees = [get_tree(f'{seq_type}{on}_04_{wg}_RAxML', 'dendropy') for on, wg in on_wg]

        # self.bs_m_diffs = [o.compare(n) for o, n in zip(mr_bayes_trees[:2], mr_bayes_trees[2:])]
        # self.bs_r_diffs = [o.compare(n) for o, n in zip(raxml_trees[:2], raxml_trees[2:])]

    def print(self):
        _ed = lambda d: f"{int(d['rf'])}/{int(d['max_rf'])}"
        # Keys: rf, max_rf, ref_edges_in_source, source_edges_in_ref, effective_tree_size,
        #       norm_rf, treeko_dist, source_subtrees, common_edges, source_edges, ref_edges

        rows = [[f'Seqs {self.seq_type}', '', ''],
                ['', 'Complete', 'Parts'],
                ['o', _ed(self.m2r_diffs[0]), _ed(self.m2r_diffs[1])],
                ['n', _ed(self.m2r_diffs[2]), _ed(self.m2r_diffs[3])],
                ['o-n', _ed(self.rf_m_diffs[0]), _ed(self.rf_m_diffs[1])],
                ['', _ed(self.rf_r_diffs[0]), _ed(self.rf_r_diffs[1])]]
        print(StringColumns(rows))


class NormalizationResult:
    def __init__(self, project):
        self.project = project
        self.outgroup = None
        self.analyses_step = None
        self.has_A = False
        self.tree_steps = dict()  # step_name -> step object
        self.trees = dict()       # step_name -> PhylogeneticTree object
        #
        self.S_tree_diffs = None  # Of type _TreeDiffs
        self.A_tree_diffs = None  # Of type _TreeDiffs

    def run(self, step_data):
        self._find_project_data()

        self.S_tree_diffs = _TreeDiffs(self, 'S')
        self.S_tree_diffs.print()
        if self.has_A:
            self.A_tree_diffs = _TreeDiffs(self, 'A')
            self.A_tree_diffs.print()

        # Create step and collect data
        step = TableStep(self.project, step_data, remove_data=True)
        self.analyses_step.propagate_step_name_prefix(step)
        step.save()
        return step

    def _find_project_data(self):
        # Outgroup
        if (settings := get_settings()) and (wf := settings.get('workflow_parameters')):
            self.outgroup = wf.get('outgroup')
        if not self.outgroup:
            print('Info: No outgroup specified?!', settings)

        # Analyses chloroplast step
        self.analyses_step = self.project.read_step_if_in(
                '04_AnalyseChloroplast', check_data_type='table', no_check=True)
        if not self.analyses_step:
            raise ZCItoolsValueError('No analyse chloroplast step (04_AnalyseChloroplast)!')
        self.has_A = settings.get('calc_all', 0) and not all(self.analyses_step.get_column_values('Part starts'))

        # Find all phylogenetic steps
        for sa in ('SA' if self.has_A else 'S'):
            for on in 'on':
                for wg in 'WG':
                    for phylo, dt in (('MrBayes', 'mr_bayes'), ('RAxML', 'raxml')):
                        step_name = f'{sa}{on}_04_{wg}_{phylo}'
                        step = self.project.read_step_if_in(step_name, check_data_type=dt, no_check=True)
                        self.tree_steps[step_name] = step
                        self.trees[step_name] = PhylogeneticTree(
                            step.get_consensus_file(), self.outgroup,
                            rename_nodes=lambda name: f'NC_{name[2:]}' if name.startswith('p_') else name)

        if (no_steps := [k for k, v in self.tree_steps.items() if not v]):
            raise ZCItoolsValueError(f"No tree step(s): {', '.join(sorted(no_steps))}!")