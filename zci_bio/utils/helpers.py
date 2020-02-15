import os
import shutil
from .import_methods import import_bio_seq_io, import_bio_align_io
from common_utils.file_utils import extension_no_dot

# Methods for this and that

# Biopyhton helpers
bio_io_known_formats = frozenset(['genbank', 'fasta'])
ext_2_bio_io_type = dict(
    gb='genbank', gbff='genbank',
    fa='fasta',  fas='fasta',
)
_bio_ext_2_type = dict(('.' + e, t) for e, t in ext_2_bio_io_type.items())

align_io_known_formats = frozenset(['phylip'])
ext_2_align_io_type = dict(
    phy='phylip',
)


def feature_location_desc(location):
    # Returns tuple of indices for describing location as simple as possible
    # Location can be specified in lot of ways, check:
    #   https://biopython.org/DIST/docs/api/Bio.SeqFeature-module.html

    cls_name = location.__class__.__name__  # To prevent importing of classes
    if cls_name == 'FeatureLocation':
        return (int(location.start), int(location.end))

    if cls_name == 'CompoundLocation':
        parts = location.parts
        return (int(parts[0].start), int(parts[-1].end))
        # return (int(location.start), int(location.end))

    assert False, (f'Not supported type {cls_name}!', location)


def feature_qualifiers_to_desc(feature):
    # From doc:
    # qualifiers - A dictionary of qualifiers on the feature.
    #   These are analogous to the qualifiers from a GenBank feature table.
    #   The keys of the dictionary are qualifier names, the values are the qualifier values.
    #   As of Biopython 1.69 this is an ordered dictionary.

    qualifiers = feature.qualifiers
    if feature.type in ('gene', 'CDS'):
        genes = qualifiers['gene']
        assert len(genes) == 1, genes
        return genes[0]

    if feature.type == 'repeat_region':
        r_type = qualifiers['rpt_type']
        assert len(r_type) == 1, r_type
        return r_type[0]

    return str(qualifiers)  # ToDo: For now


# Sequences
def read_sequence(filename, format=None):
    with open(filename, 'r') as in_data:
        return import_bio_seq_io().read(in_data, get_bio_io_type(filename, format))


def split_sequences(input_filename, output_ext):
    SeqIO = import_bio_seq_io()
    input_type = _bio_ext_2_type[os.path.splitext(input_filename)[1]]
    input_dir = os.path.dirname(input_filename)
    output_type = _bio_ext_2_type[output_ext]
    sequence_ids = []
    with open(input_filename, 'r') as seqs:
        for rec in SeqIO.parse(seqs, input_type):
            out_f = rec.id + output_ext
            if input_dir:
                out_f = os.path.join(input_dir, out_f)
            SeqIO.write([rec], open(out_f, 'w'), output_type)
            sequence_ids.append(rec.id)
    return sequence_ids


def concatenate_sequences(output_filename, input_filenames):
    SeqIO = import_bio_seq_io()
    output_type = _bio_ext_2_type[os.path.splitext(output_filename)[1]]
    with open(output_filename, 'w') as out_seqs:
        for in_f in input_filenames:
            with open(in_f, 'r') as seq:
                SeqIO.write(list(SeqIO.parse(seq, _bio_ext_2_type[os.path.splitext(in_f)[1]])), out_seqs, output_type)


def convert_sequence_file(input_filename, output_filename, input_format=None, output_format=None):
    import_bio_seq_io().convert(
        input_filename, get_bio_io_type(input_filename, input_format),
        output_filename, get_bio_io_type(output_filename, output_format))


def change_sequence_data(method, input_filename, output_filename, input_format=None, output_format=None, position=None):
    SeqIO = import_bio_seq_io()
    from Bio.Seq import Seq  # Now it is safe to make an import
    from Bio.SeqRecord import SeqRecord

    input_format = get_bio_io_type(input_filename, input_format)
    output_format = get_bio_io_type(output_filename, output_format)
    with open(output_filename, 'w') as out_seqs:
        with open(input_filename, 'r') as in_seqs:
            for rec in SeqIO.parse(in_seqs, input_format):
                if method == 'revert':
                    seq = str(rec.seq)[::-1]
                elif method == 'translate':
                    assert position
                    seq = str(rec.seq)
                    seq = seq[position:] + seq[:position]
                else:
                    assert False, method

                # Note: featues/annotations not transfered!
                SeqIO.write(
                    SeqRecord(Seq(seq, rec.seq.alphabet), id=rec.id, name=rec.name, description=rec.description),
                    out_seqs, output_format)


#
def write_annotated_sequence(filename, id_, seq, annotation, output_format=None, name=None, description=None):
    SeqIO = import_bio_seq_io()
    from Bio.Seq import Seq  # Now it is safe to make an import
    from Bio.SeqRecord import SeqRecord
    from Bio.SeqFeature import SeqFeature, FeatureLocation
    from Bio.Alphabet import DNAAlphabet

    output_format = get_bio_io_type(filename, output_format)
    with open(filename, 'w') as out_seqs:
        features = [SeqFeature(location=FeatureLocation(f_i, t_i), type=ft, id=n, qualifiers=dict(gene=n))
                    for ft, n, f_i, t_i in annotation]
        SeqIO.write(
            SeqRecord(Seq(seq, DNAAlphabet()),
                      id=id_, name=name, description=str(description), features=features),
            out_seqs, output_format)


#
def get_bio_io_type(filename, format_):
    if not format_:
        ext = extension_no_dot(filename)
        format_ = ext_2_bio_io_type.get(ext, ext)
    assert format_ in bio_io_known_formats, (filename, format_)
    return format_


# ALignments
def read_alignment(filename, format=None):
    with open(filename, 'r') as in_data:
        return import_bio_align_io().read(in_data, get_align_io_type(filename, format))


def get_align_io_type(filename, format_):
    if not format_:
        ext = extension_no_dot(filename)
        format_ = ext_2_align_io_type.get(ext, ext)
    assert format_ in align_io_known_formats, (filename, format_)
    return format_


#
def fetch_our_sequence(seq_ident, in_dir):
    dirs = os.environ.get('ZCI_OUR_SEQUENCES')
    if dirs:
        for _dir in dirs.split(':'):
            for f in os.listdir(_dir):
                name, ext = os.path.splitext(f)
                if name == seq_ident:
                    shutil.copyfile(os.path.join(_dir, f), os.path.join(in_dir, f))
                    return ext
