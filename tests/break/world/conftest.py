"""tests/break/world: the break tests of the classes of the owner's own breaking that the families «question», «answer/road» and «portion/speech» did not take (U237, breakD)."""
import os
import sys

_TESTS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROUTE = os.path.join(os.path.dirname(_HERE), 'answer_route')
_PORTION = os.path.join(os.path.dirname(_HERE), 'portion_speech')     # bps_common, the kit bw_common imports
for _path in (_TESTS, _HERE, _ROUTE, _PORTION):
    if _path not in sys.path:
        sys.path.insert(0, _path)
