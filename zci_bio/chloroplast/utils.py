from common_utils.exceptions import ZCItoolsValueError
from ..utils.features import Feature, Partition


def find_chloroplast_irs(seq):
    # Finds the longest pair of inverted repeats
    _ir = ('inverted',)
    rep_regs = [f for f in seq.features
                if f.type == 'repeat_region' and
                f.qualifiers.get('rpt_type', _ir)[0] == 'inverted']
    if rep_regs:
        max_len = max(map(len, rep_regs))
        max_regs = [f for f in rep_regs if len(f) == max_len]
        if len(max_regs) == 2:
            check_l = len(seq) // 4
            ira, irb = max_regs
            return (irb, ira) if (check_l < irb.location.start < ira.location.start) else (ira, irb)


def find_chloroplast_partition(seq_ident, seq):
    # Returns None or Partition object with parts named: lsc, ira, ssc, irb.
    irs = find_chloroplast_irs(seq)
    if irs:
        ira, irb = irs
        l_seq = len(seq)
        partition = Partition(
            [Feature(l_seq, name='ira', feature=ira), Feature(l_seq, name='irb', feature=irb)],
            fill=True)
        n_parts = partition.not_named_parts()
        assert len(n_parts) == 2, len(n_parts)
        ssc_ind = int(len(n_parts[0]) > len(n_parts[1]))
        n_parts[1 - ssc_ind].name = 'lsc'
        n_parts[ssc_ind].name = 'ssc'
        return partition
