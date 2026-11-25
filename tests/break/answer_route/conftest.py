"""tests/break/answer_route: the break tests of the families «answer» and «the road to the model, the search, the reserve» (U237). They use the stands of tests/ (helpers_always_answer, helpers_s6_fault)."""
import os
import sys

_TESTS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_HERE = os.path.dirname(os.path.abspath(__file__))
for _path in (_TESTS, _HERE):
    if _path not in sys.path:
        sys.path.insert(0, _path)
