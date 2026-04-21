"""
Secured HTTPS Server — Flask HTTPS on port 443 with security headers.

Generate certificates first (Git Bash, WSL, or OpenSSL for Windows):
    openssl req -x509 -nodes -days 365 -newkey rsa:2048 ^
      -keyout server\key.pem -out server\cert.pem ^
      -subj "/CN=192.165.20.79/O=CCEN356Lab"

Run on Server PC (Windows, 192.165.20.79):
    python secured_server.py
"""

from flask import Flask, render_template, request, abort
import atexit
import logging
from logging.handlers import QueueHandler, QueueListener
import os
from queue import SimpleQueue
import time


def _configure_async_logger(log_filename, logger_name):
    """Write logs through a queue so request threads are not blocked by disk I/O."""
    log_queue = SimpleQueue()
    file_handler = logging.FileHandler(log_filename)
    file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

    listener = QueueListener(log_queue, file_handler)
    listener.start()
    atexit.register(listener.stop)

    configured_logger = logging.getLogger(logger_name)
    configured_logger.setLevel(logging.INFO)
    configured_logger.handlers.clear()
    configured_logger.addHandler(QueueHandler(log_queue))
    configured_logger.propagate = False
    return configured_logger


logger = _configure_async_logger('server.log', 'secured_server')

QOS_MODE_HEADER = os.getenv("CCEN356_QOS_MODE_HEADER", "X-CCEN356-QOS-MODE")
QOS_MODE_VALUE = os.getenv("CCEN356_QOS_MODE_VALUE", "on").strip().lower()
QOS_HTTPS_DELAY_MS = max(0.0, float(os.getenv("CCEN356_QOS_HTTPS_DELAY_MS", "0")))

app = Flask(
    __name__,
    template_folder=os.path.join(os.path.dirname(__file__), 'templates')
)


def _is_qos_mode_enabled(req):
    return req.headers.get(QOS_MODE_HEADER, "").strip().lower() == QOS_MODE_VALUE


@app.before_request
def validate_path():
    if '..' in request.path:
        logger.warning(f"Directory traversal attempt from {request.remote_addr}: {request.path}")
        abort(403)
    if _is_qos_mode_enabled(request) and QOS_HTTPS_DELAY_MS > 0:
        time.sleep(QOS_HTTPS_DELAY_MS / 1000.0)


@app.after_request
def add_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    response.headers['Content-Security-Policy'] = "default-src 'self'"
    qos_mode = "on" if _is_qos_mode_enabled(request) else "off"
    response.headers[QOS_MODE_HEADER] = qos_mode
    logger.info(
        f"Request from {request.remote_addr}: {request.method} {request.path} "
        f"— {response.status_code} (qos={qos_mode})"
    )
    return response


@app.route('/')
def home():
    return render_template('index.html')


@app.route('/show-something')
def show():
    return render_template('show.html')


@app.errorhandler(403)
def forbidden(e):
    return "<h1>403 Forbidden</h1><p>Access denied.</p>", 403


@app.errorhandler(404)
def not_found(e):
    return "<h1>404 Not Found</h1><p>The requested page does not exist.</p>", 404


@app.errorhandler(500)
def internal_error(e):
    return "<h1>500 Internal Server Error</h1><p>Something went wrong.</p>", 500


if __name__ == '__main__':
    cert_path = os.path.join(os.path.dirname(__file__), 'cert.pem')
    key_path = os.path.join(os.path.dirname(__file__), 'key.pem')

    if not os.path.exists(cert_path) or not os.path.exists(key_path):
        print("ERROR: cert.pem and key.pem not found in server/ directory.")
        print("Generate them with:")
        print("  openssl req -x509 -nodes -days 365 -newkey rsa:2048 \\")
        print("    -keyout server/key.pem -out server/cert.pem \\")
        print('    -subj "/CN=192.165.20.79/O=CCEN356Lab"')
        exit(1)

    print("HTTPS server starting on https://0.0.0.0:443")
    print(f"QoS mode header: {QOS_MODE_HEADER}={QOS_MODE_VALUE} | HTTPS delay: {QOS_HTTPS_DELAY_MS}ms")
    app.run(
        host='0.0.0.0',
        port=443,
        ssl_context=(cert_path, key_path),
        debug=False,
        threaded=True,
        use_reloader=False,
    )
