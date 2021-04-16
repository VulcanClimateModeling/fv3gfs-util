from __future__ import annotations
from typing import Callable, Iterable, Optional, Dict, Tuple
from ._timing import Timer, NullTimer
import numpy as np
import contextlib
from .utils import is_c_contiguous
from .types import Allocator

BufferKey_t = Tuple[Callable, Iterable[int], type]
BUFFER_CACHE: Dict[BufferKey_t, Buffer] = {}


class Buffer:
    """A buffer cached by default.

    _key: key into cache storage to allow easy re-caching
    array: ndarray allocated
    """

    _key: BufferKey_t
    array: np.ndarray

    def __init__(self, key: BufferKey_t, array: np.ndarray):
        """Init a cacheable buffer.

        Args:
            key: a cache key made out of tuple of allocator (behaving like np.empty), shape and dtype
            array: ndarray of actual data
        """
        self._key = key
        self.array = array

    @classmethod
    def get_from_cache(
        cls, allocator: Allocator, shape: Iterable[int], dtype: type, force_cpu: bool
    ) -> Buffer:
        """Retrieve or insert then retrieve of buffer from cache.

        Args:
            allocator: behaves like a np.empty function, used to allocate memory
            shape: shape of array
            dtype: type of array elements
            force_cpu: allocate only CPU
        """
        if force_cpu:
            allocator = np.empty
        key = (allocator, shape, dtype)
        if key in BUFFER_CACHE and len(BUFFER_CACHE[key]) > 0:
            return BUFFER_CACHE[key].pop()
        else:
            if key not in BUFFER_CACHE:
                BUFFER_CACHE[key] = []
            array = allocator(shape, dtype=dtype)
            assert is_c_contiguous(array)
            return cls(key, array)

    @staticmethod
    def push_to_cache(buffer: Buffer):
        """Push the buffer back into the cache.

        Args:
            buffer: buffer to push back in cache, using internal key
        """
        BUFFER_CACHE[buffer._key].append(buffer)


@contextlib.contextmanager
def array_buffer(
    allocator: Allocator, shape: Iterable[int], dtype: type, force_cpu: bool
):
    """
    A context manager providing a contiguous array, which may be re-used between calls.

    Args:
        allocator: a function with the same signature as numpy.zeros which returns
            an ndarray
        shape: the shape of the desired array
        dtype: the dtype of the desired array

    Yields:
        buffer_array: an ndarray created according to the specification in the args.
            May be retained and re-used in subsequent calls.
    """
    buffer = Buffer.get_from_cache(allocator, shape, dtype, force_cpu)
    yield buffer.array
    Buffer.push_to_cache(buffer)


@contextlib.contextmanager
def send_buffer(
    allocator: Callable,
    array: np.ndarray,
    force_cpu: bool,
    timer: Optional[Timer] = None,
):
    """A context manager ensuring that `array` is contiguous in a context where it is
    being sent as data, copying into a recycled buffer array if necessary.

    Args:
        allocator: a function behaving like numpy.empty
        array: a possibly non-contiguous array for which to provide a buffer
        timer: object to accumulate timings for "pack"

    Yields:
        buffer_array: if array is non-contiguous, a contiguous buffer array containing
            the data from array. Otherwise, yields array.
    """
    if timer is None:
        timer = NullTimer()
    if array is None or is_c_contiguous(array):
        yield array
    else:
        timer.start("pack")
        with array_buffer(allocator, array.shape, array.dtype, force_cpu) as sendbuf:
            sendbuf[:] = array
            # this is a little dangerous, because if there is an exception in the two
            # lines above the timer may be started but never stopped. However, it
            # cannot be avoided because we cannot put those two lines in a with or
            # try block without also including the yield line.
            timer.stop("pack")
            yield sendbuf


@contextlib.contextmanager
def recv_buffer(
    allocator: Callable,
    array: np.ndarray,
    force_cpu: bool,
    timer: Optional[Timer] = None,
):
    """A context manager ensuring that array is contiguous in a context where it is
    being used to receive data, using a recycled buffer array and then copying the
    result into array if necessary.

    Args:
        allocator: a function behaving like numpy.empty
        array: a possibly non-contiguous array for which to provide a buffer
        timer: object to accumulate timings for "unpack"

    Yields:
        buffer_array: if array is non-contiguous, a contiguous buffer array which is
            copied into array when the context is exited. Otherwise, yields array.
    """
    if timer is None:
        timer = NullTimer()
    if array is None or is_c_contiguous(array):
        yield array
    else:
        timer.start("unpack")
        with array_buffer(allocator, array.shape, array.dtype, force_cpu) as recvbuf:
            timer.stop("unpack")
            yield recvbuf
            with timer.clock("unpack"):
                array[:] = recvbuf
