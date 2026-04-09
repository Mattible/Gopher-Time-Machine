FROM --platform=$BUILDPLATFORM golang:1.25-alpine AS builder
ARG TARGETOS TARGETARCH BUILDPLATFORM

RUN apk add --no-cache git
COPY . .
RUN go mod download
RUN GOOS=${TARGETOS} GOARCH=${TARGETARCH} go build -o main .
RUN adduser -D appuser

RUN chown appuser:appuser /go/main

FROM scratch
WORKDIR /app

ARG timestamp=""
ENV TIMESTAMP=${timestamp}

COPY --from=builder /go/main .
COPY --from=builder /etc/passwd /etc/passwd

USER appuser

EXPOSE 8080
ENTRYPOINT [ "./main" ]