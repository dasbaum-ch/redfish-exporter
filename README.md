# Redfish-Exporter

A Python-based Prometheus exporter for collecting power data (Watts, Volts, Amperes) from bare metal servers using the Redfish API. This tool supports multiple vendors (e.g., HPE, Supermicro) and is designed to run cross-platform on Linux and Windows.

I've createtd this python script to collect Power data to analyse Watts, Volts and Amperes. If there is a better solution or you want more feature, feel free to replace me or expand my prometheus exporter.

---

## Features

- Collects power metrics: Watts, Volts, and Amperes.
- Supports multiple vendors (HPE, Supermicro, etc.).
- Cross-platform compatibility (Linux and Windows).
- Graceful error handling and retry logic.
- Configurable via YAML.
- Docker support.

---

## Usage

```
usage: python main.py [-h] [--config CONFIG] [--port PORT]

Redfish Prometheus Exporter

options:
  -h, --help       show this help message and exit
  --config CONFIG  Path to config file
  --port PORT      Override port from config file
```

---

# Install

## Requirements

* python 3.8+
* see `pyproject.tom`

Install the dependencies using `uv`:

```bash
uv sync
source .venv/bin/activate
uv lock --upgrade --refresh
```

## Configuration

Create `config.yaml` with following structure:

### Basic Configuration

```yaml
---
interval: 5
port: 8000
username: user
password: secret
chassis: ["1"]
hosts:
  - host1.example.net
  - host2.example.net
  - host3.example.net
  - host4.example.net
```

### Advanced Configuration

```yaml
---
interval: 5
port: 8000
username: user1
password: secret1
chassis: ["1"]
hosts:
  - fqdn: host1.example.net
    username: user2
    password: secret2
    chassis: ["0"]
  - fqdn: host2.example.net
    username: user3
    password: secret3
    chassis: ["1"]
  - fqdn: host3.example.net
    username: user4
    password: secret4
    chassis: ["example"]
  - fqdn: host4.example.net
    username: user5
    password: secret5
```

The `port`, `interval` are optional and can be be overridden by command-line arguments. Default values are hardcoded.

# Docker / Container

To run the Redfish Exporter in a Docker container:

```
docker buildx build -t redfish_exporter .
docker run -it --rm --name redfish_exporter_app -p 8000:8000 redfish_exporter:latest
```

# Legacy Installation

## Python Dependencies

```bash
mkdir /srv/redfish-exporter
# or
git clone https://github.com/dasbaum-ch/redfish-exporter.git /srv/redfish-exporter
cd /srv/redfish-exporter
uv sync --locked
```

## Create user

```bash
sudo useradd -r -s /bin/false redfish
```

## Systemd Service

1. Copy the systemd unit file:

```bash
sudo cp redfish-exporter.service /etc/systemd/system/redfish-exporter.service
```

2. Reload and start the service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now redfish-exporter.service
```

# License

This project is licensed under the MIT License. See the LICENSE file for details.

# Testet on Hardware

Here some Server's that I have successfully testet:
* Supermicro
  * AS -5126GS-TNRT2
    * Redfish 1.21.0
  * AS -1124US-TNRP
    * Redfish 1.8.0
* HPE
  * ProLiant DL380 Gen10
  * Redfish 1.6.0
