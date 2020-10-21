from collections import defaultdict
import itertools
from .utils import find_chloroplast_partition
from ..utils.entrez import Entrez
from ..utils.helpers import fetch_from_properties_db
from ..utils.features import Feature


class SequenceDesc:
    def __init__(self, seq_ident, seq, table_data, sequence_step, properties_db):
        self.seq_ident = seq_ident
        self._seq = seq
        self._table_data = table_data
        #
        self.length = len(seq)
        self._genes = find_uniq_features(seq, 'gene')
        self._cds = find_uniq_features(seq, 'CDS')
        self._parts = find_chloroplast_partition(seq)
        self._parts_data = _PartsDesc(self._parts, self._genes, self.length) if self._parts else None
        self.part_starts = None
        self.part_lengths = None
        self.part_genes = None
        # Set in step 2. (Evaluate credibility of collected data)
        self.credible_whole_sequence = True
        self.credible_irs = True
        # Set in step 3. (Find missing or more credible data)
        self.irs_took_from = None
        self._took_parts = None
        self._tool_parts_data = None
        self.took_part_starts = None
        self.part_orientation = None

        # Extract data from NCBI GenBank files (comments)
        self.extract_ncbi_comments(sequence_step, properties_db)

    num_genes = property(lambda self: len(self._genes))
    num_cds = property(lambda self: len(self._cds))
    taxid = property(lambda self: self._table_data.get_cell(self.seq_ident, 'tax_id'))
    title = property(lambda self: self._table_data.get_cell(self.seq_ident, 'title'))
    created_date = property(lambda self: self._table_data.get_cell(self.seq_ident, 'create_date'))

    _ncbi_comment_fields = dict(
        (x, None) for x in ('artcle_title', 'journal', 'pubmed_id', 'first_date',
                            'assembly_method', 'sequencing_technology', 'bio_project', 'sra_count'))
    _key_genbank_data = 'NCBI GenBank data'
    _key_sra_count = 'NCBI SRA count'

    def extract_ncbi_comments(self, sequences_step, properties_db):
        # Notes:
        #  - sequences_step contains GenBank files collected from NCBI which contains genome info
        #  - properties_db is used to cache results dince they are static
        # Set empty fields
        self.__dict__.update(self._ncbi_comment_fields)

        self.__dict__.update(fetch_from_properties_db(
            properties_db, self.seq_ident, self._key_genbank_data,
            self._genbank_data, sequences_step, self.seq_ident, properties_db))

    def _genbank_data(self, sequences_step, seq_ident, properties_db):
        vals = dict()
        seq = sequences_step.get_sequence_record(seq_ident)

        refs = seq.annotations['references']
        if refs[0].title != 'Direct Submission':
            vals['artcle_title'] = refs[0].title
            vals['journal'] = refs[0].journal
            if refs[0].pubmed_id:
                vals['pubmed_id'] = int(refs[0].pubmed_id)
        if refs[-1].title == 'Direct Submission':
            # ToDo: re ...
            vals['first_date'] = datetime.strptime(
                refs[-1].journal.split('(', 1)[1].split(')', 1)[0], '%d-%b-%Y').date()

        if (sc := seq.annotations.get('structured_comment')) and \
           (ad := sc.get('Assembly-Data')):
            vals['assembly_method'] = ad.get('Assembly Method')
            vals['sequencing_technology'] = ad.get('Sequencing Technology')

        #
        vals.update(fetch_from_properties_db(
            properties_db, self.seq_ident, self._key_sra_count,
            self._sra_count_data, sequences_step, seq_ident, properties_db))
        return vals

    def _sra_count_data(self, seq):
        vals_sra = dict()
        for x in seq.dbxrefs:  # format ['BioProject:PRJNA400982', 'BioSample:SAMN07225454'
            if x.startswith('BioProject:'):
                if bp := x.split(':', 1)[1]:
                    vals_sra['bio_project'] = bp
                    sra_count = Entrez().search_count('sra', term=f"{bp}[BioProject]")
                    vals_sra['sra_count'] = sra_count or None  # None means empty cell :-)
        return vals_sra

    #
    def set_parts_data(self):
        if self._parts:
            self.part_starts, self.part_lengths, self.part_genes = _parts_desc(self._parts, self._genes, self.length)

        if self._took_parts:
            self.took_part_starts, _ = _parts_desc(self._took_parts, None, self.length)

        if parts := self._took_parts or self._parts:  # Take better one
            # Offset
            self.offset = seq_offset(self.length, parts.get_part_by_name('lsc').real_start)
            self.trnH_GUG = trnH_GUG_offset(self.length, self.offset, self._genes)

            # Part orientation
            orient = chloroplast_parts_orientation(self._seq, parts, self._genes)
            if ppp := [p for p in ('lsc', 'ira', 'ssc') if not orient[p]]:
                self.part_orientation = ','.join(ppp)


def chloroplast_parts_orientation(seq_rec, partition, genes):
    # Check chloroplast sequence part orientation.
    # Default orientation is same as one uses in Fast-Plast. Check:
    #  - source file orientate_plastome_v.2.0.pl
    #    (https://github.com/mrmckain/Fast-Plast/blob/master/bin/orientate_plastome_v.2.0.pl)
    #  - explanation https://github.com/mrmckain/Fast-Plast/issues/22
    # Consitent with Wikipedia image:
    #  - https://en.wikipedia.org/wiki/Chloroplast_DNA#/media/File:Plastomap_of_Arabidopsis_thaliana.svg

    l_seq = len(seq_rec)
    in_parts = partition.put_features_in_parts(Feature(l_seq, feature=f) for f in genes)

    lsc_count = sum(f.feature.strand if any(x in f.name for x in ('rpl', 'rps')) else 0
                    for f in in_parts.get('lsc', []))
    ssc_count = sum(f.feature.strand for f in in_parts.get('ssc', []))
    ira_count = sum(f.feature.strand if 'rrn' in f.name else 0 for f in in_parts.get('ira', []))

    return dict(lsc=(lsc_count <= 0),
                ssc=(ssc_count <= 0),
                ira=(ira_count >= 0))


def _parts_desc(parts, genes, length):
    # Formats:
    #  part starts     : '<lsc start>, <ira start>, <ssc strart>, <irb start>'
    #  part lengths    : '<lsc_length>, <ir length>, <ssc length>'
    #  number of genes : '<lsc start>, <ira start>, <ssc strart>, <irb start>'
    lsc, ira, ssc, irb = [parts[p] for p in ('lsc', 'ira', 'ssc', 'irb')]
    lsc_s = seq_offset(length, lsc.real_start)
    part_starts = ', '.join([str(lsc_s)] + [str(p.real_start) for p in (ira, ssc, irb)])
    part_lens = ', '.join(str(len(p)) for p in (lsc, ira, ssc))
    part_starts = f'{part_starts}\n{part_lens}'
    if genes is None:
        return part_starts, part_lens

    # Number of genes in parts
    part_genes = parts.put_features_in_parts([Feature(length, feature=f) for f in genes])
    gs = ', '.join(str(len(part_genes[p])) for p in ('lsc', 'ssc', 'ira', 'irb'))
    return part_starts, part_lens, gs


class _PartsDesc:
    def __init__(self, parts, genes, seq_length):
        lsc, ira, ssc, irb = [parts[p] for p in ('lsc', 'ira', 'ssc', 'irb')]
        lsc_s = seq_offset(seq_length, lsc.real_start)

        self.starts = [lsc_s] + [p.real_start for p in (ira, ssc, irb)]
        self.lengths = [len(p) for p in (lsc, ira, ssc, irb)]
        self.offset = seq_offset(seq_length, lsc.real_start)
        if genes is None:
            self.num_genes = None
            self.trnH_GUG = None
        else:
            part_genes = parts.put_features_in_parts([Feature(seq_length, feature=f) for f in genes])
            self.num_genes = [len(part_genes[p]) for p in ('lsc', 'ira', 'ssc', 'irb')]
            self.trnH_GUG = trnH_GUG_offset(seq_length, self.offset, genes)


def seq_offset(seq_length, offset):
    o2 = offset - seq_length
    return offset if offset <= abs(o2) else o2


def trnH_GUG_offset(seq_length, lsc_start, genes):
    features = [f for f in genes if f.qualifiers['gene'][0] == 'trnH-GUG']
    if features:
        rel_to_lsc = [((f.location.start - lsc_start) % seq_length) for f in features]
        return min(seq_offset(seq_length, d) for d in rel_to_lsc)


def find_uniq_features(seq, _type):
    fs = defaultdict(list)
    for idx, f in enumerate(seq.features):
        if f.type == _type and f.location:
            name = f.qualifiers['gene'][0]
            if not fs[name] or \
               ((s_f := set(f.location)) and not any(set(x.location).intersection(s_f) for _, x in fs[name])):
                fs[name].append((idx, f))
    return [y[1] for y in sorted(itertools.chain(*fs.values()))]