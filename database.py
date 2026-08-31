import sqlite3
import os
from datetime import datetime
from pathlib import Path

def get_appdata_path():
    appdata = os.environ.get('APPDATA', os.path.expanduser('~'))
    db_dir = os.path.join(appdata, 'CameraDetection')
    Path(db_dir).mkdir(parents=True, exist_ok=True)
    return db_dir

DB_PATH = os.path.join(get_appdata_path(), "camera_app.db")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS devices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            url TEXT,
            username TEXT,
            password TEXT,
            is_active BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS detections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            detection_number INTEGER NOT NULL,
            object_type TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            device_id INTEGER,
            FOREIGN KEY(device_id) REFERENCES devices(id)
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    default_settings = {
        'model_type': 'pt',
        'model_path': '',
        'confidence': '0.5',
        'detect_every_n_frames': '2',
        'filtered_classes': '',
        'theme': 'vista'
    }
    for k, v in default_settings.items():
        c.execute("INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, ?)", (k, v))
    conn.commit()
    conn.close()

def add_device(name, dev_type, url=None, username=None, password=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        INSERT INTO devices (name, type, url, username, password)
        VALUES (?, ?, ?, ?, ?)
    ''', (name, dev_type, url, username, password))
    conn.commit()
    last_id = c.lastrowid
    conn.close()
    return last_id

def get_devices():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT id, name, type, url, username, password, is_active, created_at FROM devices')
    rows = c.fetchall()
    devices = []
    for row in rows:
        devices.append({
            "id": row[0],
            "name": row[1],
            "type": row[2],
            "url": row[3],
            "username": row[4],
            "password": row[5],
            "is_active": bool(row[6]),
            "created_at": row[7]
        })
    conn.close()
    return devices

def update_device(device_id, name=None, url=None, username=None, password=None, is_active=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    fields = []
    values = []
    if name is not None:
        fields.append("name = ?")
        values.append(name)
    if url is not None:
        fields.append("url = ?")
        values.append(url)
    if username is not None:
        fields.append("username = ?")
        values.append(username)
    if password is not None:
        fields.append("password = ?")
        values.append(password)
    if is_active is not None:
        fields.append("is_active = ?")
        values.append(is_active)
    if fields:
        values.append(device_id)
        c.execute(f"UPDATE devices SET {', '.join(fields)} WHERE id = ?", values)
        conn.commit()
    conn.close()

def delete_device(device_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM devices WHERE id = ?", (device_id,))
    conn.commit()
    conn.close()

def add_detection(object_type, device_id=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT MAX(detection_number) FROM detections WHERE object_type = ?", (object_type,))
    row = c.fetchone()
    next_num = (row[0] or 0) + 1
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute('''
        INSERT INTO detections (detection_number, object_type, timestamp, device_id)
        VALUES (?, ?, ?, ?)
    ''', (next_num, object_type, timestamp, device_id))
    conn.commit()
    conn.close()
    return next_num

def get_detections(limit=100, offset=0):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        SELECT id, detection_number, object_type, timestamp, device_id
        FROM detections
        ORDER BY timestamp DESC
        LIMIT ? OFFSET ?
    ''', (limit, offset))
    rows = c.fetchall()
    logs = []
    for row in rows:
        logs.append({
            "id": row[0],
            "detection_number": row[1],
            "object_type": row[2],
            "timestamp": row[3],
            "device_id": row[4]
        })
    conn.close()
    return logs

def get_setting(key):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT value FROM app_settings WHERE key = ?", (key,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None

def set_setting(key, value):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, ?)", (key, str(value)))
    conn.commit()
    conn.close()

def get_settings():
    keys = ['model_type', 'model_path', 'confidence', 'detect_every_n_frames', 'filtered_classes', 'theme']
    return {k: get_setting(k) for k in keys}

def update_settings(confidence=None, detect_every=None):
    if confidence is not None:
        set_setting('confidence', confidence)
    if detect_every is not None:
        set_setting('detect_every_n_frames', detect_every)

def get_filtered_classes():
    filter_str = get_setting('filtered_classes')
    if filter_str and filter_str.strip():
        return [c.strip().lower() for c in filter_str.split(',')]
    return None

def set_filtered_classes(class_list):
    if class_list is None:
        set_setting('filtered_classes', '')
    else:
        set_setting('filtered_classes', ','.join(class_list))

def get_detections_filtered(limit=100, offset=0, object_type=None, date_from=None, date_to=None, device_id=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    query = "SELECT id, detection_number, object_type, timestamp, device_id FROM detections WHERE 1=1"
    params = []
    if object_type and object_type != "Все события":
        if object_type == "Человек":
            query += " AND LOWER(object_type) = 'person'"
        elif object_type == "Автомобиль":
            query += " AND LOWER(object_type) IN ('car', 'truck', 'bus', 'motorcycle')"
        elif object_type == "Животное":
            query += " AND LOWER(object_type) IN ('dog', 'cat', 'horse', 'sheep', 'cow', 'elephant', 'bear', 'zebra', 'giraffe', 'bird')"
        else:
            query += " AND LOWER(object_type) = ?"
            params.append(object_type.lower())
    if device_id is not None:
        query += " AND device_id = ?"
        params.append(device_id)
    if date_from:
        query += " AND date(timestamp) >= ?"
        params.append(date_from)
    if date_to:
        query += " AND date(timestamp) <= ?"
        params.append(date_to)
    query += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    c.execute(query, params)
    rows = c.fetchall()
    logs = []
    for row in rows:
        logs.append({
            "id": row[0],
            "detection_number": row[1],
            "object_type": row[2],
            "timestamp": row[3],
            "device_id": row[4]
        })
    conn.close()
    return logs

def get_detections_count(object_type=None, date_from=None, date_to=None, device_id=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    query = "SELECT COUNT(*) FROM detections WHERE 1=1"
    params = []
    if object_type and object_type != "Все события":
        if object_type == "Человек":
            query += " AND LOWER(object_type) = 'person'"
        elif object_type == "Автомобиль":
            query += " AND LOWER(object_type) IN ('car', 'truck', 'bus', 'motorcycle')"
        elif object_type == "Животное":
            query += " AND LOWER(object_type) IN ('dog', 'cat', 'horse', 'sheep', 'cow', 'elephant', 'bear', 'zebra', 'giraffe', 'bird')"
        else:
            query += " AND LOWER(object_type) = ?"
            params.append(object_type.lower())
    if device_id is not None:
        query += " AND device_id = ?"
        params.append(device_id)
    if date_from:
        query += " AND date(timestamp) >= ?"
        params.append(date_from)
    if date_to:
        query += " AND date(timestamp) <= ?"
        params.append(date_to)
    c.execute(query, params)
    count = c.fetchone()[0]
    conn.close()
    return count

def get_available_object_types():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT DISTINCT object_type FROM detections ORDER BY object_type")
    rows = c.fetchall()
    conn.close()
    return [row[0] for row in rows]

def get_devices_for_filter():
    devices = get_devices()
    return [{"id": d["id"], "name": d["name"]} for d in devices]