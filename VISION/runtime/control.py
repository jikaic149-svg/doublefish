"""RoboFish transport and the data-only tracking control session."""

from __future__ import annotations

import json
import queue
import threading
import time
import urllib.parse
import urllib.request

import numpy as np

from config import ROBOFISH_IP, ROBOFISH_PORT


class RoboFishComm:
    def __init__(self, ip=ROBOFISH_IP, port=ROBOFISH_PORT):
        self.ip = ip
        self.port = port
        self.base_url = f"http://{ip}:{port}"
        self.cmd_queue = queue.Queue(maxsize=1)
        self.stopped = False
        self.mcu_hz = 0.0
        self._last_send_t = time.time()
        self._last_cmd_t = 0.0
        self._last_params = None
        self.vision_seq = 0
        self._state_lock = threading.Lock()
        self._request_lock = threading.Lock()
        self._control_session = 0
        self._motion_enabled = False
        self.thread = threading.Thread(target=self._worker_loop, daemon=True)
        self.thread.start()
        print(f"RoboFish 机器鱼 HTTP PID 控制接口准备就绪 -> 目标地址: {self.base_url}")

    def _request_control(self, variable, value=1, timeout=0.3):
        query_string = urllib.parse.urlencode({"var": variable, "val": value})
        url = f"{self.base_url}/control?{query_string}"
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "RoboFish-Visual-Tracker",
                "Connection": "close",
            },
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8", errors="replace").strip()

    def _request_vision_pid(
        self,
        sequence,
        x_error_m,
        y_error_m,
        speed_mps,
        curve_severity,
        brake_request,
        timeout=0.3,
    ):
        query_string = urllib.parse.urlencode({
            "seq": int(sequence),
            "x_error": f"{float(x_error_m):.4f}",
            "y_error": f"{float(y_error_m):.4f}",
            "speed": f"{float(speed_mps):.4f}",
            "curve": f"{float(curve_severity):.3f}",
            "brake": 1 if brake_request else 0,
        })
        url = f"{self.base_url}/vision_pid?{query_string}"
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "RoboFish-Visual-Tracker",
                "Connection": "close",
            },
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not payload.get("ok") or int(payload.get("seq", -1)) != int(sequence):
            raise RuntimeError(f"invalid vision PID ACK: {payload}")
        return payload

    def _worker_loop(self):
        while not self.stopped:
            try:
                params = self.cmd_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                with self._request_lock:
                    if not self._command_is_current(params):
                        continue
                    if params.get("kind") == "vision_pid":
                        request_started = time.perf_counter()
                        payload = self._request_vision_pid(
                            params["seq"],
                            params["x_error"],
                            params["y_error"],
                            params["speed"],
                            params["curve"],
                            params["brake"],
                            timeout=0.3,
                        )
                        latency_ms = (time.perf_counter() - request_started) * 1000.0
                        print(
                            f"[VISION ACK] seq={payload['seq']} "
                            f"applied={payload.get('applied_seq', '-')} "
                            f"esc={payload.get('esc', '-')}° "
                            f"RTT={latency_ms:.1f}ms"
                        )
                    else:
                        action_map = {
                            "forward": "servo_forward",
                            "backward": "servo_backward",
                            "left": "servo_left",
                            "right": "servo_right",
                            "mode_bionic": "mode",
                            "mode_prop": "mode",
                            "mode_hybrid": "mode",
                        }
                        self._request_control(action_map[params["action"]], timeout=0.2)

                now = time.time()
                dt = now - self._last_send_t
                if dt > 0:
                    self.mcu_hz = 0.9 * self.mcu_hz + 0.1 * (1.0 / dt)
                self._last_send_t = now
            except Exception as error:
                if params.get("kind") == "vision_pid":
                    print(
                        f"[VISION ACK 失败] seq={params.get('seq', '-')} "
                        f"x={float(params.get('x_error', 0.0)):+.4f}m "
                        f"y={float(params.get('y_error', 0.0)):.4f}m "
                        f"错误={error}"
                    )
                else:
                    print(f"[HTTP 发送失败] 无法连通机器鱼 ({self.base_url}): {error}")

    def get_mcu_hz(self):
        if time.time() - self._last_send_t > 1.5:
            self.mcu_hz *= 0.5
        return round(self.mcu_hz, 1)

    def _command_is_current(self, params):
        if params.get("kind") != "vision_pid":
            return True
        with self._state_lock:
            return (
                self._motion_enabled
                and params.get("session") == self._control_session
            )

    def _clear_queue(self):
        while not self.cmd_queue.empty():
            try:
                self.cmd_queue.get_nowait()
            except queue.Empty:
                break

    def _send_async(self, params):
        now = time.time()
        is_stop = params.get("action") == "stop"
        if not is_stop and (now - self._last_cmd_t < 0.1):
            return False
        self._last_cmd_t = now
        if params.get("kind") == "vision_pid":
            with self._state_lock:
                if not self._motion_enabled:
                    return False
                params = dict(params, session=self._control_session)
        self._last_params = params
        self._clear_queue()
        try:
            self.cmd_queue.put_nowait(params)
            return True
        except queue.Full:
            return False

    def set_mode(self, motion_mode):
        mode_map = {
            "bionic": "mode_bionic",
            "propeller": "mode_prop",
            "prop": "mode_prop",
            "hybrid": "mode_hybrid",
        }
        target_mode = mode_map.get(str(motion_mode).lower(), "mode_bionic")
        print(f"[HTTP 下发] 切换机器鱼模式为: {target_mode}")
        self._send_async({"action": target_mode})

    def ensure_hybrid_mode(self):
        """Start a new control session after a serialized propulsion stop."""
        with self._state_lock:
            self._control_session += 1
            session = self._control_session
            self._motion_enabled = False
        self._clear_queue()
        try:
            with self._request_lock:
                self._request_control("servo_stop", timeout=0.5)
            with self._state_lock:
                if self._control_session != session:
                    return False
                self._motion_enabled = True
            print(
                f"[HTTP 视觉准备] 会话 {session} 已建立，"
                "旧 PID 命令全部失效"
            )
            return True
        except Exception as error:
            print(f"[HTTP 视觉准备失败] {error}")
            return False

    def send_command(self, cmd_str):
        if cmd_str in ["stop", "emergency_stop"]:
            print("[HTTP 下发] 机器鱼急停/停止推进")
            return self.stop_now()

    def stop_now(self):
        """Invalidate old PID work, then serialize STOP behind any in-flight request."""
        with self._state_lock:
            self._control_session += 1
            self._motion_enabled = False
        self._last_params = None
        self._clear_queue()
        try:
            with self._request_lock:
                self._request_control("servo_stop", timeout=0.5)
            print("[HTTP 反馈] 推进已停止")
            return True
        except Exception as error:
            print(f"[HTTP 停止失败] {error}")
            return False

    def process_tracking_error(
        self,
        cross_m=None,
        along_m=None,
        dist_m=None,
        speed_mps=0.0,
        curve_severity=0.0,
        brake_request=False,
        cross_track_m=0.0,
        heading_error_deg=0.0,
        path_curvature_per_m=0.0,
        steering_demand=0.0,
        *,
        s_m=None,
        f_m=None,
        remaining_m=None,
        yaw_rate_rps=0.0,
        desired_yaw_rate_rps=0.0,
    ):
        """Send a Frenet S/F sample through the legacy MCU wire adapter.

        The controller boundary is ``(s, f, heading, speed, yaw_rate)``.
        The ESP32 protocol still calls its two scalar inputs ``x_error`` and
        ``y_error``; conversion is isolated here until firmware accepts a
        native Frenet message.
        """
        if f_m is None:
            f_m = cross_m if cross_m is not None else 0.0
        if s_m is None:
            s_m = along_m if along_m is not None else 0.0
        if remaining_m is None:
            remaining_m = dist_m if dist_m is not None else 0.0
        self.vision_seq = (self.vision_seq + 1) & 0x7FFFFFFF
        queued = self._send_async({
            "kind": "vision_pid",
            "seq": self.vision_seq,
            "x_error": float(np.clip(f_m, -5.0, 5.0)),
            "y_error": float(np.clip(remaining_m, 0.0, 5.0)),
            "speed": float(np.clip(speed_mps, 0.0, 5.0)),
            "curve": float(np.clip(curve_severity, 0.0, 1.0)),
            "brake": bool(brake_request),
        })
        if queued:
            print(
                f"[VISION 入队] seq={self.vision_seq} "
                f"x={cross_m:+.3f}m y={dist_m:.3f}m "
                f"v={speed_mps:.2f}m/s 离={cross_track_m:.2f}m "
                f"角={heading_error_deg:+.0f}° "
                f"曲率={path_curvature_per_m:+.2f}/m "
                f"转向={steering_demand:+.2f} "
                f"制动={'是' if brake_request else '否'}"
            )
        return queued

    def close(self):
        self.stop_now()
        self.stopped = True
        if self.thread.is_alive():
            self.thread.join(timeout=1.0)


from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class ControlDecision:
    status: str
    guidance: Optional[dict[str, Any]] = None
    pid: Optional[dict[str, Any]] = None
    stop_required: bool = False
    message: Optional[str] = None


class VisionControlSession:
    def __init__(self, path_guidance, command_interval_s: float = 0.10):
        self.path_guidance = path_guidance
        self.command_interval_s = float(command_interval_s)
        self.active = False
        self.status = "READY"
        self.segment = 0
        self._last_control_t = float("-inf")

    def prepare(self, path_world, position, frame_time, heading):
        """Prepare geometry without enabling propulsion."""
        self.active = False
        self.segment = 0
        return self.path_guidance.start(
            path_world, position, frame_time, heading
        )

    def activate(self, initial_guidance) -> None:
        self.active = True
        self.status = "HYBRID TRACKING"
        self.segment = int(initial_guidance["seg_index"])
        self._last_control_t = float("-inf")

    def stop(self, status="STOPPED", *, clear_path=False) -> bool:
        """Enter a non-driving state and report whether propulsion may exist."""
        was_active = self.active
        self.active = False
        self.status = status
        if clear_path:
            self.path_guidance.clear()
            self.segment = 0
        return was_active

    def update(
        self,
        *,
        calibrated: bool,
        position,
        frame_time: float,
        now: float,
        allow_course_update: bool,
        speed_mps: float,
    ) -> ControlDecision:
        if not self.active:
            return ControlDecision(status=self.status)
        if not calibrated:
            self.stop("UNCALIBRATED")
            return ControlDecision(
                status=self.status,
                stop_required=True,
                message="场地标定失效，循迹已停止。",
            )
        if position is None:
            self.stop("TARGET LOST")
            return ControlDecision(
                status=self.status,
                stop_required=True,
                message="视觉目标失效，循迹已停止。",
            )
        if not self.path_guidance.prepared:
            self.stop("PATH INVALID")
            return ControlDecision(
                status=self.status,
                stop_required=True,
                message="路径引导状态失效，循迹已停止。",
            )

        guidance = self.path_guidance.update(
            position,
            frame_time,
            allow_course_update=allow_course_update,
            speed_mps=float(speed_mps),
        )
        self.segment = int(guidance["seg_index"])
        if guidance["settled"]:
            self.stop("ARRIVED")
            return ControlDecision(
                status=self.status,
                guidance=guidance,
                stop_required=True,
                message="已进入终点停止圈。",
            )

        pid = None
        if now - self._last_control_t >= self.command_interval_s:
            # The navigation layer exposes one semantic turn command.  The
            # legacy flat fields remain as a compatibility fallback for
            # replay fixtures and older guidance providers.
            command = guidance.get("command") or {}
            frenet = guidance.get("frenet") or {}
            s_m = float(frenet.get("s_m", guidance.get("s_m", guidance["along_m"])))
            f_m = float(frenet.get(
                "f_m", guidance.get(
                    "f_m",
                    guidance.get(
                        "signed_cross_track_error_m",
                        command.get("protocol_x_error_m", guidance.get("x_error_m", 0.0)),
                    ),
                )
            ))
            heading_error_deg = float(frenet.get(
                "heading_error_deg", guidance["heading_error_deg"]
            ))
            yaw_rate_rps = float(frenet.get("yaw_rate_rps", guidance.get("yaw_rate_rps", 0.0)))
            desired_yaw_rate_rps = float(command.get(
                "desired_yaw_rate_rps", guidance.get("desired_yaw_rate_rps", 0.0)
            ))
            speed_value = frenet.get("speed_mps", guidance.get("speed_mps"))
            if speed_value is None:
                speed_value = speed_mps
            remaining_m = float(command.get(
                "drive_distance_m", guidance["drive_distance_m"]
            ))
            pid = {
                # Canonical S/F fields consumed by the transport adapter.
                "s_m": s_m,
                "f_m": f_m,
                "remaining_m": remaining_m,
                "heading_error_deg": heading_error_deg,
                "yaw_rate_rps": yaw_rate_rps,
                "desired_yaw_rate_rps": desired_yaw_rate_rps,
                "speed_mps": float(speed_value),
                "curve_severity": command.get(
                    "curve_severity", guidance["curve_severity"]
                ),
                "brake_request": command.get(
                    "brake_request", guidance["brake_request"]
                ),
                "cross_track_m": guidance.get("cross_track_m", abs(f_m)),
                "path_curvature_per_m": guidance["path_curvature_per_m"],
                "steering_demand": command.get(
                    "turn_demand", guidance["steering_demand"]
                ),
                # Compatibility aliases for existing tests, logging and
                # callers that still use the old names.
                "cross_m": f_m,
                "along_m": s_m,
                "dist_m": remaining_m,
            }
            self._last_control_t = now
        self.status = (
            "HYBRID BRAKING" if guidance["brake_request"]
            else "HYBRID TRACKING"
        )
        return ControlDecision(
            status=self.status,
            guidance=guidance,
            pid=pid,
        )
