import os
import sys
import unittest


PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
VISION_DIR = os.path.join(PROJECT_DIR, "VISION")
RUNTIME_DIR = os.path.join(VISION_DIR, "runtime")
if RUNTIME_DIR not in sys.path:
    sys.path.insert(0, RUNTIME_DIR)

from ui import create_runtime_state


class VisionRuntimeStateTests(unittest.TestCase):
    def test_each_run_gets_independent_mutable_state(self):
        first = create_runtime_state("INVALID")
        second = create_runtime_state("INVALID")

        first.drawn_path["pixels"].append((1, 2))
        first.pending_actions.append("START")

        self.assertEqual(second.drawn_path["pixels"], [])
        self.assertEqual(list(second.pending_actions), [])
        self.assertEqual(second.frame["reference_source"], "INVALID")

    def test_default_state_has_bounded_trajectory_and_explicit_source(self):
        state = create_runtime_state("NO_REFERENCE")

        self.assertEqual(state.trajectory.maxlen, 150)
        self.assertEqual(state.frame["reference_source"], "NO_REFERENCE")
        self.assertFalse(state.drawn_path["active"])

