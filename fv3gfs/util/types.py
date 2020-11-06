from typing import Iterable, TypeVar, Tuple
from typing_extensions import Protocol

Array = TypeVar("Array")


class Allocator(Protocol):
    def __call__(self, shape: Iterable[int], dtype: type) -> Array:
        pass


class NumpyModule(Protocol):

    empty: Allocator
    zeros: Allocator
    ones: Allocator

    def rot90(self, m: Array, k: int = 1, axes: Tuple[int, int] = (0, 1)):
        ...
