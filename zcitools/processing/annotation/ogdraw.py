import os.path
import re
from zipfile import ZipFile
from zcitools.steps.images import ImagesStep
from zcitools.utils.helpers import split_list
from zcitools.utils.file_utils import write_str_in_file, read_file_as_str, read_file_as_list, extract_from_zip

_instructions = """
Open web page: https://chlorobox.mpimp-golm.mpg.de/OGDraw.html

For each GenBank file {step_name}/*.gbff do:

FASTA file(s) to annotate
 * Upload file
 * (check) Circular
 * (check) Plastid
 * (check) Tidy up annotation

Inverted Repeat
 * (check) Auto

Output Options
 * check {image_format}

Actions
 * Submit

When job is finished:
 - Download all results as zip (small disk icon in Results header) into {step_name}

When all files are processed:
 - run zcit command: zcit.py ogdraw {step_name}

-----
FAQ: https://chlorobox.mpimp-golm.mpg.de/OGDraw-FAQ.html
"""


def calculate_ogdraw(step_data, image_format, annotations_step, cache):
    step = ImagesStep(step_data, remove_data=True)
    all_images = sorted(annotations_step.all_sequences())

    # Fetch cached sequences
    to_fetch = step.get_cached_records(cache, all_images, info=True)

    # Store sequence
    if to_fetch:
        # Note: it is important that file has extension gbff (multiple sequence data)
        for i, d in enumerate(split_list(to_fetch, 30)):
            annotations_step.concatenate_seqs_genbank(step.step_file(f'sequences_{i + 1}.gbff'), d)
            # Write sequences for finish command
            write_str_in_file(step.step_file(f'_list_sequences_{i + 1}.txt'), '\n'.join(d))

        # Store instructions
        write_str_in_file(step.step_file('INSTRUCTIONS.txt'),
                          _instructions.format(step_name=step_data['step_name'], image_format=image_format))
        # Store image format used
        write_str_in_file(step.step_file('_image_format.txt'), image_format)

    #
    step.set_images(all_images)
    step.save(needs_editing=True)
    return step


def finish_ogdraw(step_obj, cache):
    # Note: original files are left in directory
    image_format = read_file_as_str(step_obj.step_file('_image_format.txt'))
    assert image_format

    # Check files ogdraw-result-<num>-<hash>.zip
    zip_files = step_obj.step_files(matches='^ogdraw-result-[0-9]+-.*.zip')
    if not zip_files:
        print("Warning: can't find any OGDraw output file (ogdraw-result-*.zip)!")
        return

    # Collect sequence idents submited
    seq_ident_map = dict()  # (sequence file idx, line idx) -> seq_ident
    for f in step_obj.step_files(matches=r'^_list_sequences_\d+.txt'):
        file_idx = int(re.findall(r'\d+', f)[0])
        # Note: line idx starts from 1, since files in zip has that numbering
        seq_ident_map.update(((file_idx, i + 1), seq_ident)
                             for i, seq_ident in enumerate(read_file_as_list(step_obj.step_file(f))))

    # extract ogdraw-result-<num>-<hash>/sequences_<num>ff_<num>/ogdraw_job_<hash>-outfile.<image_format>
    # Zip subdirectory naming depends on naming of OGDraw input files (sequences_<num>.gbff)
    f_end = f'-outfile.{image_format}'
    added_images = []
    for filename in zip_files:
        with ZipFile(step_obj.step_file(filename), 'r') as zip_f:
            for z_i in zip_f.infolist():
                if z_i.filename.endswith(f_end):
                    # Find sequence id of that file
                    rest = z_i.filename.split('sequences_')[1]
                    nums = re.findall(r'\d+', rest)
                    file_idx = int(nums[0])
                    line_idx = int(nums[1])
                    seq_ident = seq_ident_map[(file_idx, line_idx)]
                    #
                    added_images.append(seq_ident)
                    extract_from_zip(zip_f, z_i.filename, step_obj.step_file(f'{seq_ident}.{image_format}'))

    step_obj._check_data()
    step_obj.save(create=False)

    # Set into the cache
    if cache:
        for image_ident in added_images:
            cache.set_record(image_ident, step_obj.step_file(f'{image_ident}.{image_format}'))
