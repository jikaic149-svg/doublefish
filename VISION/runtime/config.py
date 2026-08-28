"""Central configuration for the desktop RoboFish vision application.

Keeping deployment values here prevents camera, networking, and control
services from importing the main UI module just to read constants.
"""

from __future__ import annotations

import os


WORK_DIR = os.path.dirname(os.path.abspath(__file__))
VISION_DIR = os.path.dirname(WORK_DIR)
REPO_DIR = os.path.dirname(VISION_DIR)
CONFIG_DIR = os.path.join(VISION_DIR, "configs")
MODEL_DIR = os.path.join(VISION_DIR, "models")
OUTPUT_DIR = os.path.join(REPO_DIR, "output", "vision")
CACHE_DIR = os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.join(VISION_DIR, ".cache")),
    "RoboFishVision",
)
os.makedirs(CONFIG_DIR, exist_ok=True)
os.makedirs(MODEL_DIR, exist_ok=True)
os.makedirs(CACHE_DIR, exist_ok=True)

# Keep generated third-party caches outside the source directory.
os.environ["YOLO_CONFIG_DIR"] = os.path.join(CACHE_DIR, "ultralytics")
os.environ["MPLCONFIGDIR"] = os.path.join(CACHE_DIR, "matplotlib")
os.environ["OPENCV_VIDEOIO_MSMF_ENABLE_HW_TRANSFORMS"] = "0"

# Camera capture.
TARGET_FPS = 60
TARGET_WIDTH = 640
TARGET_HEIGHT = 480
CAMERA_LATENCY_S = 0.30
CAMERA_LATENCY_MAX_PREDICTION_M = 0.12
CAMERA_STALE_TIMEOUT_S = 0.35
ENABLE_CLAHE_DEFAULT = False

# Pool dimensions and ArUco corner mapping.
PHYSICAL_WIDTH = 3.14
PHYSICAL_HEIGHT = 1.6
MARKER_TL = 1
MARKER_TR = 2
MARKER_BR = 4
MARKER_BL = 3

# Fish detection and fixed marker tracking.
# The runtime model is the selected V15 checkpoint from the training experiments.
# ``VisionApplication.run`` changes into ``VISION/runtime`` before startup, so
# this stays a portable project-relative path instead of embedding a machine
# specific absolute path in the YOLO invocation.
YOLO_MODEL_PATH = os.path.join("..", "models", "best.pt")
YOLO_CONF_THRESHOLD = 0.18
YOLO_IMG_SIZE = 640
YOLO_DEVICE = 0
YOLO_DETECT_INTERVAL_S = 0.20
MARKER_PROFILE_PATH = os.path.join(CONFIG_DIR, "marker_profile.local.json")
TURN_CALIBRATION_PATH = os.path.join(CONFIG_DIR, "turn_calibration.local.json")

# Tablet and RoboFish communication.
TABLET_TCP_HOST = "0.0.0.0"
TABLET_TCP_PORT = 9998
ROBOFISH_IP = "192.168.4.1"
ROBOFISH_PORT = 80

# Position filtering.
POS_SMOOTHING_ALPHA = 0.4

# MJPEG streaming.
MJPEG_PORT = 8090
MJPEG_STREAM_WIDTH = 960
MJPEG_STREAM_HEIGHT = 540
MJPEG_JPEG_QUALITY = 50
MJPEG_MAX_FPS = 30

# Local preview.
DISPLAY_MAX_FPS = 30
