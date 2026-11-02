"""Computer Vision, Face Detection, and Intelligent 9:16 Re-framing."""
from __future__ import annotations

import cv2
import numpy as np
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any

from config import MODELS_DIR

YUNET_PATH = MODELS_DIR / "face_detection_yunet_2023mar.onnx"
_detector = None


def get_face_detector():
    """Load OpenCV YuNet FaceDetectorYN if model exists, else fallback to Haar."""
    global _detector
    if _detector is not None:
        return _detector

    if YUNET_PATH.exists():
        try:
            # Initialize with arbitrary frame size (can be updated per frame)
            _detector = cv2.FaceDetectorYN.create(
                model=str(YUNET_PATH),
                config="",
                input_size=(640, 360),
                score_threshold=0.6,
                nms_threshold=0.3,
                top_k=5000,
            )
            return _detector
        except Exception as e:
            print(f"[vision] Failed to create YuNet detector ({e}), falling back to Haar")

    # Fallback to Haar Cascade
    cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    _detector = cv2.CascadeClassifier(cascade_path)
    return _detector


def detect_faces(frame: np.ndarray) -> List[Dict[str, float]]:
    """Detect all faces in a BGR frame: [{x, y, w, h, conf}]."""
    detector = get_face_detector()
    h, w = frame.shape[:2]

    faces = []
    if isinstance(detector, cv2.FaceDetectorYN):
        detector.setInputSize((w, h))
        _, detections = detector.detect(frame)
        if detections is not None:
            for d in detections:
                box_x, box_y, box_w, box_h = d[0:4]
                conf = float(d[14])
                faces.append({
                    "x": float(max(0, box_x)),
                    "y": float(max(0, box_y)),
                    "w": float(box_w),
                    "h": float(box_h),
                    "conf": conf,
                    "cx": float(box_x + box_w / 2.0),
                    "cy": float(box_y + box_h / 2.0),
                })
    else:  # Haar Cascade
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        boxes = detector.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))
        for (bx, by, bw, bh) in boxes:
            faces.append({
                "x": float(bx), "y": float(by), "w": float(bw), "h": float(bh),
                "conf": 0.8, "cx": float(bx + bw / 2.0), "cy": float(by + bh / 2.0)
            })

    return faces


def calculate_crop_window(
    src_w: int,
    src_h: int,
    target_aspect: Tuple[int, int] = (9, 16),
    face: Optional[Dict[str, float]] = None,
) -> Dict[str, int]:
    """Calculate the 9:16 bounding box inside a 16:9 source frame."""
    target_ratio = target_aspect[0] / target_aspect[1]
    
    # Maximum height we can take
    crop_h = src_h
    crop_w = int(round(crop_h * target_ratio))

    if crop_w > src_w:
        crop_w = src_w
        crop_h = int(round(crop_w / target_ratio))

    # Center crop default
    center_x = (src_w - crop_w) // 2
    center_y = (src_h - crop_h) // 2

    # If face is detected, slide crop_w along X-axis to keep face centered
    if face:
        face_cx = face["cx"]
        # Center crop window around face X
        ideal_x = int(face_cx - crop_w / 2.0)
        center_x = max(0, min(src_w - crop_w, ideal_x))

    return {
        "x": center_x,
        "y": center_y,
        "w": crop_w,
        "h": crop_h,
    }


def calculate_crop_box(
    frame_width: int,
    frame_height: int,
    face_center_x: Optional[float] = None,
    face_center_y: Optional[float] = None,
    target_aspect: float = 9 / 16,
) -> Tuple[int, int, int, int]:
    """Calculate (x, y, w, h) for reframing 16:9 into vertical 9:16."""
    crop_h = frame_height
    crop_w = int(round(crop_h * target_aspect))
    if crop_w % 2 != 0:
        crop_w += 1

    if crop_w > frame_width:
        crop_w = frame_width
        crop_h = int(round(crop_w / target_aspect))
        if crop_h % 2 != 0:
            crop_h += 1

    center_y = (frame_height - crop_h) // 2
    if face_center_x is not None:
        ideal_x = int(face_center_x - crop_w / 2.0)
        center_x = max(0, min(frame_width - crop_w, ideal_x))
    else:
        center_x = (frame_width - crop_w) // 2

    return center_x, center_y, crop_w, crop_h


def calculate_stacked_crops(
    frame_width: int,
    frame_height: int,
    face_bbox: Optional[Tuple[int, int, int, int]] = None,
) -> Tuple[Dict[str, int], Dict[str, int]]:
    """Calculate crops for stacked layout (top: facecam/speaker, bottom: gameplay/screen)."""
    # Top box: 1:1 or 9:8 box around speaker face
    if face_bbox:
        fx, fy, fw, fh = face_bbox
        pad = int(max(fw, fh) * 0.5)
        top_w = min(frame_width, fw + 2 * pad)
        top_h = top_w
        top_x = max(0, min(frame_width - top_w, fx - pad))
        top_y = max(0, min(frame_height - top_h, fy - pad))
    else:
        # Default top-left or top-right webcam
        top_w = frame_width // 3
        top_h = top_w
        top_x = 0
        top_y = 0

    # Bottom box: full width center screen (gameplay)
    bot_w = frame_width
    bot_h = frame_height // 2
    bot_x = 0
    bot_y = frame_height // 4

    return (
        {"x": top_x, "y": top_y, "w": top_w, "h": top_h},
        {"x": bot_x, "y": bot_y, "w": bot_w, "h": bot_h},
    )

