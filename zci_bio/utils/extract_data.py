import os.path
from functools import wraps
import difflib
from datetime import datetime
from Bio.SeqFeature import FeatureLocation, CompoundLocation
from .entrez import Entrez
from .diff_sequences import Diff
from ..chloroplast.utils import find_chloroplast_irs


def with_seq(func):
    @wraps(func)
    def func_wrapper(self, seq_ident=None, seq=None):
        if seq is None:
            assert seq_ident
            seq = self.sequences_step.get_sequence_record(seq_ident)
        return func(self, seq)
    return func_wrapper


def with_seq_ident(func):
    @wraps(func)
    def func_wrapper(self, seq_ident=None, seq=None):
        if not seq_ident:
            seq_ident = seq.name
        return func(self, seq_ident)
    return func_wrapper


class ExtractData:
    # Extract/fetch additional data from NCBI GenBank file or by Entrez searches.
    # Idea is to cache that data
    # Two set of methods:
    #  - set of methods that extract or fetch data
    #  - set of methods use upper methods and do caching.
    def __init__(self, properties_db=None, sequences_step=None):
        self.properties_db = properties_db
        self.sequences_step = sequences_step

    def _seq_filename(self, seq_ident):
        return os.path.abspath(self.sequences_step.get_sequence_filename(seq_ident))

    # Extract and fetch methods
    @with_seq
    def genbank_data(self, seq):
        annotations = seq.annotations

        vals = dict(length=len(seq.seq))
        if not_dna := [i for i, c in enumerate(str(seq.seq)) if c not in 'ATCG']:
            vals['not_dna'] = not_dna

        vals.update((k, v) for k in ('organism', 'sequence_version') if (v := annotations.get(k)))
        if v := annotations.get('date'):
            vals['update_date'] = datetime.strptime(v, '%d-%b-%Y').date()

        refs = annotations['references']
        if refs[0].title != 'Direct Submission':
            vals['article_title'] = refs[0].title
            vals['journal'] = refs[0].journal
            if refs[0].pubmed_id:
                vals['pubmed_id'] = int(refs[0].pubmed_id)
        if refs[-1].title == 'Direct Submission':
            # ToDo: re ...
            vals['first_date'] = datetime.strptime(
                refs[-1].journal.split('(', 1)[1].split(')', 1)[0], '%d-%b-%Y').date()

        if (sc := annotations.get('structured_comment')) and \
           (ad := sc.get('Assembly-Data')):
            vals['assembly_method'] = ad.get('Assembly Method')
            vals['sequencing_technology'] = ad.get('Sequencing Technology')
        return vals

    @with_seq
    def sra_count(self, seq):
        vals_sra = dict()
        for x in seq.dbxrefs:  # format ['BioProject:PRJNA400982', 'BioSample:SAMN07225454'
            if x.startswith('BioProject:'):
                if bp := x.split(':', 1)[1]:
                    vals_sra['bio_project'] = bp
                    sra_count = Entrez().search_count('sra', term=f"{bp}[BioProject]")
                    vals_sra['sra_count'] = sra_count or None  # None means empty cell :-)
        return vals_sra

    @with_seq
    def annotation(self, seq):
        if irs := find_chloroplast_irs(seq, check_length=False):
            ira, irb = irs
            # To be sure!
            ira_p = ira.location.parts
            irb_p = irb.location.parts
            d = dict(length=len(seq.seq),
                     ira=[int(ira_p[0].start), int(ira_p[-1].end)],
                     irb=[int(irb_p[0].start), int(irb_p[-1].end)])
            #
            ira_s = ira.extract(seq)
            irb_s = irb.extract(seq)
            if ira.strand == irb.strand:
                irb_s = irb_s.reverse_complement()
            d.update(self._irs_desc(seq, ira_s, irb_s, d))
            return d
        return dict(length=len(seq.seq))

    @with_seq
    def small_d(self, seq):
        return self._small_d_annotation(seq, no_prepend_workaround=True, no_dna_fix=True)

    @with_seq
    def small_d_P(self, seq):
        return self._small_d_annotation(seq, no_prepend_workaround=False, no_dna_fix=True)

    @with_seq
    def small_d_D(self, seq):
        return self._small_d_annotation(seq, no_prepend_workaround=True, no_dna_fix=False)

    @with_seq
    def small_d_all(self, seq):
        return self._small_d_annotation(seq, no_prepend_workaround=False, no_dna_fix=False)

    @with_seq_ident
    def chloroplot(self, seq_ident):
        from ..chloroplast.irs.chloroplot import chloroplot as chloroplot_ann
        return chloroplot_ann(self._seq_filename(seq_ident))

    @with_seq_ident
    def pga(self, seq_ident):
        from ..chloroplast.irs.pga import pga
        return self._from_indices(
            self.sequences_step.get_sequence_record(seq_ident),
            pga(self._seq_filename(seq_ident)))

    @with_seq_ident
    def pga_sb(self, seq_ident):
        return self._self_blast('pga', seq_ident)

    @with_seq_ident
    def plann(self, seq_ident):
        from ..chloroplast.irs.plann import plann
        return self._from_indices(
            self.sequences_step.get_sequence_record(seq_ident),
            plann(self._seq_filename(seq_ident)))

    @with_seq_ident
    def plann_sb(self, seq_ident):
        return self._self_blast('plann', seq_ident)

    @with_seq_ident
    def org_annotate(self, seq_ident):
        from ..chloroplast.irs.org_annotate import org_annotate
        return self._from_indices(
            self.sequences_step.get_sequence_record(seq_ident),
            org_annotate(self._seq_filename(seq_ident)))

    #
    def _small_d_annotation(self, seq, no_prepend_workaround=True, no_dna_fix=True):
        from ..chloroplast.irs.small_d import small_d
        return self._from_indices(
            seq,
            small_d(seq, no_prepend_workaround=no_prepend_workaround, no_dna_fix=no_dna_fix))

    def _self_blast(self, variant, seq_ident):
        from ..chloroplast.irs.self_blast import self_blast
        return self._from_indices(
            self.sequences_step.get_sequence_record(seq_ident),
            self_blast(variant, self._seq_filename(seq_ident)))

    #
    def _from_indices(self, seq, irs):
        if irs:
            print(irs)
            ira, irb = irs
            seq_len = len(seq.seq)
            d = dict(length=len(seq.seq),
                     ira=[ira[0], ira[1]],
                     irb=[irb[0], irb[1]])
            #
            ira = self._feature(seq, *ira, 1)
            irb = self._feature(seq, *irb, -1)
            d.update(self._irs_desc(seq, ira.extract(seq), irb.extract(seq), d))
            return d
        return dict(length=len(seq.seq))

    def _feature(self, seq, s, e, strand):
        if s < e:
            return FeatureLocation(s, e, strand=strand)
        return CompoundLocation([FeatureLocation(s, len(seq.seq), strand=strand),
                                 FeatureLocation(0, e, strand=strand)])

    def _irs_desc(self, seq, ira, irb, irs_d):
        ira = str(ira.seq)
        irb = str(irb.seq)
        # print(len(ira), len(irb))
        # print('  ira', ira[:20], ira[-20:])
        # print('  irb', irb[:20], irb[-20:])
        if ira == irb:
            return dict(type='+')

        # Check is same IRs region already inspected.
        seq_ident = seq.name.split('.')[0]
        for _, data in self.properties_db.get_properties_key2_like(seq_ident, 'annotation %').items():
            if irs_d['ira'] == data.get('ira') and irs_d['irb'] == data.get('irb'):
                return dict(type=data['type'], diff=data['diff'])

        print(f'diff {seq_ident}: lengths {len(ira)} and {len(irb)}')
        diff = Diff(ira, irb)
        return dict(type=diff.in_short(), diff=diff.get_opcodes())


# Add cache methods into ExtractData class
# Note: these methods are not decorators, but quite similar
def cache_fetch(key, method):
    def func_wrapper(self, seq_ident=None, seq=None):
        if not seq_ident:
            seq_ident = seq.name
        return self.properties_db.fetch_property(seq_ident, key, method(self), seq_ident=seq_ident, seq=seq)
    return func_wrapper


def cache_fetch_keys1(key, method):
    def func_wrapper(self, seq_idents, seq_step=None):
        if not seq_step:
            seq_step = self.sequences_step
        sr = seq_step.get_sequence_record
        return self.properties_db.fetch_properties_keys1(
            seq_idents, key, lambda s: method(self, seq_ident=s, seq=sr(s)))
    return func_wrapper


for key, m_sufix, cls_method in (
        ('NCBI GenBank data', 'genbank_data', ExtractData.genbank_data),
        ('NCBI SRA count', 'sra_count', ExtractData.sra_count),
        ('annotation ncbi', 'annotation_ncbi', ExtractData.annotation),
        ('annotation ge_seq', 'annotation_ge_seq', ExtractData.annotation),
        ('annotation small_d', 'annotation_small_d', ExtractData.small_d),
        ('annotation small_d_P', 'annotation_small_d_P', ExtractData.small_d_P),
        ('annotation small_d_D', 'annotation_small_d_D', ExtractData.small_d_D),
        ('annotation small_d_all', 'annotation_small_d_all', ExtractData.small_d_all),
        ('annotation chloe', 'annotation_chloe', ExtractData.annotation),
        ('annotation chloroplot', 'annotation_chloroplot', ExtractData.chloroplot),
        ('annotation pga', 'annotation_pga', ExtractData.pga),
        ('annotation pga_sb', 'annotation_pga_sb', ExtractData.pga_sb),
        ('annotation plann', 'annotation_plann', ExtractData.plann),
        ('annotation plann_sb', 'annotation_plann_sb', ExtractData.plann_sb),
        ('annotation org_annotate', 'annotation_org_annotate', ExtractData.org_annotate),
        ):
    # Caching
    # Interface: method_name(seq_ident=None, seq=None)
    setattr(ExtractData, f'cache_{m_sufix}', cache_fetch(key, cls_method))
    # Bulk fetch
    # Interface: method_name(seq_idents, seq_step=None)
    setattr(ExtractData, f'cache_keys1_{m_sufix}', cache_fetch_keys1(key, cls_method))
