#!/usr/bin/env python3
"""A tiny EC2 app for hands-on CloudWatch metrics, logs, and X-Ray traces."""
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, request, render_template
from aws_xray_sdk.core import xray_recorder
from aws_xray_sdk.ext.flask.middleware import XRayMiddleware

APP_NAME = 'ec2-observability-demo'
LOG_FILE = Path(os.environ.get('APP_LOG', 'app.log'))
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
TOKEN = os.environ.get('DEMO_TOKEN')
if not TOKEN:
    raise SystemExit('Set DEMO_TOKEN to a random secret before starting this demo.')

app = Flask(__name__)
app.logger.setLevel(logging.ERROR)
# SDK sends X-Ray segments to a locally configured X-Ray receiver on UDP 2000.
# The CloudWatch agent must be separately configured to receive and forward them.
xray_recorder.configure(service=APP_NAME, sampling=False, context_missing='LOG_ERROR')
XRayMiddleware(app, xray_recorder)

state = {'fail': False, 'slow': False}
mutex = threading.Lock()


def record(level, message, status, duration_ms, route, error=False):
    """Write JSON/EMF events. CloudWatch agent forwards this file to Logs.

    Embedded Metric Format is recognized by CloudWatch Logs and creates custom
    metrics. One log line is emitted per checkout request.
    """
    payload = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'level': level,
        'service': APP_NAME,
        'route': route,
        'status': status,
        'duration_ms': round(duration_ms, 2),
        'message': message,
    }
    if route == '/checkout':
        payload.update({
            '_aws': {
                'Timestamp': int(time.time() * 1000),
                'CloudWatchMetrics': [{
                    'Namespace': 'ObservabilityDemo',
                    'Dimensions': [['Service']],
                    'Metrics': [
                        {'Name': 'RequestCount', 'Unit': 'Count'},
                        {'Name': 'ErrorCount', 'Unit': 'Count'},
                        {'Name': 'LatencyMs', 'Unit': 'Milliseconds'},
                    ],
                }],
            },
            'Service': APP_NAME,
            'RequestCount': 1,
            'ErrorCount': int(error),
            'LatencyMs': round(duration_ms, 2),
        })
    with mutex:
        with LOG_FILE.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(payload, separators=(',', ':')) + '\n')


@app.get('/')
def index():
    return render_template('index.html')


@app.get('/status')
def status():
    with mutex:
        snapshot = state.copy()
    return jsonify(service=APP_NAME, mode=snapshot)


@app.get('/health')
def health():
    return jsonify(status='ok', service=APP_NAME)


@app.get('/checkout')
def checkout():
    start = time.monotonic()
    with mutex:
        fail, slow = state['fail'], state['slow']
    with xray_recorder.in_subsegment('checkout-business-logic') as subsegment:
        if slow:
            time.sleep(1.5)
        if subsegment:
            subsegment.put_annotation('failure_mode', fail)
            subsegment.put_annotation('slow_mode', slow)
        code = 503 if fail else 200
        message = 'Simulated dependency failure' if fail else 'Checkout successful'
    elapsed = (time.monotonic() - start) * 1000
    record('ERROR' if fail else 'INFO', message, code, elapsed, '/checkout', fail)
    return jsonify(message=message, simulated=True), code


@app.post('/control/<action>')
def control(action):
    if request.headers.get('X-Demo-Token') != TOKEN:
        return jsonify(error='forbidden'), 403
    if action not in ('fail', 'slow', 'recover'):
        return jsonify(error='unknown action'), 404
    with mutex:
        if action == 'fail':
            state['fail'] = True
        elif action == 'slow':
            state['slow'] = True
        else:
            state.update(fail=False, slow=False)
        snapshot = state.copy()
    record('WARN', f'Demo changed to {action}', 200, 0, '/control')
    return jsonify(mode=snapshot)


if __name__ == '__main__':
    # Keep the port off the public Internet. Use SSH tunneling from your RHEL VM.
    app.run(host='127.0.0.1', port=8000, use_reloader=False, threaded=True)
