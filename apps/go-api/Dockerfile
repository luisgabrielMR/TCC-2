FROM golang:1.23-bookworm@sha256:167053a2bb901972bf2c1611f8f52c44d5fe7e762e5cab213708d82c421614db AS build

WORKDIR /src

COPY go.mod go.sum .
RUN go mod download

COPY main.go .
RUN CGO_ENABLED=0 GOOS=linux go build -o /out/go-api .

FROM debian:bookworm-slim@sha256:abd67ffcfa541b485a3dff59865ab629aa048a6c613e639d36e7456b0b229241

ENV PORT=8000

WORKDIR /app
COPY --from=build /out/go-api /app/go-api

EXPOSE 8000

CMD ["/app/go-api"]
