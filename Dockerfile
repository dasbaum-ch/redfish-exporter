# syntax=docker/dockerfile:1.7
FROM python:3.14-slim-trixie
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

# Setup a non-root user
RUN groupadd --system --gid 999 nonroot \
 && useradd --system --gid 999 --uid 999 --create-home nonroot

WORKDIR /app

RUN chown nonroot:nonroot /app

# Enable bytecode compilation
ENV UV_COMPILE_BYTECODE=1

# Copy from the cache instead of linking since it's a mounted volume
ENV UV_LINK_MODE=copy

# Then, add the rest of the project source code and install it
# Installing separately from its dependencies allows optimal layer caching

# Use the non-root user to run our application
USER nonroot

COPY --chown=nonroot:nonroot . /app/
RUN uv sync --locked
# Place executables in the environment at the front of the path
ENV PATH="/app/.venv/bin:$PATH"

# Reset the entrypoint, don't invoke `uv`
ENTRYPOINT []


EXPOSE 8000

CMD [ "python", "main.py" ]
