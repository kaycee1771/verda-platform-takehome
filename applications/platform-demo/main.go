package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/signal"
	"sync/atomic"
	"syscall"
	"time"
)

var version = "dev"

type application struct {
	environment string
	requests    atomic.Uint64
}

type event struct {
	Level       string `json:"level"`
	Marker      string `json:"marker"`
	Event       string `json:"event"`
	Environment string `json:"environment"`
	Version     string `json:"version"`
	Method      string `json:"method,omitempty"`
	Path        string `json:"path,omitempty"`
	Status      int    `json:"status,omitempty"`
}

func (a *application) emit(item event) {
	item.Marker = "platform_demo"
	item.Environment = a.environment
	item.Version = version
	encoded, err := json.Marshal(item)
	if err != nil {
		log.Printf(`{"level":"error","marker":"platform_demo","event":"json_encode_failed"}`)
		return
	}
	log.Print(string(encoded))
}

func (a *application) handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /", func(response http.ResponseWriter, request *http.Request) {
		a.requests.Add(1)
		response.Header().Set("Content-Type", "application/json")
		response.WriteHeader(http.StatusOK)
		_, _ = fmt.Fprintf(response, `{"service":"platform-demo","environment":%q,"version":%q}`+"\n", a.environment, version)
		a.emit(event{Level: "info", Event: "request", Method: request.Method, Path: request.URL.Path, Status: http.StatusOK})
	})
	mux.HandleFunc("GET /healthz", func(response http.ResponseWriter, _ *http.Request) {
		response.WriteHeader(http.StatusNoContent)
	})
	mux.HandleFunc("GET /readyz", func(response http.ResponseWriter, _ *http.Request) {
		response.WriteHeader(http.StatusNoContent)
	})
	mux.HandleFunc("GET /metrics", func(response http.ResponseWriter, _ *http.Request) {
		response.Header().Set("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
		_, _ = fmt.Fprintf(response, "# HELP platform_demo_requests_total Successful root requests.\n")
		_, _ = fmt.Fprintf(response, "# TYPE platform_demo_requests_total counter\n")
		_, _ = fmt.Fprintf(response, "platform_demo_requests_total %d\n", a.requests.Load())
		_, _ = fmt.Fprintf(response, "# HELP platform_demo_build_info Build and environment identity.\n")
		_, _ = fmt.Fprintf(response, "# TYPE platform_demo_build_info gauge\n")
		_, _ = fmt.Fprintf(response, "platform_demo_build_info{environment=%q,version=%q} 1\n", a.environment, version)
	})
	return mux
}

func main() {
	log.SetFlags(0)
	log.SetOutput(os.Stdout)
	environment := os.Getenv("APP_ENVIRONMENT")
	if environment == "" {
		environment = "unknown"
	}
	app := &application{environment: environment}
	server := &http.Server{
		Addr:              ":8080",
		Handler:           app.handler(),
		ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout:       10 * time.Second,
		WriteTimeout:      10 * time.Second,
		IdleTimeout:       60 * time.Second,
	}

	app.emit(event{Level: "info", Event: "ready"})
	stop := make(chan os.Signal, 1)
	signal.Notify(stop, syscall.SIGINT, syscall.SIGTERM)
	go func() {
		<-stop
		ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		if err := server.Shutdown(ctx); err != nil {
			app.emit(event{Level: "error", Event: "shutdown_failed"})
		}
	}()

	if err := server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
		app.emit(event{Level: "error", Event: "serve_failed"})
		os.Exit(1)
	}
	app.emit(event{Level: "info", Event: "stopped"})
}
