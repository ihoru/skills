# syntax=docker/dockerfile:1
FROM golang:1.25-alpine AS build
WORKDIR /src
ADD --checksum=sha256:e469b236bf3f0f52a053bfd8cb73916f49001db1aeba04b463b0757ed01c1476 https://raw.githubusercontent.com/moby/buildkit/v0.20.2/README.md buildkit-readme.md
COPY main.go .
RUN CGO_ENABLED=0 go build -trimpath \
    -ldflags "-X main.buildInput=$(sha256sum buildkit-readme.md | cut -d' ' -f1)" \
    -o /out/app main.go

FROM scratch
COPY --from=build /out/app /app
USER 65532:65532
HEALTHCHECK NONE
EXPOSE 8080
ENTRYPOINT ["/app"]
