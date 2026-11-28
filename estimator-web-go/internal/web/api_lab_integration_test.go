package web

import (
	"context"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
	"time"

	"estimator-web/internal/config"
)

// La cancelación del Chunking Lab debe llegar hasta el procesamiento de Python (no basta con cerrar la conexión de
// Go): el upstream observa el cierre, recibe una única solicitud y Go no persiste ninguna comparación incompleta.
// Usa Go real, el upstream Python aislado (FastAPI real con proveedor retenido) y PostgreSQL efímero.
func TestLabCancellationThroughPython(t *testing.T) {
	python := os.Getenv("PYTHON_FIXTURE_URL")
	if python == "" {
		t.Skip("requiere el upstream Python aislado (verification/verify-integration.sh)")
	}
	store := pgStore(t)
	server, err := New(config.Config{APIURL: python, CompareTimeout: 30 * time.Second}, store, nil)
	if err != nil {
		t.Fatal(err)
	}
	server.adminDecision = func(context.Context, administrativeOperation) (bool, error) { return true, nil }
	front := httptest.NewServer(server.Handler())
	defer front.Close()
	client := &http.Client{Timeout: 10 * time.Second}

	reset, err := client.Post(python+"/__test/reset/lab", "application/json", nil)
	if err != nil {
		t.Fatal(err)
	}
	_, _ = io.Copy(io.Discard, reset.Body)
	reset.Body.Close()
	if reset.StatusCode != 200 {
		t.Fatalf("reinicio: %d", reset.StatusCode)
	}

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	req, err := http.NewRequestWithContext(ctx, "POST", front.URL+labAPI, strings.NewReader(`{"strategies":["structural"]}`))
	if err != nil {
		t.Fatal(err)
	}
	req.Header.Set("Content-Type", "application/json")
	finished := make(chan error, 1)
	go func() {
		resp, err := client.Do(req)
		if resp != nil {
			resp.Body.Close()
		}
		finished <- err
	}()
	waitIntegrationState(t, client, python, func(s integrationState) bool { return s.ProviderActive })
	cancel()
	if err := <-finished; !errors.Is(err, context.Canceled) {
		t.Fatalf("cancelación del cliente: %v", err)
	}
	state := waitIntegrationState(t, client, python, func(s integrationState) bool { return s.ProviderClosed })
	if state.Posts != 1 || state.ProviderActive {
		t.Fatalf("Python no liberó el procesamiento de la comparación: %+v", state)
	}
	rows, err := store.Recent(context.Background(), 20)
	if err != nil {
		t.Fatal(err)
	}
	if len(rows) != 0 {
		t.Fatalf("se persistió una comparación incompleta: %d filas", len(rows))
	}
}
