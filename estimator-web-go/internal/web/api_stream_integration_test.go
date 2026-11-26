package web

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"io"
	"math/big"
	"net/http"
	"net/http/httptest"
	"os"
	"reflect"
	"strings"
	"testing"
	"time"

	"estimator-web/internal/config"
)

type integrationState struct {
	Rows           []string `json:"rows"`
	CacheWrites    int      `json:"cache_writes"`
	Posts          int      `json:"posts"`
	ProviderActive bool     `json:"provider_active"`
	ProviderClosed bool     `json:"provider_closed"`
	Writing        bool     `json:"writing"`
	WriteClosed    bool     `json:"write_closed"`
	Committed      int      `json:"committed"`
	ResponseClosed bool     `json:"response_closed"`
}

func TestSSECancellationThroughPython(t *testing.T) {
	python := os.Getenv("BLOCK2_SSE_FIXTURE_URL")
	if python == "" {
		t.Skip("requiere el upstream Python aislado del Bloque 2")
	}
	web, err := New(config.Config{APIURL: python}, nil, nil)
	if err != nil {
		t.Fatal(err)
	}
	front := httptest.NewServer(web.Handler())
	defer front.Close()
	client := &http.Client{Timeout: 5 * time.Second}
	for _, scenario := range []string{"before", "write", "after", "transcription"} {
		t.Run(scenario, func(t *testing.T) {
			reset, err := client.Post(python+"/__test/reset/"+scenario, "application/json", nil)
			if err != nil {
				t.Fatal(err)
			}
			_, _ = io.Copy(io.Discard, reset.Body)
			reset.Body.Close()
			if reset.StatusCode != 200 {
				t.Fatalf("reinicio: %d", reset.StatusCode)
			}
			ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
			defer cancel()
			path, input := "/api/v1/estimate/stream", estimateRequest
			if scenario == "transcription" {
				path, input = "/api/v1/transcription/estimate/stream", transcriptionRequest
			}
			req, _ := http.NewRequestWithContext(ctx, "POST", front.URL+path, strings.NewReader(input))
			req.Header.Set("Content-Type", "application/json")
			response, err := client.Do(req)
			if err != nil {
				t.Fatal(err)
			}
			defer response.Body.Close()
			if response.StatusCode != 200 {
				t.Fatalf("estado SSE: %d", response.StatusCode)
			}
			var deliveredResult []byte
			if scenario == "after" || scenario == "transcription" {
				frame, err := readEvent(bufio.NewReader(response.Body))
				if err != nil || (scenario == "after" && frame.kind != "result") || (scenario == "transcription" && frame.kind != "token") {
					t.Fatalf("primer evento: %q %v", frame.kind, err)
				}
				deliveredResult = frame.data
			}
			before := waitIntegrationState(t, client, python, func(s integrationState) bool {
				switch scenario {
				case "before", "transcription":
					return s.ProviderActive
				case "write":
					return s.Writing && s.ProviderClosed
				default:
					return s.Committed == 1 && s.ProviderClosed
				}
			})
			cancel()
			state := waitIntegrationState(t, client, python, func(s integrationState) bool {
				switch scenario {
				case "write":
					return s.WriteClosed
				case "after":
					return s.ResponseClosed
				default:
					return s.ProviderClosed
				}
			})
			expected := 0
			if scenario == "after" {
				expected = 1
			}
			if scenario == "after" {
				verifyConfirmedRow(t, before.Rows, state.Rows, deliveredResult)
			}
			expectedCacheWrites := 0
			if scenario == "write" || scenario == "after" {
				expectedCacheWrites = 2
			}
			if state.CacheWrites != expectedCacheWrites || state.Posts != 1 || state.Committed != expected || state.ProviderActive || (scenario == "before" && state.Writing) {
				t.Fatalf("estado final: %+v", state)
			}
		})
	}
}

// La encuesta espera una barrera explícita del fixture y limita el tiempo de diagnóstico.
func waitIntegrationState(t *testing.T, client *http.Client, python string, ready func(integrationState) bool) integrationState {
	t.Helper()
	deadline := time.Now().Add(3 * time.Second)
	var state integrationState
	for time.Now().Before(deadline) {
		r, err := client.Get(python + "/__test/state")
		if err != nil {
			t.Fatal(err)
		}
		err = json.NewDecoder(r.Body).Decode(&state)
		r.Body.Close()
		if err != nil {
			t.Fatal(err)
		}
		if ready(state) {
			return state
		}
		time.Sleep(10 * time.Millisecond)
	}
	t.Fatalf("no se alcanzó la barrera: %+v", state)
	return state
}

func TestRESTCancellationThroughPython(t *testing.T) {
	python := os.Getenv("BLOCK2_SSE_FIXTURE_URL")
	if python == "" {
		t.Skip("requiere el upstream Python aislado del Bloque 2")
	}
	server, err := New(config.Config{APIURL: python}, nil, nil)
	if err != nil {
		t.Fatal(err)
	}
	front := httptest.NewServer(server.Handler())
	defer front.Close()
	client := &http.Client{Timeout: 5 * time.Second}
	reset, err := client.Post(python+"/__test/reset/before", "application/json", nil)
	if err != nil {
		t.Fatal(err)
	}
	_, _ = io.Copy(io.Discard, reset.Body)
	reset.Body.Close()
	if reset.StatusCode != 200 {
		t.Fatalf("reinicio: %d", reset.StatusCode)
	}

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	req, err := http.NewRequestWithContext(ctx, "POST", front.URL+"/api/v1/estimate", strings.NewReader(estimateRequest))
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
	if state.Posts != 1 || state.Committed != 0 || state.CacheWrites != 0 || state.Writing {
		t.Fatalf("estado final REST: %+v", state)
	}
}

func verifyConfirmedRow(t *testing.T, before, after []string, delivered []byte) {
	t.Helper()
	if len(before) != 1 || len(after) != 1 {
		t.Fatalf("se esperaba exactamente una fila: antes %d, después %d", len(before), len(after))
	}
	decode := func(raw string) map[string]any {
		t.Helper()
		d := json.NewDecoder(strings.NewReader(raw))
		d.UseNumber()
		var value map[string]any
		if err := d.Decode(&value); err != nil {
			t.Fatal(err)
		}
		return value
	}
	first, last := decode(before[0]), decode(after[0])
	if !reflect.DeepEqual(first, last) {
		t.Fatal("la fila confirmada cambió con la cancelación")
	}
	id, ok := first["id"].(json.Number)
	if !ok {
		t.Fatal("ID ausente o inválido")
	}
	n, err := id.Int64()
	if err != nil || n <= 0 {
		t.Fatalf("ID inválido: %s", id)
	}
	request := decode(estimateRequest)
	expectedOptions := map[string]any{"project_type": request["project_type"], "detail_level": request["detail_level"], "output_format": request["output_format"], "reference_projects": nil}
	expectedResult := decode(string(delivered))
	if !reflect.DeepEqual(first["options"], expectedOptions) ||
		!equalJSONValue(first["result"], expectedResult) ||
		first["description"] != request["description"] || first["prompt_version"] != "v3" ||
		first["cached"] != false || first["cache_source"] != "none" || first["model"] != "fake" || first["provider"] != "openai" {
		t.Fatalf("fila confirmada fuera de contrato: %+v", first)
	}
	metric, ok := first["metrics"].(map[string]any)
	_, hasConversation := first["conversation_id"]
	_, hasSnapshot := first["metadata_snapshot"]
	if !ok || metric["model"] != "fake" || metric["provider"] != "openai" || metric["usage"] == nil ||
		!hasConversation || first["conversation_id"] != nil || !hasSnapshot || first["metadata_snapshot"] != nil ||
		first["requested_at"] == nil || first["completed_at"] == nil {
		t.Fatalf("metadatos persistidos inválidos: %+v", first)
	}
}

func equalJSONValue(left, right any) bool {
	switch a := left.(type) {
	case json.Number:
		b, ok := right.(json.Number)
		if !ok {
			return false
		}
		x, xOK := new(big.Rat).SetString(a.String())
		y, yOK := new(big.Rat).SetString(b.String())
		return xOK && yOK && x.Cmp(y) == 0
	case map[string]any:
		b, ok := right.(map[string]any)
		if !ok || len(a) != len(b) {
			return false
		}
		for key, value := range a {
			other, exists := b[key]
			if !exists || !equalJSONValue(value, other) {
				return false
			}
		}
		return true
	case []any:
		b, ok := right.([]any)
		if !ok || len(a) != len(b) {
			return false
		}
		for i, value := range a {
			if !equalJSONValue(value, b[i]) {
				return false
			}
		}
		return true
	default:
		return reflect.DeepEqual(left, right)
	}
}
