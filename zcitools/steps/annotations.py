import os.path
from collections import defaultdict
from .step import Step
from ..utils.import_methods import import_bio_seq_io
from ..utils.terminal_layout import StringColumns
from ..utils.genbank import feature_qualifiers_to_desc


class AnnotationsStep(Step):
    """
Stores list of (DNA) sequences with there annotations.
List of sequence identifier are stored in description.yml.
Annotations are stored:
 - in file annotations.gb, for whole sequnece set,
 - or in files <seq_ident>.gb for each sequence separately.
"""
    _STEP_TYPE = 'annotations'
    _ALL_FILENAME = 'annotations.gb'

    # Init object
    def _init_data(self, type_description):
        self._sequences = set()  # seq_ident
        if type_description:
            self._sequences.update(type_description['sequences'])

    def _check_data(self):
        exist_seq_idents = set(seq_ident for seq_ident, _ in self._iterate_records())
        # Are all sequences presented
        not_exist = self._sequences - exist_seq_idents
        if not_exist:
            raise ZCItoolsValueError(f"Sequence data not presented for: {', '.join(sorted(not_exist))}")

        # Is there more sequences
        more_data = exist_seq_idents - self._sequences
        if more_data:
            raise ZCItoolsValueError(f"Data exists for not listed sequence(s): {', '.join(sorted(more_data))}")

    # Set data
    def set_sequences(self, seqs):
        self._sequences.update(seqs)

    # Save/load data
    def get_all_annotation_filename(self):
        return self.step_file(self._ALL_FILENAME)

    def save(self, needs_editing=False):
        # Store description.yml
        self.save_description(dict(sequences=sorted(self._sequences)), needs_editing=needs_editing)

    # Retrieve data methods
    def _iterate_records(self, filter_seqs=None):
        SeqIO = import_bio_seq_io()

        all_f = self.get_all_annotation_filename()
        if os.path.isfile(all_f):
            with open(all_f, 'r') as in_s:
                for seq_record in SeqIO.parse(in_s, 'genbank'):
                    if not filter_seqs or seq_record.id in filter_seqs:
                        yield seq_record.id, seq_record
        else:
            raise 'Not implemented!!!'

    def _get_genes(self, filter_seqs=None):
        data = dict()  # seq_ident -> set of genes
        for seq_ident, seq_record in self._iterate_records(filter_seqs=filter_seqs):
            data[seq_ident] = set(feature_qualifiers_to_desc(f) for f in seq_record.features if f.type == 'gene')
        return data

    # Show data
    def show_data(self, params=None):
        # If listed, filter only these sequences
        filter_seqs = None
        if params:
            filter_seqs = self._sequences & set(params)
            params = [p for p in params if p not in filter_seqs]  # Remove processed params

        cmd = params[0] if params else 'by_type'  # Default print
        if params:
            params = params[1:]

        if cmd == 'by_type':
            all_types = set()
            data = dict()  # seq_ident -> dict(length=int, features=int, <type>=num)
            for seq_ident, seq_record in self._iterate_records(filter_seqs=filter_seqs):
                d = defaultdict(int)
                genes = set()
                for f in seq_record.features:
                    if f.type != 'source':
                        d[f.type] += 1
                        if f.type == 'gene':
                            genes.add(feature_qualifiers_to_desc(f))
                if genes:
                    d['gene_unique'] = len(genes)
                all_types.update(d.keys())
                d['length'] = len(seq_record.seq)
                d['features'] = len(seq_record.features)
                data[seq_ident] = d

            all_types = sorted(all_types)
            header = ['seq_ident', 'Length', 'Features'] + all_types
            rows = [[seq_ident, d['length'], d['features']] + [d.get(t, 0) for t in all_types]
                    for seq_ident, d in sorted(data.items())]
            print(StringColumns(sorted(rows), header=header))

        elif cmd == 'genes':
            data = self._get_genes(filter_seqs=filter_seqs)
            for seq_ident, genes in sorted(data.items()):
                print(f"{seq_ident} ({len(genes)}): {', '.join(sorted(genes))}")

        elif cmd == 'shared_genes':
            data = self._get_genes(filter_seqs=filter_seqs)
            if len(data) > 1:
                same_genes = set.intersection(*data.values())
                print('Genes not shared by all sequences:')
                for seq_ident, genes in sorted(data.items()):
                    rest_genes = genes - same_genes
                    print(f"    {seq_ident} ({len(rest_genes)}): {', '.join(sorted(rest_genes))}")

                print(f"Shared ({len(same_genes)}): {', '.join(sorted(same_genes))}")
            else:
                print('Not enough data to find same ganes!')
