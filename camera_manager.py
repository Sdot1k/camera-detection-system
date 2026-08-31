import cv2
import threading
import time
import urllib.request
import urllib.error
import base64
import os
import re
import subprocess
import json
from datetime import datetime
from detection import detect_objects
from database import add_detection, get_setting, get_appdata_path
from collections import deque

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}")

def get_screenshots_path():
    base = get_appdata_path()
    screens_dir = os.path.join(base, 'screenshots')
    os.makedirs(screens_dir, exist_ok=True)
    return screens_dir

def get_youtube_stream_url(youtube_url, resolution='best'):
    """Использует yt-dlp для получения прямого URL видеопотока."""
    import yt_dlp
    ydl_opts = {
        'format': resolution,
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(youtube_url, download=False)
            
            if 'entries' in info:
                info = info['entries'][0]
            
            if 'url' in info:
                return info['url']
            else:
                
                if 'formats' in info and len(info['formats']) > 0:
                    
                    best_format = max(info['formats'], key=lambda f: f.get('height', 0) or 0)
                    return best_format['url']
        return None
    except Exception as e:
        log(f"Ошибка извлечения URL из YouTube: {e}")
        return None

def normalize_youtube_url(url):
    """Приводит URL YouTube к стандартному виду и проверяет корректность ID."""
    url = url.strip()
    if url.endswith('.'):
        url = url[:-1]
    
    pattern = r'(?:https?://)?(?:www\.)?youtu\.be/([a-zA-Z0-9_-]+)'
    match = re.match(pattern, url)
    if match:
        video_id = match.group(1)
        if len(video_id) < 10:
            raise ValueError(f"Некорректный YouTube ID: {video_id} (слишком короткий)")
        url = f"https://www.youtube.com/watch?v={video_id}"
    if not url.startswith('http'):
        url = 'https://' + url
  
    if 'watch?v=' not in url:
        if re.match(r'^[a-zA-Z0-9_-]{10,12}$', url):
            url = f"https://www.youtube.com/watch?v={url}"
        else:
            raise ValueError(f"Не удалось распознать URL YouTube: {url}")
    id_match = re.search(r'[?&]v=([a-zA-Z0-9_-]{11,})', url)
    if not id_match:
        raise ValueError(f"URL YouTube не содержит корректный ID: {url}")
    return url

class CameraThread(threading.Thread):
    def __init__(self, device):
        super().__init__(daemon=True)
        self.device = device
        self.callbacks = []
        self.running = True
        self.cap = None
        self.last_detected_objects = set()
        self.frame_cache = deque(maxlen=5)
        self.status = "connecting"
        self.status_callback = None
        self.current_stream_url = None  

    def register_callback(self, callback):
        if callback not in self.callbacks:
            self.callbacks.append(callback)

    def unregister_callback(self, callback):
        if callback in self.callbacks:
            self.callbacks.remove(callback)

    def set_status_callback(self, callback):
        self.status_callback = callback

    def update_status(self, status):
        self.status = status
        if self.status_callback:
            self.status_callback(self.device["id"], status)

    def get_cached_frame(self):
        if self.frame_cache:
            return self.frame_cache[-1].copy()
        return None

    def run(self):
        conf_threshold = float(get_setting('confidence'))
        detect_every_n = int(get_setting('detect_every_n_frames'))
        self.update_status("connecting")

        while self.running:
            try:
                if self.device["type"] == "webcam":
                    self.cap = cv2.VideoCapture(0)
                    log(f"Запущена веб-камера {self.device['name']}")
                elif self.device["type"] == "youtube":
                    original_url = self.device["url"]
                    try:
                        norm_url = normalize_youtube_url(original_url)
                        if norm_url != original_url:
                            log(f"Нормализован URL YouTube: {original_url} -> {norm_url}")
                        # Получаем прямой URL потока
                        stream_url = get_youtube_stream_url(norm_url, 'best')
                        if not stream_url:
                            raise Exception("Не удалось получить URL потока")
                        self.current_stream_url = stream_url
                        self.cap = cv2.VideoCapture(stream_url)
                        log(f"Запущена YouTube-камера {self.device['name']}, поток URL: {stream_url[:80]}...")
                    except Exception as e:
                        log(f"Ошибка подготовки YouTube-камеры {self.device['name']}: {e}")
                        self.update_status("error")
                        time.sleep(5)
                        continue
                else:
                    url = self.device["url"]
                    if self.device["username"] and self.device["password"]:
                        auth_url = f"rtsp://{self.device['username']}:{self.device['password']}@{url.split('://')[1] if '://' in url else url}"
                        self.cap = cv2.VideoCapture(auth_url, cv2.CAP_FFMPEG)
                    else:
                        self.cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
                    log(f"Запущена IP-камера {self.device['name']} по URL: {url}")

                if not self.cap.isOpened():
                    log(f"Ошибка: не удалось открыть камеру {self.device['name']}")
                    self.update_status("error")
                    time.sleep(5)
                    continue

                self.update_status("active")
                device_id = self.device["id"]
                frame_count = 0
                last_detection_frame = 0
                consecutive_errors = 0

                while self.running and self.cap is not None and self.cap.isOpened():
                    try:
                        ret, frame = self.cap.read()
                        if not ret:
                            consecutive_errors += 1
                            log(f"Потеря кадра на камере {self.device['name']} (ошибка {consecutive_errors})")
                            if consecutive_errors > 5:
                                log(f"Слишком много ошибок чтения, переподключение...")
                                break
                            time.sleep(0.5)
                            continue
                        consecutive_errors = 0
                        self.frame_cache.append(frame.copy())
                        frame_count += 1
                        current_time = time.time()
                        date_str = time.strftime("%Y-%m-%d")
                        time_str = time.strftime("%H:%M:%S")

                        if frame_count - last_detection_frame >= detect_every_n:
                            last_detection_frame = frame_count
                            detections = detect_objects(frame)
                            for (x1, y1, x2, y2, class_name, conf) in detections:
                                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                                label = f"{class_name} {conf:.2f}"
                                cv2.putText(frame, label, (x1, y1-10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,255,0), 2)

                                obj_key = f"{class_name}_{device_id}"
                                if obj_key not in self.last_detected_objects:
                                    self.last_detected_objects.add(obj_key)
                                    add_detection(class_name, device_id)
                                    log(f"Новое обнаружение: {class_name} на камере {self.device['name']}")
                                    try:
                                        screens_dir = get_screenshots_path()
                                        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
                                        filename = os.path.join(screens_dir, f"{self.device['name']}_{class_name}_{timestamp}.jpg")
                                        cv2.imwrite(filename, frame)
                                        log(f"Скриншот сохранён: {filename}")
                                    except Exception as e:
                                        log(f"Ошибка сохранения скриншота: {e}")

                        fps = 1 / (time.time() - current_time) if (time.time() - current_time) > 0 else 0
                        cv2.putText(frame, f"FPS: {int(fps):03d}  {date_str} {time_str}", (10, 30),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0,0,255), 2)

                        for cb in self.callbacks:
                            cb(self.device["id"], frame.copy())

                        time.sleep(0.03)

                    except Exception as e:
                        log(f"Ошибка чтения кадра на камере {self.device['name']}: {e}")
                        consecutive_errors += 1
                        if consecutive_errors > 5:
                            break
                        time.sleep(0.5)

            except Exception as e:
                log(f"Ошибка в потоке камеры {self.device['name']}: {e}")
                self.update_status("error")
            finally:
                if self.cap:
                    self.cap.release()
                    self.cap = None
                self.current_stream_url = None
            if self.running:
                log(f"Попытка переподключения камеры {self.device['name']} через 5 секунд...")
                time.sleep(5)

        log(f"Поток камеры {self.device['name']} остановлен")

    def stop(self):
        self.running = False

def find_stream_url(ip, port, username=None, password=None, timeout=5):
    base_http = f"http://{ip}:{port}" if port else f"http://{ip}"
    base_rtsp = f"rtsp://{ip}:{port}" if port else f"rtsp://{ip}"
    if username and password:
        auth_http = f"http://{username}:{password}@{ip}:{port}" if port else f"http://{username}:{password}@{ip}"
        auth_rtsp = f"rtsp://{username}:{password}@{ip}:{port}" if port else f"rtsp://{username}:{password}@{ip}"
    else:
        auth_http = base_http
        auth_rtsp = base_rtsp

    candidates = [
        f"{base_http}/ISAPI/Streaming/channels/101/picture",
        f"{base_rtsp}/Streaming/Channels/101",
        f"{base_rtsp}/h264/ch1/main/av_stream",
        f"{base_http}/cgi-bin/snapshot.cgi?channel=1",
        f"{base_rtsp}/cam/realmonitor?channel=1&subtype=0",
        f"{base_rtsp}/onvif1",
        f"{base_http}/axis-cgi/mjpg/video.cgi",
        f"{base_http}/axis-cgi/jpg/image.cgi",
        f"{base_rtsp}/axis-media/media.amp",
        f"{base_rtsp}/live",
        f"{base_rtsp}/video.h264",
        f"{base_http}/video.mjpg",
    ]

    if username and password:
        for cand in list(candidates):
            if cand.startswith("http://") and not cand.startswith(auth_http):
                candidates.append(cand.replace(base_http, auth_http))
            elif cand.startswith("rtsp://") and not cand.startswith(auth_rtsp):
                candidates.append(cand.replace(base_rtsp, auth_rtsp))

    candidates = list(dict.fromkeys(candidates))

    def check_url(url):
        try:
            if url.startswith("http"):
                req = urllib.request.Request(url, method='HEAD')
                if username and password:
                    cred = base64.b64encode(f"{username}:{password}".encode()).decode()
                    req.add_header('Authorization', f'Basic {cred}')
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    if resp.status == 200:
                        content_type = resp.headers.get('Content-Type', '')
                        if 'image' in content_type or 'mjpeg' in content_type:
                            return True
            elif url.startswith("rtsp"):
                cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
                if cap.isOpened():
                    ret, frame = cap.read()
                    cap.release()
                    return ret and frame is not None
        except Exception:
            pass
        return False

    for url in candidates:
        if check_url(url):
            return url
    return None