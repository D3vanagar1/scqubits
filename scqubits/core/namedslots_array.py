# namedslots_array.py
#
# This file is part of scqubits.
#
#    Copyright (c) 2019 and later, Jens Koch and Peter Groszkowski
#    All rights reserved.
#
#    This source code is licensed under the BSD-style license found in the
#    LICENSE file in the root directory of this source tree.
############################################################################

import math

from collections import OrderedDict
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple, Union

import numpy as np

from numpy import ndarray

from scqubits.io_utils.fileio import IOData
from scqubits.io_utils.fileio_serializers import Serializable
from scqubits.utils.misc import Number


NpIndex = Union[int, slice]
NpIndexTuple = Tuple[NpIndex, ...]
NpIndices = Union[NpIndex, NpIndexTuple]
NpSliceEntry = Union[int, None]

GIndex = Union[Number, slice]
GIndexTuple = Tuple[GIndex, ...]
GIndices = Union[GIndex, GIndexTuple]
GSliceEntry = Union[Number, str, None]

GIndexObjectTuple = Tuple["GIndexObject", ...]


def is_std_slice(slice_obj: slice) -> bool:
    if slice_obj.start and not isinstance(slice_obj.start, int):
        return False
    if slice_obj.stop and not isinstance(slice_obj.stop, int):
        return False
    if slice_obj.step and not isinstance(slice_obj.step, int):
        return False
    return True


def npindices(multi_index: GIndex) -> bool:
    if isinstance(multi_index, int):
        return True
    elif isinstance(multi_index, slice):
        return is_std_slice(multi_index)
    elif isinstance(multi_index, tuple):
        return all([npindices(index) for index in multi_index])
    return False


def idx_for_value(value: Number, param_vals: ndarray) -> int:
    location = np.abs(param_vals - value).argmin()
    if math.isclose(param_vals[location], value):
        return location
    raise ValueError(
        "No matching entry for parameter value {} in the array.".format(value)
    )


class Parameters:
    """Convenience class for maintaining multiple parameter sets (names, values,
    ordering. Used in ParameterSweep as `.parameters`. Can access in several ways:
    Parameters[<name str>] = parameter values under this name
    Parameters[<index int>] = parameter values saved as the index-th set
    Parameters[<slice> or tuple(int)] = slice over the list of parameter sets
    Mostly meant for internal use inside ParameterSweep.

    paramvals_by_name:
        dictionary giving names of and values of parameter sets (note problem with
        ordering in python dictionaries
    paramnames_list:
        optional list of same names as in dictionary to set ordering
    """

    def __init__(
        self,
        paramvals_by_name: Dict[str, ndarray],
        paramnames_list: Optional[List[str]] = None,
    ) -> None:
        if paramnames_list is not None:
            self.paramnames_list = paramnames_list
        else:
            self.paramnames_list = list(paramvals_by_name.keys())

        self.names = self.paramnames_list
        self.ordered_dict = OrderedDict(
            [(name, paramvals_by_name[name]) for name in self.names]
        )
        self.paramvals_by_name = self.ordered_dict
        self.index_by_name = {
            name: index for index, name in enumerate(self.paramnames_list)
        }
        self.name_by_index = {
            index: name for index, name in enumerate(self.paramnames_list)
        }
        self.paramvals_by_index = {
            self.index_by_name[name]: param_vals
            for name, param_vals in self.paramvals_by_name.items()
        }

    def __getitem__(self, key):
        if isinstance(key, str):
            return self.paramvals_by_name[key]
        if isinstance(key, int):
            return self.paramvals_by_name[self.paramnames_list[key]]
        if isinstance(key, slice):
            sliced_paramnames_list = self.paramnames_list[key]
            return [self.paramvals_by_name[name] for name in sliced_paramnames_list]
        if isinstance(key, tuple):
            return [
                self.paramvals_by_name[self.paramnames_list[index]][key[index]]
                for index in range(len(self))
            ]

    def __len__(self):
        return len(self.paramnames_list)

    def __iter__(self):
        return iter(self.paramvals_list)

    @property
    def counts_by_name(self):
        return {
            name: len(self.paramvals_by_name[name])
            for name in self.paramvals_by_name.keys()
        }

    @property
    def ranges(self) -> List[Iterable]:
        return [range(count) for count in self.counts]

    @property
    def paramvals_list(self):
        return [self.paramvals_by_name[name] for name in self.paramnames_list]

    def get_index(self, value, slotindex):
        location = np.abs(self[slotindex] - value).argmin()
        return location

    @property
    def counts(self):
        return tuple(len(paramvals) for paramvals in self)

    def create_reduced(self, fixed_parametername_list, fixed_values=None):
        if fixed_values is not None:
            fixed_values = [np.asarray(value) for value in fixed_values]
        else:
            fixed_values = [
                np.asarray([self[name][0]]) for name in fixed_parametername_list
            ]

        reduced_paramvals_by_name = {name: self[name] for name in self.paramnames_list}
        for index, name in enumerate(fixed_parametername_list):
            reduced_paramvals_by_name[name] = fixed_values[index]
        return Parameters(reduced_paramvals_by_name)

    def create_sliced(self, np_indices: NpIndices):
        parameter_array = np.asarray(self.paramvals_list, dtype=object).copy()
        for index, np_index in enumerate(np_indices):
            parameter_array[index] = parameter_array[index][np_index]

        reduced_paramvals_by_name = {}
        for index, name in enumerate(self.paramnames_list):
            paramvals = parameter_array[index]
            if isinstance(paramvals, ndarray) and len(paramvals) > 1:
                reduced_paramvals_by_name[name] = paramvals

        return Parameters(reduced_paramvals_by_name)


class GIndexObject:
    def __init__(
        self, entry: GIndex, parameters: Parameters, slot: Optional[int] = None
    ):
        self.entry = entry
        self.parameters = parameters
        self.slot = slot
        self.name = None
        self.type, self.std_index = self.std(entry)

    def std_slice_entry(self, slice_entry: GSliceEntry) -> NpSliceEntry:
        if isinstance(slice_entry, (float, complex)):
            return idx_for_value(slice_entry, self.parameters[self.slot])
        if isinstance(slice_entry, int):
            return slice_entry
        if slice_entry is None:
            return None
        raise TypeError("Invalid slice entry: {}".format(slice_entry))

    def std(self, entry: GIndex) -> Tuple[str, NpIndex]:
        # <int>
        if isinstance(entry, int):
            return "int", entry

        # <float> or <complex>
        if isinstance(entry, (float, complex)):
            return "val", idx_for_value(self.entry, self.parameters[self.slot])

        # slice(<str>, ...)
        if isinstance(entry, slice) and isinstance(entry.start, str):
            self.name = entry.start
            start = self.std_slice_entry(entry.stop)
            stop = self.std_slice_entry(entry.step)
            if stop is None:
                return "slice.name", start
            return "slice.name", slice(start, stop, None)

        # slice(<Number> or <None>, ...)
        if isinstance(entry, slice):
            start = self.std_slice_entry(entry.start)
            stop = self.std_slice_entry(entry.stop)
            if entry.step is None or isinstance(entry.step, int):
                step = self.std_slice_entry(entry.step)
            else:
                raise TypeError(
                    "slice.step can only be int or None. Found {} "
                    "instead.".format(entry.step)
                )
            return "slice", slice(start, stop, step)

        raise TypeError("Invalid index: {}".format(entry))


class NamedSlotsNdarray(np.ndarray, Serializable):
    """
    This mixin class applies to multi-dimensional arrays, for which the leading M
    dimensions are each associated with a slot name and a corresponding array of slot
    values (float or complex or str). All standard slicing of the multi-dimensional
    array with integer-valued indices is supported as usual, e.g.

        some_array[0, 3:-1, -4, ::2]

    Slicing of the multi-dimensional array associated with named sets of values is
    extended in two ways:

    (1) Value-based slicing
    Integer indices other than the `step` index may be
    replaced by a float or a complex number or a str. This prompts a lookup and
    substitution by the integer index representing the location of the closest
    element (as measured by the absolute value of the difference for numbers,
    and an exact match for str) in the set of slot values.

    As an example, consider the situation of two named value sets

        values_by_slotname = {'param1': np.asarray([-4.4, -0.1, 0.3, 10.0]),
                              'param2': np.asarray([0.1*1j, 3.0 - 4.0*1j, 25.0])}

    Then, the following are examples of value-based slicing:

        some_array[0.25, 0:2]                   -->     some_array[2, 0:2]
        some_array[-3.0, 0.0:(2.0 - 4.0*1j)]    -->     some_array[0, 0:1]


    (2) Name-based slicing
    Sometimes, it is convenient to refer to one of the slots
    by its name rather than its position within the multiple sets. As an example, let

        values_by_slotname = {'ng': np.asarray([-0.1, 0.0, 0.1, 0.2]),
                             'flux': np.asarray([-1.0, -0.5, 0.0, 0.5, 1.0])}

    If we are interested in the slice of `some_array` obtained by setting 'flux' to a
    value or the value associated with a given index, we can now use:

        some_array['flux':0.5]            -->    some_array[:, 1]
        some_array['flux'::2, 'ng':-1]    -->    some_array[-1, :2]

    Name-based slicing has the format `<name str>:start:stop`  where `start` and
    `stop` may be integers or make use of value-based slicing. Note: the `step`
    option is not available in name-based slicing. Name-based and standard
    position-based slicing cannot be combined: `some_array['name1':3, 2:4]` is not
    supported. For such mixed- mode slicing, use several stages of slicing as in
    `some_array['name1':3][2:4]`.

    A special treatment is reserved for a pure string entry in position 0: this
    string will be directly converted into an index via the corresponding
    values_by_slotindex.
    """

    parameters: Parameters
    data_callback: Union[ndarray, Callable]

    def __new__(cls, input_array: np.ndarray, values_by_name: Dict[str, Iterable]):
        implied_shape = tuple(len(values) for name, values in values_by_name.items())
        if input_array.shape[0 : len(values_by_name)] != implied_shape:
            raise ValueError(
                "Given input array with shape {} not compatible with "
                "provided dict calling for shape {}. values_by_name: {}".format(
                    input_array.shape, implied_shape, values_by_name
                )
            )

        obj = np.asarray(input_array).view(cls)

        obj.parameters = Parameters(values_by_name)
        obj.data_callback = None
        return obj

    def __array_finalize__(self, obj):
        if obj is None:
            return

        self.parameters = getattr(obj, "parameters", None)
        self.data_callback = getattr(obj, "data_callback", None)

    def __getitem__(self, multi_index: GIndices) -> Any:
        """Overwrites the magic method for element selection and slicing to support
        the extended slicing options."""
        if isinstance(multi_index, int):
            return super().__getitem__(multi_index)

        if not isinstance(multi_index, tuple):
            multi_index = (multi_index,)
        gidx_obj_tuple = tuple(
            GIndexObject(entry, self.parameters, slot=slot_index)
            for slot_index, entry in enumerate(multi_index)
        )
        np_indices = self._to_std_index_tuple(gidx_obj_tuple)
        obj = super().__getitem__(np_indices)
        if isinstance(obj, NamedSlotsNdarray):
            obj.parameters = self.parameters.create_sliced(np_indices)
        return obj

    @classmethod
    def deserialize(cls, io_data: IOData) -> "NamedSlotsNdarray":
        """
        Take the given IOData and return an instance of the described class, initialized
        with the data stored in io_data.
        """
        input_array = np.asarray(io_data.objects["input_array"], dtype=object)
        values_by_name = io_data.objects["values_by_name"]
        return NamedSlotsNdarray(input_array, values_by_name)

    def serialize(self) -> IOData:
        """
        Convert the content of the current class instance into IOData format.
        """
        import scqubits.io_utils.fileio as io

        typename = type(self).__name__
        io_attributes = None
        io_ndarrays = None
        objects = {
            "input_array": self.tolist(),
            "values_by_name": self.parameters.paramvals_by_name,
        }
        return io.IOData(typename, io_attributes, io_ndarrays, objects=objects)

    def _name_based_to_std_index_tuple(
        self, multi_index: GIndexObjectTuple
    ) -> NpIndexTuple:
        """Converts a name-based multi-index into a position-based multi-index."""
        converted_multi_index = [slice(None)] * self.slot_count
        for gidx_object in multi_index:
            if gidx_object.type != "slice.name":
                raise TypeError("If one index is name-based, all indices must be.")
            slot_index = self.parameters.index_by_name[gidx_object.name]
            converted_multi_index[slot_index] = gidx_object.std_index

        return tuple(converted_multi_index)

    def _to_std_index_tuple(self, multi_index: GIndexObjectTuple) -> NpIndexTuple:
        """Takes an extended-syntax multi-index entry and converts it to a standard
        position-based multi-index_entry with only integer-valued indices."""
        # inspect first index_entry to determine whether multi-index entry is name-based
        first_gidx = multi_index[0]

        if first_gidx.type == "slice.name":  # if one is name based, all must be
            return self._name_based_to_std_index_tuple(multi_index)

        return tuple(gidx.std_index for gidx in multi_index)

    @property
    def slot_count(self) -> int:
        return len(self.parameters.paramvals_by_name)
