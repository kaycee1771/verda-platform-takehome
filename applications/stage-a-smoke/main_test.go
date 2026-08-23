package main

import (
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestEndpointsAndMetrics(t *testing.T) {
	app := &application{environment: "test"}
	server := httptest.NewServer(app.handler())
	defer server.Close()

	response, err := http.Get(server.URL + "/")
	if err != nil {
		t.Fatal(err)
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		t.Fatalf("root status = %d", response.StatusCode)
	}
	var payload map[string]string
	if err := json.NewDecoder(response.Body).Decode(&payload); err != nil {
		t.Fatal(err)
	}
	if payload["service"] != "stage-a-smoke" || payload["environment"] != "test" {
		t.Fatalf("unexpected payload: %#v", payload)
	}

	for _, path := range []string{"/healthz", "/readyz"} {
		probe, probeErr := http.Get(server.URL + path)
		if probeErr != nil {
			t.Fatal(probeErr)
		}
		probe.Body.Close()
		if probe.StatusCode != http.StatusNoContent {
			t.Fatalf("%s status = %d", path, probe.StatusCode)
		}
	}

	metrics, err := http.Get(server.URL + "/metrics")
	if err != nil {
		t.Fatal(err)
	}
	defer metrics.Body.Close()
	body, err := io.ReadAll(metrics.Body)
	if err != nil {
		t.Fatal(err)
	}
	for _, expected := range []string{
		"stage_a_smoke_requests_total 1",
		`stage_a_smoke_build_info{environment="test",version="dev"} 1`,
	} {
		if !strings.Contains(string(body), expected) {
			t.Fatalf("metrics missing %q: %s", expected, body)
		}
	}
}
