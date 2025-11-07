# Load Test Yagna

Load testing tool for Yagna using Locust.

## Systemd Service Setup

To set up the Locust master service on a machine using systemd:

### Prerequisites

1. Ensure you have Poetry installed:
   ```bash
   curl -sSL https://install.python-poetry.org | python3 -
   ```

2. Clone this repository to a location accessible by the systemd service user (e.g., `/root/locus-master/loadtest-yagna`):
   ```bash
   git clone <repository-url> /root/locus-master/loadtest-yagna
   cd /root/locus-master/loadtest-yagna
   ```

3. Install dependencies using Poetry:
   ```bash
   poetry install
   ```

### Setup Steps

1. Copy the systemd service file to the systemd directory:
   ```bash
   sudo cp golem/systemd/locust.service /etc/systemd/system/
   ```

2. **Important**: Update the `WorkingDirectory` path in `/etc/systemd/system/locust.service` to match the actual location where you cloned the repository. The default path in the example file is `/root/locus-master/loadtest-yagna`.

3. Activate and start the service:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable locust.service
   sudo systemctl start locust.service
   sudo systemctl status locust.service
   ```
   To view logs: `sudo journalctl -u locust.service -f`

### Service Configuration

The service file (`golem/systemd/locust.service`) is configured to:
- Run Locust in master mode
- Bind the web interface to `0.0.0.0` (accessible from all network interfaces)
- Automatically restart on failure with a 5-second delay
- Start automatically on system boot

### Stopping the Service

To stop the service:
```bash
sudo systemctl stop locust.service
```


