Northstar Shop — AWS Observability Lab
This is the small Flask checkout app I use to demonstrate logs, metrics, and traces on AWS. We'll deliberately break or slow down checkout, then investigate what happened.
All commands below run on the EC2 instance, unless stated otherwise.
1. Launch EC2 and start the app
Launch an Amazon Linux 2023 instance and attach an IAM role with `AmazonSSMManagedInstanceCore` and `CloudWatchAgentServerPolicy`.
In the security group, allow SSH (22) and TCP 8000 from your own public IP only (`/32`). The demo controls have no authentication, so don't expose port 8000 to everyone.
SSH into EC2, then run:
```bash
sudo dnf install -y git python3 stress-ng

git clone https://github.com/njamutoh/cloudwatch-observability-demo-app.git
cd cloudwatch-observability-demo-app/ec2-cloudwatch-demo-app

python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt

# Allow browser access through the EC2 public IP (only from your permitted IP).
sed -i 's/host="127.0.0.1"/host="0.0.0.0"/' app.py
python app.py
```
Leave Flask running. Open another SSH terminal and run:
```bash
cd ~/cloudwatch-observability-demo-app/ec2-cloudwatch-demo-app
curl -i http://127.0.0.1:8000/health
curl -i http://127.0.0.1:8000/checkout
```
The graphical storefront is available in your browser at `http://EC2_PUBLIC_IP:8000/`. Replace `EC2_PUBLIC_IP` with the instance's public IPv4 address.
2. Logs — generate HTTP 503 errors
In AWS: Open CloudWatch → Configure CloudWatch agent. Select the EC2 instance, install/configure the agent through Systems Manager, and add this log collection:
Setting	Value
Log file path	`/home/ec2-user/cloudwatch-observability-demo-app/ec2-cloudwatch-demo-app/app.log`
Log group	`/aws/ec2/demowatch`
Log stream	`{instance_id}`
Leave filters empty and deploy. The SSM Agent must be connected for console-based installation.
If you need to check agent status:
```bash
sudo systemctl is-active amazon-ssm-agent
sudo systemctl is-active amazon-cloudwatch-agent
```
Induce 10 failed checkout requests:
```bash
curl -s -X POST http://127.0.0.1:8000/control/fail

for i in {1..10}; do
  curl -s -o /dev/null -w 'HTTP %{http_code}\n' \
    http://127.0.0.1:8000/checkout
done
```
Inspect errors locally:
```bash
grep '"level":"ERROR"' app.log | tail -n 10
```
Or watch new errors as they happen:
```bash
tail -n 0 -F app.log | grep --line-buffered '"level":"ERROR"'
```
In AWS: Open CloudWatch → Logs → Log groups → `/aws/ec2/demowatch`. You can also use Logs Insights:
```sql
fields @timestamp, level, status, message
| filter status = 503
| sort @timestamp desc
| limit 20
```
Restore checkout when you're done:
```bash
curl -s -X POST http://127.0.0.1:8000/control/recover
```
3. Metrics — create a CPU utilization spike
In AWS: Enable EC2 detailed monitoring if you want one-minute CPU data points. This demo uses the built-in `CPUUtilization` metric.
Stress both vCPUs for two minutes:
```bash
stress-ng --cpu 2 --cpu-load 100 --timeout 2m --metrics-brief
```
In another EC2 terminal, watch CPU usage immediately:
```bash
top
```
In AWS: Open EC2 → Instances → Monitoring → CPU utilization. Use Last 1 hour, Average, and a 1-minute period if detailed monitoring is enabled. CloudWatch takes a little time to show new data points.
4. Traces — investigate a slow checkout
In AWS: In the CloudWatch Agent configuration, enable AWS X-Ray traces and deploy. Keep the default X-Ray receiver on `127.0.0.1:2000` (UDP); port 8000 is for the web app.
Check the receiver on EC2:
```bash
sudo ss -lunp | grep ':2000'
```
Generate five slow requests:
```bash
curl -s -X POST http://127.0.0.1:8000/control/recover
curl -s -X POST http://127.0.0.1:8000/control/slow

for i in {1..5}; do
  curl -s -o /dev/null \
    -w 'HTTP %{http_code} | Time: %{time_total}s\n' \
    http://127.0.0.1:8000/checkout
done
```
In AWS: Open CloudWatch → X-Ray traces → Traces. Find a recent `GET /checkout` trace, inspect its roughly 1.5-second duration, and look for the `checkout-business-logic` subsegment.
Restore normal response times:
```bash
curl -s -X POST http://127.0.0.1:8000/control/recover
```
Cleanup
Stop Flask with Ctrl+C. When finished with the lab, terminate the demo EC2 instance and remove unused CloudWatch resources to avoid ongoing charges.
