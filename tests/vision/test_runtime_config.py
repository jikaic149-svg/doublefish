import os
import sys
import unittest


PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
VISION_DIR = os.path.join(PROJECT_DIR, "VISION")
RUNTIME_DIR = os.path.join(VISION_DIR, "runtime")
if RUNTIME_DIR not in sys.path:
    sys.path.insert(0, RUNTIME_DIR)

from config import YOLO_MODEL_PATH  # noqa: E402


class RuntimeConfigTests(unittest.TestCase):
    def test_yolo_model_path_is_relative_to_runtime_directory(self):
        self.assertFalse(os.path.isabs(YOLO_MODEL_PATH))
        model_path = os.path.normpath(os.path.join(RUNTIME_DIR, YOLO_MODEL_PATH))
        self.assertEqual(model_path, os.path.join(VISION_DIR, "models", "best.pt"))
        self.assertTrue(os.path.isfile(model_path))


if __name__ == "__main__":
    unittest.main()
