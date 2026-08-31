import cv2
import numpy as np
import time
import threading
from database import get_setting, get_filtered_classes

_model = None
_model_lock = threading.Lock()
_current_model_type = None
_current_model_path = None

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}")

def load_model():
    global _model, _current_model_type, _current_model_path
    model_type = get_setting('model_type')
    model_path = get_setting('model_path')
    if not model_path or model_path == '':
        raise FileNotFoundError("Модель не выбрана. Пожалуйста, выберите файл модели в настройках.")
    with _model_lock:
        if _model is None or _current_model_type != model_type or _current_model_path != model_path:
            log(f"Загрузка модели {model_type.upper()} из {model_path}...")
            if model_type == 'pt':
                from ultralytics import YOLO
                _model = YOLO(model_path)
            elif model_type == 'onnx':
                import onnxruntime as ort
                sess_options = ort.SessionOptions()
                sess_options.intra_op_num_threads = 4
                _model = ort.InferenceSession(model_path, sess_options=sess_options, providers=['CPUExecutionProvider'])
            else:
                raise ValueError(f"Unknown model type: {model_type}")
            _current_model_type = model_type
            _current_model_path = model_path
            log("Модель загружена")
    return _model

def get_model_classes():
    try:
        model = load_model()
        model_type = get_setting('model_type')
        if model_type == 'pt' and hasattr(model, 'names'):
            return list(model.names.values())
        else:
            return get_coco_classes()
    except Exception:
        return get_coco_classes()

def get_coco_classes():
    return [
        'person', 'bicycle', 'car', 'motorcycle', 'airplane', 'bus', 'train', 'truck', 'boat',
        'traffic light', 'fire hydrant', 'stop sign', 'parking meter', 'bench', 'bird', 'cat',
        'dog', 'horse', 'sheep', 'cow', 'elephant', 'bear', 'zebra', 'giraffe', 'backpack',
        'umbrella', 'handbag', 'tie', 'suitcase', 'frisbee', 'skis', 'snowboard', 'sports ball',
        'kite', 'baseball bat', 'baseball glove', 'skateboard', 'surfboard', 'tennis racket',
        'bottle', 'wine glass', 'cup', 'fork', 'knife', 'spoon', 'bowl', 'banana', 'apple',
        'sandwich', 'orange', 'broccoli', 'carrot', 'hot dog', 'pizza', 'donut', 'cake',
        'chair', 'couch', 'potted plant', 'bed', 'dining table', 'toilet', 'tv', 'laptop',
        'mouse', 'remote', 'keyboard', 'cell phone', 'microwave', 'oven', 'toaster', 'sink',
        'refrigerator', 'book', 'clock', 'vase', 'scissors', 'teddy bear', 'hair drier', 'toothbrush'
    ]

def preprocess_onnx(image, target_size=640):
    orig_h, orig_w = image.shape[:2]
    img = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    scale = min(target_size / orig_w, target_size / orig_h)
    nw, nh = int(orig_w * scale), int(orig_h * scale)
    img_resized = cv2.resize(img, (nw, nh))
    new_img = np.full((target_size, target_size, 3), 114, dtype=np.uint8)
    top, left = (target_size - nh) // 2, (target_size - nw) // 2
    new_img[top:top+nh, left:left+nw, :] = img_resized
    img = new_img.transpose(2, 0, 1)
    img = np.expand_dims(img, axis=0).astype(np.float32) / 255.0
    return img, scale, left, top

def postprocess_onnx(outputs, frame_shape, scale, left, top, conf_threshold):
    detections = outputs[0]
    detections = detections.transpose(0, 2, 1)[0]
    boxes, scores, class_ids = [], [], []
    for detection in detections:
        x, y, w, h = detection[:4]
        class_scores = detection[4:]
        score = class_scores.max()
        class_id = class_scores.argmax()
        if score > conf_threshold:
            x = (x - left) / scale
            y = (y - top) / scale
            w = w / scale
            h = h / scale
            x1 = int(x - w / 2)
            y1 = int(y - h / 2)
            x2 = int(x + w / 2)
            y2 = int(y + h / 2)
            x1 = max(0, min(x1, frame_shape[1]))
            y1 = max(0, min(y1, frame_shape[0]))
            x2 = max(0, min(x2, frame_shape[1]))
            y2 = max(0, min(y2, frame_shape[0]))
            boxes.append([x1, y1, x2 - x1, y2 - y1])
            scores.append(score)
            class_ids.append(class_id)
    indices = cv2.dnn.NMSBoxes(boxes, scores, conf_threshold, 0.4)
    results = []
    if len(indices) > 0:
        for i in indices.flatten():
            x, y, w, h = boxes[i]
            label = f"class_{class_ids[i]}: {scores[i]:.2f}"
            results.append((x, y, x + w, y + h, label))
    return results

def detect_objects(frame):
    model = load_model()
    model_type = get_setting('model_type')
    conf_threshold = float(get_setting('confidence'))
    filtered_classes = get_filtered_classes()

    if model_type == 'pt':
        results = model(frame, verbose=False, conf=conf_threshold)
        detections = []
        for result in results:
            boxes = result.boxes
            if boxes is None:
                continue
            for box in boxes:
                x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
                cls = int(box.cls[0])
                conf = float(box.conf[0])
                class_name = model.names[cls]
                if filtered_classes is not None and class_name.lower() not in filtered_classes:
                    continue
                detections.append((x1, y1, x2, y2, class_name, conf))
        return detections
    elif model_type == 'onnx':
        input_data, scale, left, top = preprocess_onnx(frame)
        outputs = model.run(None, {model.get_inputs()[0].name: input_data})
        raw = postprocess_onnx(outputs, frame.shape, scale, left, top, conf_threshold)
        return raw
    else:
        return []