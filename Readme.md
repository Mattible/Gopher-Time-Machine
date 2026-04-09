# 🐍⏳🐿️ Gopher Time Machine

A toy Go HTTP server packaged as a Docker image, paired with `travel.py` — a Python utility that backdates a Docker image's creation timestamp to any point in time (including the beginning of time).

## Project structure

```
.
├── Dockerfile      # Multi-stage build for the Go server
├── main.go         # Tiny HTTP server, responds on GET /hello
├── go.mod
├── makefile        # Convenience targets for build, backdate, run
└── travel.py       # Docker image timestamp backdating tool
```

## The Go server

A minimal HTTP server built with [`gorilla/mux`](https://github.com/gorilla/mux).

| Route | Method | Response |
|-------|--------|----------|
| `/` | GET | `Hello from <TIMESTAMP>` or `Hello from the beginning of Golang Time` |

The `TIMESTAMP` environment variable is baked into the image at build time via `--build-arg`. If it is not set the server falls back to `Hello from the beginning of Golang Time`.

## Makefile

All common workflows are wrapped in `make` targets. Run `make help` to see the full reference.

### Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `IMAGE` | `gopher-time-machine:latest` | Source image to build or backdate |
| `RESULT_TAG` | `gopher-time-machine:year-one` | Tag applied to the backdated image |
| `TARGET_DATE` | `0000-01-01T00:00:00Z` | Timestamp written into image metadata |
| `TIMESTAMP` | `$(TARGET_DATE)` | Timestamp baked into the binary at build time |

### Targets

```bash
# Build the image (TIMESTAMP baked in via --build-arg)
make build

# Build the image and immediately backdate its metadata
make build-date

# Backdate an already-built image's metadata
make backdate

# Inspect the creation timestamp of the backdated image
make inspect

# Run the backdated image on :8080
make run
```

### Common workflows

```bash
# Full pipeline with defaults (year-zero timestamp, N/A in docker images)
make build-date

# Full pipeline with a custom date (earliest)
make build-date TARGET_DATE=2027-01-01T00:00:01Z

# full pipeline with a custom date (latest)
make build-date TARGET_DATE=9999-12-31T23:59:59Z

# Backdate an image that was already built separately
make backdate IMAGE=gopher-time-machine:latest RESULT_TAG=gopher-time-machine:year-one

make backdate IMAGE=gopher-time-machine:latest RESULT_TAG=gopher-time-machine:future TARGET_DATE=9999-12-31T23:59:59Z

# Run will build and backdate by default, but you can also point it at an already backdated image.
make run IMAGE=EXISTING_TAG RESULT_TAG={NEW_TAG} TARGET_DATE={TIME_DATE}

make run IMAGE=gopher-time-machine:latest RESULT_TAG=gopher-time-machine:future TARGET_DATE=9999-12-31T23:59:59Z

# Verify the result
make inspect
curl http://localhost:8080/
```

## travel.py — timestamp backdating tool

Modifies a Docker image's creation metadata so it appears to have been built at any arbitrary point in time. Works with both modern OCI-layout images (Docker v25+) and the legacy flat tarball format.

It handles the full content-addressable blob chain: config → image manifest → manifest list → `index.json`, rehashing every blob it touches so Docker's digest verification passes.

### Usage

```bash
python3 travel.py <source-image> <result-tag> [target-date]
```

| Argument | Required | Description |
|----------|----------|-------------|
| `source-image` | yes | Existing local image to backdate |
| `result-tag` | yes | Tag to apply to the backdated image |
| `target-date` | no | ISO 8601 timestamp (default: `0001-01-01T00:00:00Z`) |

### How it works

1. `docker save` exports the image to a tar archive
2. The archive is extracted and the OCI layout is detected
3. The config blob is patched — all `created` timestamps are replaced
4. Each modified blob is rehashed and written under its new content-addressed filename; upstream digest references (`manifest.json`, image manifest, manifest list, `index.json`) are updated accordingly
5. The archive is repacked and loaded via `docker load`
6. The resulting image is tagged with the requested name

### Requirements

- Python 3.9+ (3.13+ recommended for best performance)
- Docker CLI available on `$PATH`
