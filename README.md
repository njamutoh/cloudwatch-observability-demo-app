# Northstar Shop: AWS Observability Lab

I use this small Flask checkout app on EC2 to demonstrate three things: finding application errors in CloudWatch Logs, spotting a CPU spike in EC2 metrics, and investigating a slow request in AWS X-Ray.

The commands below run **on EC2** unless I say otherwise.

## 1. Launch EC2 and run the app

Launch an **Amazon Linux 2023** instance. Allow SSH (port 22) and **Custom TCP port 8000** from **your public IP only** (`/32`) in its security group. Attach an instance role with `AmazonSSMManagedInstanceCore` and `CloudWatchAgentServerPolicy`. The lab controls are unauthenticated, so **never open port 8000 to everyone**.

SSH into EC2 and run:

```bash
sudo dnf install -y git python3 stress-ng
git clone https://github.com/njamutoh/cloudwatch-observability-demo-app.git
cd cloudwatch-observability-demo-app/ec2-cloudwatch-demo-app
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
# For direct browser access from your IP, bind Flask to the instance network interface.
# In app.py, set app.run(host="0.0.0.0", port=8000, ...).
python app.py
```

Leave that terminal running. In a **second EC2 terminal**, enter the app directory and check it:

```bash
cd ~/cloudwatch-observability-demo-app/ec2-cloudwatch-demo-app
curl -i http://127.0.0.1:8000/health
curl -i http://127.0.0.1:8000/checkout
```

To open the graphical Northstar Shop interface, find the instance's **Public IPv4 address** in the EC2 console and visit:

```text
http://EC2_PUBLIC_IP:8000/
```

This is how the live demo is accessed. Make sure `app.py` binds to `0.0.0.0` and the security group permits port 8000 **only from your IP**. The built-in Flask server and unauthenticated `/control/*` endpoints are for this temporary lab, not public deployment.

**More secure alternative:** Keep Flask bound to `127.0.0.1` and forward port 8000 over SSH instead; then use `http://127.0.0.1:8000/` on your local machine.

## 2. Logs: generate HTTP 503 errors

**AWS setup:** In **CloudWatch → Configure CloudWatch agent**, select your instance and install/configure the agent through Systems Manager. SSM Agent needs to show as connected first. Configure a log file collection with:

- **File:** `/home/ec2-user/cloudwatch-observability-demo-app/ec2-cloudwatch-demo-app/app.log`
- **Log group:** `/aws/ec2/demowatch`
- **Log stream:** `{instance_id}`

Leave include/exclude filters empty, then deploy the configuration. If the console cannot see SSM, check `sudo systemctl is-active amazon-ssm-agent` on EC2. After deployment, check the CloudWatch Agent with `sudo systemctl is-active amazon-cloudwatch-agent`.

**Live demo:** In the second EC2 terminal:

```bash
curl -s -X POST http://127.0.0.1:8000/control/fail
for i in {1..10}; do
  curl -s -o /dev/null -w 'HTTP %{http_code}\n' http://127.0.0.1:8000/checkout
done
grep '"level":"ERROR"' app.log | tail -n 10
curl -s -X POST http://127.0.0.1:8000/control/recover
```

To watch **new errors live**, use this in a separate EC2 terminal:

```bash
tail -n 0 -F app.log | grep --line-buffered '"level":"ERROR"'
```

**In AWS:** Go to **CloudWatch → Logs → Log groups → `/aws/ec2/demowatch`**, or use Logs Insights:

```sql
fields @timestamp, level, status, message
| filter status = 503
| sort @timestamp desc
| limit 20
```

CloudWatch logs can arrive a little later than they appear in `app.log`.

## 3. Metrics: push CPU utilization up

**AWS setup:** Enable **EC2 detailed monitoring** if you want one-minute CPU datapoints. This uses the built-in `CPUUtilization` metric, so there's no need to create custom application metrics for this test.

**Live demo:** Run on EC2:

```bash
stress-ng --cpu 2 --cpu-load 100 --timeout 2m --metrics-brief
```

Open `top` in another EC2 terminal to see CPU usage immediately:

```bash
top
```

**In AWS:** Go to **EC2 → Instances → Monitoring → CPU utilization**. Use the **1-hour** view and **1-minute** period (with detailed monitoring). CloudWatch takes some time to publish the new datapoints, even though CPU rises immediately on EC2.

## 4. Traces: investigate a slow checkout

**AWS setup:** In the CloudWatch Agent configuration, enable **AWS X-Ray traces** and deploy. Keep its default receiver at **`127.0.0.1:2000` (UDP)**. Port 8000 is for the web app, not X-Ray.

Check the X-Ray receiver on EC2:

```bash
sudo ss -lunp | grep ':2000'
```

**Live demo:**

```bash
curl -s -X POST http://127.0.0.1:8000/control/recover
curl -s -X POST http://127.0.0.1:8000/control/slow
for i in {1..5}; do
  curl -s -o /dev/null -w 'HTTP %{http_code} | Time: %{time_total}s\n' http://127.0.0.1:8000/checkout
done
curl -s -X POST http://127.0.0.1:8000/control/recover
```

**In AWS:** Open **CloudWatch → X-Ray traces → Traces** in the same region. Find a recent `GET /checkout` trace, check the ~1.5-second duration, and inspect the `checkout-business-logic` subsegment.

## When you're done

Stop Flask with `Ctrl+C`. Terminate the demo EC2 instance when you no longer need it, and clean up unused CloudWatch resources to avoid ongoing charges.
