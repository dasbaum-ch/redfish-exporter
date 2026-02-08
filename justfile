# Default task
default:
    just --list

# Setup dependencies
setup:
    uv sync
    uv lock --upgrade --refresh
    pre-commit install

# Lint the code
lint:
    ruff check .

# Format the code
format:
    ruff format .

# Setup pre-commit
pre-commit:
    pre-commit install

# Run the exporter
run:
    python redfish-exporter --config config.yaml

# Run the exporter with custom config
run-custom config="config.custom.yaml":
    python redfish-exporter --config {{config}}

# Run the exporter with custom port
run-port port="9000":
    python redfish-exporter --config config.yaml --port {{port}}

# Run the exporter with custom interval
run-interval interval="10":
    python redfish-exporter --config config.yaml --interval {{interval}}

# Build Docker image
docker-build:
    docker buildx build -t redfish_exporter .

# Run Docker container
docker-run:
    docker run -it --rm --name redfish_exporter_app -p 8000:8000 redfish_exporter:latest

# Run Docker container with custom port
docker-run-port port="9000":
    docker run -it --rm --name redfish_exporter_app -p {{port}}:8000 redfish_exporter:latest

# Install systemd service
install-systemd:
    sudo cp redfish-exporter.service /etc/systemd/system/redfish-exporter.service
    sudo systemctl daemon-reload
    sudo systemctl enable --now redfish-exporter.service
