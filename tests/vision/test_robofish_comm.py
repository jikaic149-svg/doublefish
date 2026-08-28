import os
import sys
import threading
import time
import unittest
from unittest import mock


PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
VISION_DIR = os.path.join(PROJECT_DIR, "VISION")
RUNTIME_DIR = os.path.join(VISION_DIR, "runtime")
if RUNTIME_DIR not in sys.path:
    sys.path.insert(0, RUNTIME_DIR)

from control import RoboFishComm


class RoboFishCommTests(unittest.TestCase):
    def test_stop_is_serialized_after_inflight_pid_and_invalidates_session(self):
        pid_started = threading.Event()
        release_pid = threading.Event()
        calls = []

        def fake_pid(*args, **kwargs):
            del args, kwargs
            calls.append("pid-start")
            pid_started.set()
            release_pid.wait(1.0)
            calls.append("pid-end")
            return {"ok": True, "seq": 1, "applied_seq": 1}

        def fake_control(_self, variable, value=1, timeout=0.3):
            del value, timeout
            calls.append(variable)
            return "ok"

        with (
            mock.patch.object(RoboFishComm, "_request_vision_pid", fake_pid),
            mock.patch.object(RoboFishComm, "_request_control", fake_control),
        ):
            comm = RoboFishComm(ip="127.0.0.1", port=80)
            try:
                self.assertTrue(comm.ensure_hybrid_mode())
                comm.process_tracking_error(0.1, 0.0, 0.5)
                self.assertTrue(pid_started.wait(1.0))

                stopped = threading.Event()

                def stop_worker():
                    comm.stop_now()
                    stopped.set()

                thread = threading.Thread(target=stop_worker)
                thread.start()
                time.sleep(0.02)
                self.assertFalse(stopped.is_set())
                release_pid.set()
                thread.join(1.0)

                self.assertTrue(stopped.is_set())
                self.assertLess(calls.index("pid-end"), len(calls) - 1)
                self.assertEqual(calls[-1], "servo_stop")
                self.assertFalse(comm.process_tracking_error(0.1, 0.0, 0.5))
            finally:
                release_pid.set()
                comm.close()


if __name__ == "__main__":
    unittest.main()

