# EC2 + CloudWatch observability practice app

A **single Python application** for demonstrating AWS CloudWatch metrics, Logs, dashboards, alarms, and AWS X-Ray traces. **No Docker, setup scripts, systemd unit, dashboards-as-code, or monitoring configuration** is included. Configure AWS services manually in the console during your lab.

## Run on EC2

Use Amazon Linux 2023 (or another machine with Python 3.9+). From your EC2 SSH terminal, after installing Python and Git:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export DEMO_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
python app.py
```

Keep that terminal open while running the lab. The application listens on **EC2 localhost port 8000**, intentionally not exposed to the public Internet.

From a **separate terminal on your local RHEL VM**, create an SSH tunnel to EC2 (replace placeholders):

```bash
ssh -i /path/to/key.pem -L 8000:127.0.0.1:8000 ec2-user@EC2_PUBLIC_IP
```

Run all `curl` commands below on the **local RHEL VM**. For the three control commands, replace `YOUR_TOKEN` with the `DEMO_TOKEN` printed or saved privately on EC2; do not show the token to the audience or commit it to Git.

## Reproduce the live incident

```bash
# Baseline: success (HTTP 200)
curl -i http://127.0.0.1:8000/checkout

# Generate some baseline requests
for i in {1..30}; do curl -s -o /dev/null http://127.0.0.1:8000/checkout; sleep 0.2; done

# Introduce application errors (HTTP 503)
curl -s -X POST -H 'X-Demo-Token: YOUR_TOKEN' http://127.0.0.1:8000/control/fail
for i in {1..50}; do curl -s -o /dev/null http://127.0.0.1:8000/checkout; sleep 0.2; done

# Recover and verify HTTP 200
curl -s -X POST -H 'X-Demo-Token: YOUR_TOKEN' http://127.0.0.1:8000/control/recover
curl -i http://127.0.0.1:8000/checkout
```

Optional slow request demo (about 1.5 seconds per checkout):

```bash
curl -s -X POST -H 'X-Demo-Token: YOUR_TOKEN' http://127.0.0.1:8000/control/slow
curl -w '\nTotal seconds: %{time_total}\n' -s http://127.0.0.1:8000/checkout
curl -s -X POST -H 'X-Demo-Token: YOUR_TOKEN' http://127.0.0.1:8000/control/recover
```

## What to configure manually in AWS

1. **EC2 IAM role** with permissions for CloudWatch Logs/metrics and X-Ray; for a teaching lab, AWS's `CloudWatchAgentServerPolicy` and `AWSXRayDaemonWriteAccess` managed policies are a practical starting point. Apply least privilege for production.
2. **CloudWatch Agent** on EC2: install it manually (via Systems Manager or SSH), configure log collection from the absolute path of `app.log`, and turn on the **X-Ray traces receiver** if using the built-in X-Ray SDK. X-Ray's SDK emits segments to local UDP port 2000; without a configured receiver, traces will **not** reach AWS. No OpenTelemetry packages are required in the app.
3. **CloudWatch Logs**: confirm that each `/checkout` request produces JSON events. The JSON includes **Embedded Metric Format (EMF)**: the `ObservabilityDemo` namespace exposes `RequestCount`, `ErrorCount`, and `LatencyMs` when the logs are successfully ingested. Note that collecting logs is not the same as automatically extracting metrics—EMF requires recognized ingestion through CloudWatch Logs.
4. **CloudWatch Metrics / Dashboard**: add graphs for those custom metrics alongside the built-in EC2 `CPUUtilization` metric. A low-load demo may show little EC2 CPU activity; the application error metric is the primary incident signal.
5. **CloudWatch Alarm + SNS**: create an alarm on the **sum of `ErrorCount`**, such as >= 3 errors in one 60-second period, with `Treat missing data as not breaching`; attach an SNS topic with a **confirmed** email subscription. Threshold and alarm evaluation timing determine when email arrives.
6. **X-Ray**: after traces are arriving, inspect the checkout request traces and the `checkout-business-logic` subsegment. X-Ray SDK Python is in maintenance mode; this is a minimal educational demonstration rather than a recommended new production architecture.

### Operational notes

- The app logs to `app.log` in the directory where it was started. Use the **absolute path** when configuring CloudWatch Agent.
- `/health` remains OK when checkout errors are simulated. This deliberately distinguishes **process availability** from **user-facing application functionality**.
- The `/control/*` endpoints require `DEMO_TOKEN`, and the Flask server is bound to localhost. Never expose Flask's development server publicly.
- The sample traffic is modest and should only be run on infrastructure you control.
- No Auto Scaling Group is deployed. Discuss self-healing and capacity scaling **theoretically** with your diagram.

## Graphical web interface

Open **http://127.0.0.1:8000/** in a browser on your local RHEL VM **after starting the SSH tunnel**. You'll see a fictional Northstar Shop checkout page with a **Complete demo checkout** button, live status indicator, HTTP result, and observed response time.

- The button calls the existing `GET /checkout` endpoint. Normal operation displays a green successful checkout (HTTP 200).
- Use the protected `POST /control/fail` terminal command above and click checkout again: the page visibly fails (HTTP 503), while the app emits the same CloudWatch EMF metrics, JSON logs, and X-Ray segments.
- Use `POST /control/slow` for a visibly delayed checkout; recover with `POST /control/recover`.
- The webpage has **no failure-mode admin buttons**: the presenter controls incidents privately from a terminal.
- The UI uses bundled HTML/CSS/JavaScript only. No frontend frameworks, containers, CDN dependencies, or database.
- `GET /status` provides the current simulation state for the on-screen indicator; `/health` intentionally continues to report process health even if checkout is failing.

**Note:** The in-browser request counter and latency are illustrative per-browser-session values, not CloudWatch metrics. The real `/checkout` calls independently generate telemetry for AWS.
