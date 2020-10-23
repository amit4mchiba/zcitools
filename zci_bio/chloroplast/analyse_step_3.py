import os
import multiprocessing
from concurrent.futures import ThreadPoolExecutor
from common_utils.file_utils import ensure_directory, write_fasta
from ..utils.mummer import MummerDelta
from ..utils.ncbi_taxonomy import get_ncbi_taxonomy


def run_align_cmd(seq_fasta, qry_fasta, out_prefix):
    # Blast version
    # cmd = f"blastn -subject {seq_fasta} -query {qry_fasta} " + \
    #     f"-perc_identity 40 -num_alignments 2 -max_hsps 2 -outfmt 5 > {out_prefix}.xml"
    # ...

    # Mummer version
    out_prefix = os.path.join(os.path.dirname(seq_fasta), out_prefix)
    cmd = f"nucmer -p {out_prefix} {seq_fasta} {qry_fasta}"
    print(f"Command: {cmd}")
    os.system(cmd)

    # Read output file
    return MummerDelta(f'{out_prefix}.delta')


def find_missing_partitions(seq_descs):
    with_irs = set(d.taxid for d in seq_descs.values() if d._parts and not d._took_parts)
    if len(with_irs) == len(seq_descs):  # All in
        return
    if not with_irs:
        print('Warning: all genomes miss IR parts!!!')
        return

    # Run alignment of related species IR ends onto sequences without IRs
    ncbi_tax = get_ncbi_taxonomy()
    seq_2_result_object = dict()  # dict seq_ident -> tuple (ira interval, irb interval, matche seq_ident)
    with ThreadPoolExecutor(max_workers=multiprocessing.cpu_count()) as executor:
        for seq_ident, seq_data in seq_descs.items():
            if seq_data._parts or seq_data._took_parts:
                continue

            ncbi_2_max_taxid = seq_data._analyse.ncbi_2_max_taxid
            close_taxids = ncbi_tax.find_close_taxids(seq_data.taxid, ncbi_2_max_taxid[seq_ident], with_irs)
            if not close_taxids:
                print(f"Warning: sequence {seq_ident} doesn't have close relative with IR partition!")
                continue

            taxid_2_ncbi = seq_data._analyse.taxid_2_ncbi
            # _run_align(seq_ident, seq_data, [seq_descs[taxid_2_ncbi[t]] for t in close_taxids],
            #            seq_2_result_object)
            executor.submit(_run_align, seq_ident, seq_data, [seq_descs[taxid_2_ncbi[t]] for t in close_taxids],
                            seq_2_result_object)

    #
    for seq_ident, (ira, irb, transfer_from) in seq_2_result_object.items():
        seq_descs[seq_ident].set_took_part(ira, irb, transfer_from, 'missing')

    return seq_2_result_object


def _run_align(seq_ident, seq_data, close_data, seq_2_result_object, match_length=100, first_nice=True):
    # Store fasta
    f_dir = seq_data._analyse.step.step_file('find_irs', seq_ident)
    ensure_directory(f_dir)
    seq_fasta = os.path.join(f_dir, f"{seq_ident}.fa")
    write_fasta(seq_fasta, [(seq_ident, seq_data._seq.seq)])

    all_aligns = []
    for d in close_data:
        ira = d._parts.get_part_by_name('ira')
        rec = ira.extract(d._seq)
        qry_fasta = os.path.join(f_dir, f"qry_{d.seq_ident}.fa")
        write_fasta(qry_fasta, [('end1', rec.seq[:match_length]), ('end2', rec.seq[-match_length:])])
        align = run_align_cmd(seq_fasta, qry_fasta, f"res_{d.seq_ident}")
        if first_nice and (x := _get_nice_irs(align)):
            seq_2_result_object[seq_ident] = (*x, d.seq_ident)
            return
        all_aligns.append(align)

    # No alignment matched all ends.
    if x := _get_the_best_irs(all_aligns):
        seq_2_result_object[seq_ident] = (*x, d.seq_ident)


def _get_the_best_ir(irss):
    max_l, max_irs = None, None
    for irs in irss:
        if irs:
            ira, irb = irs
            _l = (ira[1] - ira[0]) if ira[1] > ira[0] else (irb[1] - irb[0])
            if max_l is None or _l > max_l:
                max_l, max_irs = _l, irs
    return max_irs


def _get_the_best_irs(alignments):
    # Try nice ones, than partial (2+1), than partial (1+2)
    for m in (_get_nice_irs, _get_2_1_irs, _get_1_2_irs):
        if x := _get_the_best_ir(map(m, alignments)):
            return x


def _get_nice_irs(align):
    if 2 == len(align.aligns(None, 'end1')) == len(align.aligns(None, 'end2')):  # All sides
        ira_1, irb_2 = align.aligns(None, 'end1')
        ira_2, irb_1 = align.aligns(None, 'end2')
        return ((ira_1.sequence_interval[0], ira_2.sequence_interval[1]),
                (irb_1.sequence_interval[0], irb_2.sequence_interval[1]))


def _get_2_1_irs(align):
    if len(align.aligns(None, 'end1')) == 2 and len(align.aligns(None, 'end2')) == 1:
        ira_1, irb_2 = align.aligns(None, 'end1')
        ir = align.aligns(None, 'end2')[0]
        if ir.positive:  # In positive direction (IRA matched)
            x = ir.sequence_interval[1]
            y = irb_2.sequence_interval[1] - (x - ira_1.sequence_interval[0])
        else:
            y = ir.sequence_interval[0]
            x = ira_1.sequence_interval[0] + (irb_2.sequence_interval[1] - y)
        return ((ira_1.sequence_interval[0], x), (y, irb_2.sequence_interval[1]))


def _get_1_2_irs(align):
    if len(align.aligns(None, 'end1')) == 1 and len(align.aligns(None, 'end2')) == 2:
        ir = align.aligns(None, 'end1')[0]
        ira_2, irb_1 = align.aligns(None, 'end2')
        if ir.positive:  # In positive direction (IRA matched)
            x = ir.sequence_interval[0]
            y = irb_1.sequence_interval[0] + (ira_2.sequence_interval[1] - x)
        else:
            y = ir.sequence_interval[1]
            x = ira_2.sequence_interval[1] - (y - irb_1.sequence_interval[0])
        return ((x, ira_2.sequence_interval[1]), (irb_1.sequence_interval[0], y))


def find_best_irs_by_similar(seq_descs, seq_ident, seq_data):
    with_irs = set(d.taxid for d in seq_descs.values() if d._parts)
    with_irs.discard(seq_data.taxid)
    if not with_irs:
        print('Warning: all genomes miss IR parts!!!')
        return

    ncbi_2_max_taxid = seq_data._analyse.ncbi_2_max_taxid
    close_taxids = get_ncbi_taxonomy().find_close_taxids(seq_data.taxid, ncbi_2_max_taxid[seq_ident], with_irs)
    if not close_taxids:
        print(f"Warning: sequence {seq_ident} doesn't have close relative with IR partition!")
        return

    taxid_2_ncbi = seq_data._analyse.taxid_2_ncbi
    seq_2_result_object = dict()
    _run_align(seq_ident, seq_data, [seq_descs[taxid_2_ncbi[t]] for t in close_taxids], seq_2_result_object, first_nice=False)
    return seq_2_result_object.get(seq_ident)  # None or (ira, irb, transfer_from)
