# Load Test Yagna and Arkiv

Load testing tools for Yagna and Arkiv using Locust.

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

### Golem Service Setup

1. Copy the systemd service file to the systemd directory:
   ```bash
   sudo cp golem/systemd/locust-golem.service /etc/systemd/system/
   ```

2. **Important**: Update the `WorkingDirectory` path in `/etc/systemd/system/locust-golem.service` to match the actual location where you cloned the repository. The default path in the example file is `/root/locus-master/loadtest-yagna`.

3. Activate and start the service:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable locust-golem.service
   sudo systemctl start locust-golem.service
   sudo systemctl status locust-golem.service
   ```
   To view logs: `sudo journalctl -u locust-golem.service -f`

### Arkiv Service Setup

1. Copy the systemd service file to the systemd directory:
   ```bash
   sudo cp arkiv/systemd/locust-arkiv.service /etc/systemd/system/
   ```

2. **Important**: Update the `WorkingDirectory` path in `/etc/systemd/system/locust-arkiv.service` to match the actual location where you cloned the repository. The default path in the example file is `/root/locus-master/loadtest-yagna`.

3. Activate and start the service:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable locust-arkiv.service
   sudo systemctl start locust-arkiv.service
   sudo systemctl status locust-arkiv.service
   ```
   To view logs: `sudo journalctl -u locust-arkiv.service -f`

### Service Configuration

Both service files (`golem/systemd/locust-golem.service` and `arkiv/systemd/locust-arkiv.service`) are configured to:
- Run Locust in master mode
- Bind the web interface to `0.0.0.0` (accessible from all network interfaces)
- Automatically restart on failure with a 5-second delay
- Start automatically on system boot

### Stopping the Services

To stop a service:
```bash
# Stop Golem service
sudo systemctl stop locust-golem.service

# Stop Arkiv service
sudo systemctl stop locust-arkiv.service
```


