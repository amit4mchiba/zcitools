import os.path
import datetime
import re
from zcitools.utils.file_utils import ensure_directory, remove_directory, silent_remove, \
    write_yaml, read_yaml
from ..utils.exceptions import ZCItoolsValueError

"""
Step object is created with step data that specfies step subdirectory and other environment info.
Subdirectory doesn't have to exist. In that case base class will create it.

Step subdirectory contains file description.yml which describes data step contains and environment project data.
description.yml contains data:
 - data_type : Step class type identifier. Value from <step class>._STEP_TYPE's
 - data      : Contains specific data description. Depends on step data type.
 - project   : Environment data, propagated from zcit.py script.
   - step_name  : Subdirectory name
   - prev_steps : List of step names used to produce (calculate) step's data
   - command    : zcit.py script command used to produce the step
   - cmd        : Arguments part of shell command (after zcit.py) used to produce the step.
"""


class Step:
    _STEP_TYPE = None
    _COLUMN_TYPES = frozenset(['seq_ident', 'str', 'int'])
    _CACHE_PREFIX = '_c_'  # Cache files are prfixed with '_c_'

    def __init__(self, step_data, remove_data=False, update_mode=False):
        self._step_data = step_data
        # step_data['step_name'] is string or list of strings for substeps
        if isinstance(step_data['step_name'], str):
            self._step_name_list = [step_data['step_name']]
            self.directory = step_data['step_name']
        else:
            self._step_name_list = step_data['step_name']
            self.directory = os.path.join(*step_data['step_name'])
        self._update_mode = update_mode

        # Call init data method
        if remove_data:
            remove_directory(self.directory, create=True)
            d = None
        else:
            d = self.get_desription()
            if not d:
                ensure_directory(self.directory)
        if d:
            if d['data_type'] != self._STEP_TYPE:
                raise ZCItoolsValueError(
                    f"Step class of tyep '{self._STEP_TYPE}' created with data of type '{d['data_type']}'!")
            type_desc = d['data']
        else:
            type_desc = None
        #
        self._init_data(type_desc)

        # Check data if exists and step not set in update mode
        if type_desc and not self._update_mode:
            self._check_data()

    def _init_data(self, type_description):
        raise NotImplementedError(f'Method {self.__class__.__name__}._init_data() is not implemented!')

    def _check_data(self):
        print(f'Warning: method {self.__class__.__name__}._check_data() not implemented!')

    #
    def get_step_type(self):
        return self._STEP_TYPE

    def get_step_command(self):
        return self._step_data['command']

    def get_step_needs_editing(self):
        return self._step_data['needs_editing']

    # Description methods
    def save_description(self, type_description, create=True, needs_editing=False):
        pd = dict(self._step_data)
        pd['needs_editing'] = needs_editing
        if create:
            pd['created'] = datetime.datetime.now().isoformat()
            pd['updated'] = None
        else:
            pd['updated'] = datetime.datetime.now().isoformat()
        write_yaml(dict(data_type=self.get_step_type(), data=type_description, project=pd),
                   self.step_file('description.yml'))

    def get_desription(self):
        return read_yaml(self.step_file('description.yml'))

    def get_type_desciption(self):
        d = self.get_desription()
        if d:
            return d['data']

    # Substep methods
    def get_substep_step_data(self, step_name):
        return dict(step_name=step_name)  # , prev_steps=None, command=None, command_args=None, cmd=None)

    def create_substep(self, step_cls, local_step_name, remove_data=False, update_mode=False):
        return step_cls(self.get_substep_step_data(self._step_name_list + [local_step_name]),
                        remove_data=remove_data, update_mode=update_mode)

    def read_substep(self, local_step_name):
        from . import read_step
        return read_step(self._step_name_list + [local_step_name])

    # Commonn file methods
    def absolute_path(self):
        return os.path.abspath(self.directory)

    def step_file(self, f):
        return os.path.join(*self._step_name_list, f)

    def strip_step_dir(self, f):
        assert f.startswith(self.directory), (f, self.directory)
        return f[(len(self.directory) + 1):]

    def strip_step_dir_files(self, files):
        return [self.strip_step_dir(f) for f in files]

    @classmethod
    def _is_cache_file(cls, f):
        return f.startswith(cls._CACHE_PREFIX)

    def cache_file(self, f):
        return self.step_file(self._CACHE_PREFIX + f)

    def step_files(self, not_cached=False, matches=None):
        # Returns list of step's filenames relative to step subdirectory
        if not_cached:
            files = [f for f in os.listdir(self.directory) if not self._is_cache_file(f)]
        else:
            files = os.listdir(self.directory)
        if matches:
            pattern = re.compile(matches)
            files = [f for f in files if pattern.search(f)]
        return files

    def step_subdirectories(self):
        return [f for f in os.listdir(self.directory) if os.path.isdir(os.path.join(self.directory, f))]

    def remove_cache_files(self):
        for f in self.step_files():
            if self._is_cache_file(f):
                silent_remove(self.step_file(f))

    def get_cached_records(self, cache, record_idents, info=False):
        if cache:
            return cache.get_records(record_idents, self.directory, info=info)
        return record_idents

    #
    def show_data(self, params=None):
        print(f'{self.__class__.__name__}.show_data() not implemented!')
