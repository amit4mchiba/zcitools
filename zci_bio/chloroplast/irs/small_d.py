import os
import tempfile
import subprocess
import tempfile
from Bio import SeqIO

"""
Wrapper around irscan program. irscan program is used by OGDRAW to locate IRs.

'For quick and precise detection of inverted repeat regions in organellar genomes,
a small D program (http://www.digitalmars.com/d/index.html) was developed and included in the package.'
From paper:
(2007) OrganellarGenomeDRAW (OGDRAW): a tool for the easy generation of high-quality custom graphical
maps of plastid and mitochondrial genomes.
https://link.springer.com/article/10.1007/s00294-007-0161-y

'Small D' executables and source can be found on OGDRAW download page:
 - https://chlorobox.mpimp-golm.mpg.de/OGDraw-Downloads.html
 - File is GeneMap-1.1.1.tar.gz.
Subproject irscan contains directories:
 - bin : Win, Linux and Mac executables.
 - src : D code.

Note: it is not possible to compile code with current D version.

I encountered two types of crashes, which stderr outputs are:
Error: ArrayBoundsError irscan(161)
 - IR starts at sequence start. Method screen_from_to_pos() moves pos into negative
 - Workaround is to run irscan on sequence prepended by sequence end. Like: seq[-100:] + seq

Error: ArrayBoundsError irscan(354)
 - IRs were not located. Printing of results crashes.
 - No workaround since there are no IRs. At least not in irscan definition of IRs.
"""


def small_d(seq_rec, working_dir=None):
    if not working_dir:
        working_dir = tempfile.gettempdir()
    fasta_filename = os.path.join(working_dir, f'{seq_rec.name}.fa')
    irscan_exe = os.environ.get('IRSCAN_EXE', 'irscan')

    for offset in (0, 500, 5000, 25000, 30000):
        s_rec = (seq_rec[-offset:] + seq_rec) if offset else seq_rec
        SeqIO.write([s_rec], fasta_filename, 'fasta')
        with tempfile.TemporaryFile() as stderr:
            try:
                result = subprocess.run([irscan_exe, '-f', fasta_filename],
                                        check=True,
                                        stdout=subprocess.PIPE, stderr=stderr)
            except subprocess.CalledProcessError:
                stderr.seek(0)
                err = stderr.read().decode('utf-8')
                print(f'\nWarning: sequence {seq_rec.name} has IR on the start, with offset {offset}!\n{err}\n')
                if '161' in err:
                    # Try with longer offset
                    continue
                return  # Nothing to do more!
        #
        os.remove(fasta_filename)
        seq_length = len(seq_rec.seq)
        output = result.stdout.decode('utf-8')
        irs = tuple(int(x) - offset for x in output.split(';')[:4])
        ira, irb = _ir(seq_length, *irs[:2]), _ir(seq_length, *irs[2:])

        # Check IR order
        if (irb[0] - ira[1]) % seq_length < (ira[0] - irb[1]) % seq_length:
            return ira, irb
        return irb, ira


def _ir(seq_length, ira, irb):
    # Note: irscan output is 1-based, and range means [start..end]
    return ((ira - 1) % seq_length), (irb if irb > 0 else (irb % seq_length))


def small_d_on_file(seq_filename):
    _ext_2_bio_io_type = dict(
        gb='genbank', gbff='genbank',
        fa='fasta',  fas='fasta',
        fastq='fastq',
    )

    base_filename, file_extension = os.path.splitext(seq_filename)
    in_format = _ext_2_bio_io_type[file_extension[1:]]
    return small_d(SeqIO.read(seq_filename, in_format))


if __name__ == '__main__':
    import sys
    print(small_d_on_file(sys.argv[1]))