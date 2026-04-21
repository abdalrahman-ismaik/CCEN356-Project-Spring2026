"""
HTTP Server — Plain HTTP on port 80 for performance comparison.

Run on Server PC (Windows, 192.165.20.79):
    python http_server.py

Note: On Windows, run as Administrator to bind to port 80.
"""

from flask import Flask, render_template, request
import atexit
import logging
from logging.handlers import QueueHandler, QueueListener
import os
from queue import SimpleQueue


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


logger = _configure_async_logger('http_server.log', 'http_server')

app = Flask(
    __name__,
    template_folder=os.path.join(os.path.dirname(__file__), 'templates')
)


@app.after_request
def log_request(response):
    logger.info(f"Request from {request.remote_addr}: {request.method} {request.path} — {response.status_code}")
    return response


@app.route('/')
def home():
    return render_template('index.html')


@app.route('/show-something')
def show():
    return render_template('show.html')


if __name__ == '__main__':
    print("HTTP server starting on http://0.0.0.0:80")
    app.run(host='0.0.0.0', port=80, debug=False, threaded=True, use_reloader=False)
