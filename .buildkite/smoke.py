from importlib.metadata import version
from pathlib import Path
import sys

import more_itertools as mi


package = Path(mi.__file__).resolve().parent
assert package.is_relative_to(Path(sys.prefix).resolve()), package
assert version('more-itertools') == mi.__version__
assert (package / 'py.typed').is_file()
assert (package / 'more.pyi').is_file()
assert list(mi.chunked(range(5), 2)) == [[0, 1], [2, 3], [4]]
assert mi.first(iter([7, 3])) == 7
assert mi.last(iter([7, 3])) == 3
assert list(mi.take(3, iter(range(10)))) == [0, 1, 2]
print(
    f'Installed wheel {mi.__version__}: metadata, type stubs and API smoke checks passed'
)
