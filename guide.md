# Developer Operations Guide

## 1. Manual Execution (Development Mode)

### 1.1 Initialize Secure Tunnel
Establish the Cloudflare tunnel to expose the local server.
```bash
cloudflared tunnel run raspi-tunnel
```

### 1.2 Activate Virtual Environment
Load the project's isolated Python environment dependencies.

```bash
source my_env/bin/activate
```

### 1.3 Execute Application Entry Points
Choose the appropriate mode for your testing requirements.

#### 1.3.1 Web Interface Only (Lightweight Mode)
Run this command to initialize the web server for UI testing without hardware/bot interactions.

```bash
python3 webapp.py
```

#### 1.3.2 Full System Initialization (Bot & Hardware Mode)
Run this command to activate the main application, including robot control logic, voice processing, and hardware communication.

``` bash
python3 main.py
```

### 1.4 Deactivate Environment
Exit the virtual environment when development operations are complete.

```bash
deactivate
```

## 2. System Daemon Management (Production)
The project is configured to run as a background daemon using `systemd`. Use the following commands to manage the application lifecycle and persistence.

### 2.1 Enable Boot Persistence
Configure the services to launch automatically upon system startup.

```bash
sudo systemctl enable hanah-app.service
sudo systemctl enable cloudflared.service
```

### 2.2 Start Services
Manually start the services immediately without rebooting.

```bash
sudo systemctl start hanah-app.service
sudo systemctl start cloudflared.service
```

### 2.3 Monitoring & Logging
Verify service health and inspect real-time logs for debugging.

Check Service Status:

```bash
systemctl status hanah-app.service
systemctl status cloudflared.service
```
Stream Real-time Logs:
```bash
journalctl -u hanah-app.service -f
journalctl -u cloudflared.service -f
```

### 2.4 Restart Services
Reload the application to apply code changes or recover from errors.

```bash
sudo systemctl restart hanah-app.service
sudo systemctl restart cloudflared.service
```

### 2.5 Service Configuration Modification
To modify the service definition (e.g., environment variables, execution paths):

#### 1. Edit the service file:

```bash
sudo nano /etc/systemd/system/<Name.service>
# Example: sudo nano /etc/systemd/system/hanah-app.service
```
#### 2. Reload the systemd daemon: 
Required to register changes made to the `.service` file.

```bash
sudo systemctl daemon-reload
```
#### 3. Apply changes: 
Restart the service to implement the new configuration.

```bash
sudo systemctl restart hanah-app.service
```

### 2.6 Service Stop
### 1. Temporary stop 
Stop the service to run project manually 
```bash
sudo systemctl stop hanah-app.service
sudo systemctl stop cloudflared.service
```
### 2. Completely stop
Stop the service start up completely 
```bash
# 1. Stop service immediately
sudo systemctl stop hanah-app.service

# 2. Prevent service start after reboot 
# Hanah main program
sudo systemctl stop hanah-app.service
sudo systemctl disable hanah-app.service
# Cloudflare
sudo systemctl stop hanah-tunnel.service
sudo systemctl disable hanah-tunnel.service

# 3. Update system
sudo systemctl daemon-reload
```