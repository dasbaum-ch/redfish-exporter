# Description

I've createtd this python script to collect Power data to analyse Watts, Volts and Amperes. If there is a better solution, feel free to replace me.

Usage:

```
usage: python main.py [-h] [--config CONFIG] [--port PORT]

Redfish Prometheus Exporter

options:
  -h, --help       show this help message and exit
  --config CONFIG  Path to config file
  --port PORT      Override port from config file
```

# Install

## Requirements

Dependencies:

* see requirements.txt

## Configuration

Create `config.yaml`:

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

or:

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


# Use as Container

```
docker buildx build -t your-tag .
docker run -it --rm --name redfish_exporter_app -p 8000:8000 your-tag:latest
```

# Legacy way

```bash
mkdir /srv/redfish-exporter
# or
git clone https://github.com/dasbaum-ch/redfish-exporter.git /srv/redfish-exporter
```

## Python dependencies

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

## Install systemd unit file

```bash
sudo cp redfish-exporter.service /etc/systemd/system/redfish-exporter.service
sudo systemctl daemon-reload
sudo systemctl enable --now redfish-exporter.service
```
