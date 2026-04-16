"""
HTTP Server — Plain HTTP on port 80 for performance comparison.

Run on Server PC (Windows, 192.165.20.79):
    python http_server.py

Note: On Windows, run as Administrator to bind to port 80.
"""

from flask import Flask, render_template, request
import logging
import os

# Logging
logging.basicConfig(
    filename='http_server.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('http_server')

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
    app.run(host='0.0.0.0', port=80, debug=False)
