FROM golang:1.23-bookworm AS build

WORKDIR /src

COPY go.mod go.sum .
RUN go mod download

COPY main.go .
RUN CGO_ENABLED=0 GOOS=linux go build -o /out/go-api .

FROM debian:bookworm-slim

ENV PORT=8000

WORKDIR /app
COPY --from=build /out/go-api /app/go-api

EXPOSE 8000

CMD ["/app/go-api"]
