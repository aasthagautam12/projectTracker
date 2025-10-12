from typing import Dict, Tuple, List, DefaultDict
from collections import defaultdict
import numpy as np
import cv2
from ultralytics import YOLO

# Load a small, fast model (swap to yolov8s.pt if you have more compute)
_yolo_model = YOLO("yolov8n.pt")

# Reasonable defaults; the client can override at runtime
DEFAULT_COLOR_RANGES = {
    "red":   [(0, 120, 70), (10, 255, 255), (170, 120, 70), (180, 255, 255)],  # two ranges for red
    "green": [(35, 52, 72), (90, 255, 255)],
    "blue":  [(90, 60, 0), (128, 255, 255)],
}

# In-memory store for analysis artifacts by job_id (used by the API)
ANALYSIS_STORE: dict = {}

def detect_objects_bboxes(frame_bgr: np.ndarray, conf: float = 0.35):
    """Run YOLOv8 inference and return list of (x1,y1,x2,y2,label,score)."""
    results = _yolo_model.predict(source=frame_bgr[:, :, ::-1], imgsz=640, conf=conf, verbose=False)
    boxes = []
    for r in results:
        if r.boxes is None:
            continue
        for b in r.boxes:
            x1, y1, x2, y2 = b.xyxy[0].cpu().numpy().astype(int)
            cls_id = int(b.cls[0].item())
            score = float(b.conf[0].item())
            label = _yolo_model.model.names[cls_id]
            boxes.append((x1, y1, x2, y2, label, score))
    return boxes

def color_masks(frame_bgr: np.ndarray, color_choice: str, ranges: Dict[str, Tuple[Tuple[int,int,int], Tuple[int,int,int]]]):
    """Create a binary mask for the selected color in HSV space. Supports red split range."""
    hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
    selection = ranges.get(color_choice)
    if selection is None:
        return None

    if color_choice == "red":
        # red wraps hue; combine two masks
        lower1, upper1, lower2, upper2 = selection  # type: ignore
        mask1 = cv2.inRange(hsv, np.array(lower1), np.array(upper1))
        mask2 = cv2.inRange(hsv, np.array(lower2), np.array(upper2))
        mask = cv2.bitwise_or(mask1, mask2)
    else:
        lower, upper = selection  # type: ignore
        mask = cv2.inRange(hsv, np.array(lower), np.array(upper))

    # clean up noise
    kernel = np.ones((5, 5), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_DILATE, kernel)
    return mask

def overlay_annotations(frame_bgr: np.ndarray, boxes, mask, show_mask: bool = True):
    """Draw bboxes and optionally color mask contours on the frame."""
    out = frame_bgr.copy()

    # Draw detection boxes
    for (x1, y1, x2, y2, label, score) in boxes:
        cv2.rectangle(out, (x1, y1), (x2, y2), (0, 255, 0), 2)
        cv2.putText(out, f"{label} {score:.2f}", (x1, max(20, y1 - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

    # Draw color contours
    if show_mask and mask is not None:
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(out, contours, -1, (255, 0, 0), 2)

    return out

def process_frame(frame_bytes: bytes, color_choice: str = "red", conf: float = 0.35):
    """Decode bytes->image, run detection + color mask, return (annotated JPEG bytes, boxes)."""
    # decode jpeg/png bytes to numpy BGR
    nparr = np.frombuffer(frame_bytes, np.uint8)
    frame_bgr = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if frame_bgr is None:
        raise ValueError("Failed to decode frame")

    # objects
    boxes = detect_objects_bboxes(frame_bgr, conf=conf)

    # color
    mask = color_masks(frame_bgr, color_choice, DEFAULT_COLOR_RANGES)

    # overlay
    annotated = overlay_annotations(frame_bgr, boxes, mask, show_mask=True)

    # encode back to JPEG
    success, jpg = cv2.imencode('.jpg', annotated, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
    if not success:
        raise ValueError("JPEG encode failed")
    return jpg.tobytes(), boxes

def process_video_file(in_path: str, out_path: str, color_choice: str = "red", conf: float = 0.35):
    """Process a full video; writes an annotated MP4 and returns analysis dict."""
    cap = cv2.VideoCapture(in_path)
    if not cap.isOpened():
        raise ValueError("Could not open input video")

    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 640)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 480)

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(out_path, fourcc, fps, (width, height))
    if not writer.isOpened():
        cap.release()
        raise ValueError("Could not open output writer")

    per_class: DefaultDict[str, int] = defaultdict(int)
    total_frames = 0
    total_detections = 0

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            total_frames += 1
            success, buf = cv2.imencode('.jpg', frame)
            if not success:
                continue
            annotated_bytes, boxes = process_frame(buf.tobytes(), color_choice=color_choice, conf=conf)
            total_detections += len(boxes)
            for *_, label, _ in boxes:
                per_class[label] += 1
            ann = cv2.imdecode(np.frombuffer(annotated_bytes, np.uint8), cv2.IMREAD_COLOR)
            if ann is None:
                ann = frame
            writer.write(ann)
    finally:
        cap.release()
        writer.release()

    analysis = {
        "total_frames": total_frames,
        "total_detections": total_detections,
        "per_class": dict(sorted(per_class.items(), key=lambda x: x[1], reverse=True)),
        "fps": fps,
        "width": width,
        "height": height,
    }
    return analysis

def save_analysis_plot(job_id: str, analysis: dict, png_path: str):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    labels = list(analysis.get("per_class", {}).keys())
    values = list(analysis.get("per_class", {}).values())
    plt.figure(figsize=(8, 4.5))
    plt.bar(labels, values)
    plt.title("Detections per Class")
    plt.xlabel("Class")
    plt.ylabel("Count")
    plt.xticks(rotation=45, ha='right')
    plt.tight_layout()
    plt.savefig(png_path)
    plt.close()
