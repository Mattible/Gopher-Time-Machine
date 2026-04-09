# ── configurable variables ────────────────────────────────────────────────────
IMAGE       ?= gopher-time-machine:latest
RESULT_TAG  ?= gopher-time-machine:year-one
TARGET_DATE ?= 0000-01-01T00:00:00Z

# TIMESTAMP is baked into the image at build time (used by the /hello endpoint).
# Defaults to TARGET_DATE so the server message matches the backdated metadata.
TIMESTAMP   ?= $(TARGET_DATE)

# ── targets ───────────────────────────────────────────────────────────────────

.PHONY: help build backdate build-and-backdate run

help:
	@echo ""
	@echo "Usage:"
	@echo "  make build               Build the Docker image (IMAGE, TIMESTAMP)"
	@echo "  make build-date          Build the image, then backdate its metadata"
	@echo "  make backdate            Backdate an existing image's metadata (IMAGE, RESULT_TAG, TARGET_DATE)"
	@echo "  make inspect             Check the metadata of the backdated image (RESULT_TAG)"
	@echo "  make run                 Run the backdated image locally on :8080"
	@echo ""
	@echo "Variables (override on the command line):"
	@echo "  IMAGE       Source image to build/backdate  [$(IMAGE)]"
	@echo "  RESULT_TAG  Tag for the backdated image     [$(RESULT_TAG)]"
	@echo "  TARGET_DATE Timestamp to embed in metadata  [$(TARGET_DATE)]"
	@echo "  TIMESTAMP   Timestamp baked into the binary [$(TIMESTAMP)]"
	@echo ""

## Build the Docker image with TIMESTAMP baked in via --build-arg
build:
	docker build \
		--build-arg timestamp="$(TIMESTAMP)" \
		-t $(IMAGE) .

## Backdate an existing image's creation metadata using travel.py
backdate:
	python3 travel.py $(IMAGE) $(RESULT_TAG) $(TARGET_DATE)

## Build the image then immediately backdate its metadata
build-date: build backdate

## Check the metadata of the backdated image
inspect:
	docker images --no-trunc --format '{{.Repository}}:{{.Tag}} - CreatedAt: {{.CreatedAt}}' $(RESULT_TAG)

## Run the backdated image and expose it on port 8080
run: build backdate
	docker run --rm -p 8080:8080 $(RESULT_TAG)
