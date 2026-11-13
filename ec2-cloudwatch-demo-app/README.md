
# Northstar Shop — AWS Observability Lab

A small Flask application running on Amazon EC2, built to demonstrate three practical observability scenarios:

- **Logs:** Investigate HTTP 503 application errors using CloudWatch Logs.
- **Metrics:** Generate a CPU utilization spike and observe it in CloudWatch.
- **Traces:** Investigate slow application requests using AWS X-Ray.

All commands run on EC2 unless otherwise specified.

## 1. Launch EC2 and Run the Application

Launch an **Amazon Linux 2023** EC2 instance.

- Allow SSH (port 22) from your IP address only.
- Attach an IAM role with `AmazonSSMManagedInstanceCore` and `CloudWatchAgentServerPolicy`.
- Keep port 8000 private. The demo-control endpoints do not require authentication.

### Install dependencies and clone the repository

```bash
sudo dnf install -y git python3 stress-ng

git clone https://github.com/njamutoh/cloudwatch-observability-demo-app.git

cd cloudwatch-observability-demo-app/ec2-cloudwatch-demo-app
```

### Create and activate the Python environment

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python app.py
```

Leave this terminal running.

### Verify the application

Open another EC2 terminal:

```bash
cd ~/cloudwatch-observability-demo-app/ec2-cloudwatch-demo-app

curl -i http://127.0.0.1:8000/health
curl -i http://127.0.0.1:8000/checkout
```

Both should return HTTP 200 under normal conditions.

### Access the application from your local Linux machine

Create an SSH tunnel (replace the placeholders):

```bash
ssh -i /path/to/key.pem \
  -L 8000:127.0.0.1:8000 \
  ec2-user@EC2_PUBLIC_IP
```

Open `http://127.0.0.1:8000/` in your local browser while the tunnel is running.

---

## 2. Logs — Simulate HTTP 503 Errors

### Configure CloudWatch Logs

In **CloudWatch → Configure CloudWatch Agent**, select the EC2 instance and install/configure the agent through Systems Manager.

SSM Agent must be connected before using the console installation workflow.

Configure log collection:

| Setting | Value |
|---|---|
| Log file | `/home/ec2-user/cloudwatch-observability-demo-app/ec2-cloudwatch-demo-app/app.log` |
| Log group | `/aws/ec2/demowatch` |
| Log stream | `{instance_id}` |
| Include/exclude filters | Leave empty |

Deploy the configuration.

Check agent status if needed:

```bash
sudo systemctl is-active amazon-ssm-agent
sudo systemctl is-active amazon-cloudwatch-agent
```

### Generate 10 HTTP 503 errors

```bash
curl -s -X POST http://127.0.0.1:8000/control/fail

for i in {1..10}; do
  curl -s -o /dev/null -w 'HTTP %{http_code}\n' \
    http://127.0.0.1:8000/checkout
done
```

### Investigate errors locally

```bash
grep '"level":"ERROR"' app.log | tail -n 10
```

To monitor new errors in real time:

```bash
tail -n 0 -F app.log | grep --line-buffered '"level":"ERROR"'
```

### Investigate using CloudWatch

Navigate to:

**CloudWatch → Logs → Log groups → `/aws/ec2/demowatch`**

Alternatively, run this CloudWatch Logs Insights query:

```sql
fields @timestamp, level, status, message
| filter status = 503
| sort @timestamp desc
| limit 20
```

CloudWatch logs may take a little longer to appear than local application logs.

### Restore the application

```bash
curl -s -X POST http://127.0.0.1:8000/control/recover
```

---

## 3. Metrics — Generate a CPU Utilization Spike

### Configure EC2 monitoring

Enable **EC2 Detailed Monitoring** to get one-minute CPU utilization datapoints.

We'll use the built-in `CPUUtilization` metric rather than creating custom application metrics.

### Generate high CPU utilization

```bash
stress-ng --cpu 2 --cpu-load 100 --timeout 2m --metrics-brief
```

This stresses both vCPUs for two minutes.

### Observe CPU usage immediately

Open another EC2 terminal:

```bash
top
```

### Investigate using CloudWatch

Navigate to:

**EC2 → Instances → Monitoring → CPU Utilization**

Use:

- Time range: **1 hour**
- Period: **1 minute** (with detailed monitoring)
- Statistic: **Average**

CloudWatch metrics are not instantaneous. The CPU load appears locally before the updated metric becomes visible in the AWS Console.

---

## 4. Traces — Investigate a Slow Checkout

### Configure AWS X-Ray

In your CloudWatch Agent configuration, enable **AWS X-Ray traces** and deploy.

Keep the default X-Ray receiver:

```text
127.0.0.1:2000 (UDP)
```

Port 8000 serves the Flask application. Port 2000 receives its X-Ray trace segments.

Verify the listener:

```bash
sudo ss -lunp | grep ':2000'
```

### Generate five slow requests

```bash
# Reset the application
curl -s -X POST http://127.0.0.1:8000/control/recover

# Enable slow responses
curl -s -X POST http://127.0.0.1:8000/control/slow

# Generate five slow requests
for i in {1..5}; do
  curl -s -o /dev/null \
    -w 'HTTP %{http_code} | Time: %{time_total}s\n' \
    http://127.0.0.1:8000/checkout
done
```

Each request should take approximately **1.5 seconds**.

### Investigate using AWS X-Ray

Navigate to:

**CloudWatch → X-Ray traces → Traces**

Select a recent `GET /checkout` trace.

Inspect:

- HTTP response code: `200`
- Request duration: approximately `1.5s`
- The `checkout-business-logic` subsegment
- Trace details and raw data

This demonstrates that an HTTP 200 response doesn't necessarily mean the user experienced good performance.

### Restore normal response times

```bash
curl -s -X POST http://127.0.0.1:8000/control/recover
```

---

## 5. Cleanup

Stop the Flask application with `Ctrl+C`.

When finished, terminate the demo EC2 instance and remove unused CloudWatch resources to avoid unnecessary charges.

---

**That's the lab:** introduce a problem, observe its symptoms, investigate the evidence, and restore normal operation.
