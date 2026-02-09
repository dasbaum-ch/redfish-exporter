# Redfish-Interface-Emulator

Source: https://github.com/DMTF/Redfish-Interface-Emulator

This command runs the container with the built-in mockup:
```bash
docker run --rm dmtf/redfish-interface-emulator:latest
```

or use my `test/compose.yaml`:
```yaml
services:
  redfish-server:
    image: dmtf/redfish-interface-emulator:latest 
    container_name: redfish-server
    ports:
      - "5000:5000"
    restart: unless-stopped
```
an run it with
```bash
docker compose up -d
```
