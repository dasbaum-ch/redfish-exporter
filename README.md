# Redfish Exporter
A Python-based Prometheus exporter for collecting power data (Watts, Volts, Amperes) from bare metal servers using the Redfish API. This tool supports multiple vendors (e.g., HPE, Supermicro).

I've createtd this python script to collect Power data to analyse Watts, Volts and Amperes. If there is a better solution, feel free to replace me.

---

## Table of Contents
- [Redfish Exporter](#redfish-exporter)
  - [Table of Contents](#table-of-contents)
  - [Description](#description)
  - [Features](#features)
  - [Usage](#usage)
- [Installation](#installation)
  - [Requirements](#requirements)
  - [Configuration](#configuration)
    - [Basic Configuration](#basic-configuration)
    - [Basic Configuration](#basic-configuration-1)
- [Container](#container)
- [Legacy Installation](#legacy-installation)
  - [Python Dependencies](#python-dependencies)
  - [Create user](#create-user)
  - [Systemd Service](#systemd-service)
- [Testet on Hardware](#testet-on-hardware)
- [License](#license)

---

## Description
This tool collects power metrics from servers using the Redfish API and exposes them in a format compatible with Prometheus. It supports both modern and legacy Redfish API versions and handles authentication for different vendors.

---

## Features
- Collects power metrics: Watts, Volts, and Amperes.
- Supports multiple vendors (HPE, Supermicro, etc.).
- Cross-platform compatibility (Linux and Windows).
- Graceful error handling and retry logic.
- Configurable via YAML.
- Docker support.

## Usage
```bash
usage: redfish_exporter.py [-h] [--config CONFIG] [--port PORT] [--interval INTERVAL]

Redfish Prometheus Exporter

options:
  -h, --help            show this help message and exit
  --config CONFIG       Path to config file
  --port PORT           Override port from config file
  --interval INTERVAL   Override interval from config file
```

# Installation

## Requirements
Requirements:

* Python 3.8+
* see `pyproject.toml`

Install the dependencies using:

```bash
cd /srv/redfish-exporter
uv sync
source .venv/bin/activate
uv lock --upgrade --refresh
```

## Configuration
Create a `config.yaml` file with the following structure:

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

### Basic Configuration
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

The `port`, `interval` are optional and can be overwritten by argument. Save default values are hardcoded.


# Container
To run the Redfish Exporter in a Docker container:

```
docker buildx build -t your-tag .
docker run -it --rm --name redfish_exporter_app -p 8000:8000 your-tag:latest
```

# Legacy Installation
```bash
mkdir /srv/redfish-exporter
# or
git clone https://github.com/dasbaum-ch/redfish-exporter.git /srv/redfish-exporter
```

## Python Dependencies
```bash
cd /srv/redfish-exporter
uv sync
source .venv/bin/activate
uv lock --upgrade --refresh
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
1. Reload and start the service:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now redfish-exporter.service
```

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

# License
This project is licensed under the MIT License. See the LICENSE file for details.
