package web

import (
	"bufio"
	"context"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
	"time"

	"estimator-web/internal/config"
)

const transcriptionMetadataFixture = `{"model":"fake","provider":"fake","finish_reason":"stop","usage":{"input_tokens":1,"output_tokens":2,"total_tokens":3,"phases":[{"phase":"estimation","model":"fake","finish_reason":"stop","input_tokens":1,"output_tokens":2,"total_tokens":3,"latency_ms":1}]},"estimated_cost_usd":null,"latency_ms":1,"generated_at":"2026-01-01T00:00:00Z","evaluation":null,"additive":null}`
const structuredMetadataFixture = `{"model":"fake","provider":"fake","finish_reason":"stop","usage":{"input_tokens":1,"output_tokens":2,"total_tokens":3},"latency_ms":0,"cache_hit":false,"estimated_cost_usd":null,"request_cost_usd":null,"prompt_version":"v3","estimation_id":9007199254740993}`

const transcriptionRequest = `{"transcription":"Una transcripción suficientemente larga."}`

func TestSSEFlushesFragmentedMultilineEventBeforeUpstreamFinishes(t *testing.T) {
	release := make(chan struct{})
	handler := testAPI(t, func(w http.ResponseWriter, r *http.Request) {
		_, _ = io.Copy(io.Discard, r.Body)
		w.Header().Set("Content-Type", "text/event-stream")
		flusher := w.(http.Flusher)
		fmt.Fprint(w, ": comentario\r\nevent: token\r\ndata: {\r\n")
		flusher.Flush()
		fmt.Fprint(w, "data: \"text\":\"hola\"}\r\n\r\n")
		flusher.Flush()
		select {
		case <-release:
		case <-r.Context().Done():
			return
		}
		fmt.Fprintf(w, "event: metadata\ndata: %s\n\nevent: done\ndata: {\"status\":\"complete\"}\n\n", transcriptionMetadataFixture)
	}, nil)
	downstream := httptest.NewServer(handler)
	defer downstream.Close()
	req, err := http.NewRequest("POST", downstream.URL+"/api/v1/transcription/estimate/stream", strings.NewReader(transcriptionRequest))
	if err != nil {
		t.Fatal(err)
	}
	req.Header.Set("Content-Type", "application/json")
	client := http.Client{Timeout: 3 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 || resp.Header.Get("X-Accel-Buffering") != "no" {
		t.Fatalf("cabeceras: %d %v", resp.StatusCode, resp.Header)
	}
	reader := bufio.NewReader(resp.Body)
	frame, err := readEvent(reader)
	if err != nil || string(frame.wire) != ": comentario\r\nevent: token\r\ndata: {\r\ndata: \"text\":\"hola\"}\r\n\r\n" {
		t.Fatalf("evento: %q %v", frame.wire, err)
	}
	close(release)
	tail, err := io.ReadAll(reader)
	if err != nil || !strings.Contains(string(tail), "event: done") {
		t.Fatalf("cierre: %q %v", tail, err)
	}
}

func TestSSEFailureModesNeverInventDone(t *testing.T) {
	for _, test := range []struct {
		name, wire string
		status     int
		wait       bool
	}{
		{"validación", "", 422, false},
		{"EOF", "event: token\ndata: {\"text\":\"hola\"}\n\n", 200, false},
		{"orden", "event: done\ndata: {\"status\":\"complete\"}\n\n", 200, false},
		{"error", "event: error\ndata: {\"status_code\":502,\"message\":\"secreto\"}\n\n", 200, false},
		{"inactividad", "", 200, true},
	} {
		t.Run(test.name, func(t *testing.T) {
			handler := testAPI(t, func(w http.ResponseWriter, r *http.Request) {
				_, _ = io.Copy(io.Discard, r.Body)
				if test.status != 200 {
					w.Header().Set("Content-Type", "application/json")
					w.WriteHeader(test.status)
					io.WriteString(w, `{"detail":"secreto"}`)
					return
				}
				w.Header().Set("Content-Type", "text/event-stream")
				w.WriteHeader(200)
				io.WriteString(w, test.wire)
				w.(http.Flusher).Flush()
				if test.wait {
					waitRequestClose(t, r)
				}
			}, func(c *config.Config) { c.StreamIdle = 100 * time.Millisecond })
			w := callPublicAPI(handler, "POST", "/api/v1/transcription/estimate/stream", transcriptionRequest, "application/json")
			if w.Code != test.status || strings.Contains(w.Body.String(), "event: done") || strings.Contains(w.Body.String(), "secreto") {
				t.Fatalf("%d %s", w.Code, w.Body.String())
			}
			if test.status == 200 && !strings.Contains(w.Body.String(), "event: error") {
				t.Fatal("sin evento de error")
			}
			if test.wait && !strings.Contains(w.Body.String(), `"status_code":504`) {
				t.Fatal("no se señaló la expiración")
			}
		})
	}
}

func TestStructuredSSECancellationClosesHTTPUpstream(t *testing.T) {
	for _, after := range []bool{false, true} {
		t.Run(fmt.Sprintf("tras resultado=%v", after), func(t *testing.T) {
			closed := make(chan struct{})
			upstream := testAPI(t, func(w http.ResponseWriter, r *http.Request) {
				_, _ = io.Copy(io.Discard, r.Body)
				defer close(closed)
				w.Header().Set("Content-Type", "text/event-stream")
				if after {
					fmt.Fprintf(w, "event: result\ndata: %s\n\n", estimateResult)
				}
				w.(http.Flusher).Flush()
				waitRequestClose(t, r)
			}, nil)
			server := httptest.NewServer(upstream)
			defer server.Close()
			ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
			defer cancel()
			req, _ := http.NewRequestWithContext(ctx, "POST", server.URL+"/api/v1/estimate/stream", strings.NewReader(estimateRequest))
			req.Header.Set("Content-Type", "application/json")
			resp, err := server.Client().Do(req)
			if err != nil {
				t.Fatal(err)
			}
			defer resp.Body.Close()
			if after {
				event, err := readEvent(bufio.NewReader(resp.Body))
				if err != nil || event.kind != "result" {
					t.Fatalf("resultado: %v %v", event, err)
				}
			}
			cancel()
			select {
			case <-closed:
			case <-time.After(2 * time.Second):
				t.Fatal("no cerró el upstream")
			}
		})
	}
}

func TestSSEEventLimitAndTotalBudget(t *testing.T) {
	t.Run("evento demasiado grande", func(t *testing.T) {
		handler := testAPI(t, func(w http.ResponseWriter, r *http.Request) {
			_, _ = io.Copy(io.Discard, r.Body)
			w.Header().Set("Content-Type", "text/event-stream")
			fmt.Fprint(w, "event: token\ndata: {\"text\":\""+strings.Repeat("a", eventLimit)+"\"}\n\n")
		}, nil)
		response := callPublicAPI(handler, "POST", "/api/v1/transcription/estimate/stream", transcriptionRequest, "application/json")
		if response.Code != 200 || !strings.Contains(response.Body.String(), `"status_code":502`) || strings.Contains(response.Body.String(), "event: token") {
			t.Fatalf("evento desbordado: estado %d, tamaño %d", response.Code, response.Body.Len())
		}
	})
	t.Run("plazo total", func(t *testing.T) {
		handler := testAPI(t, func(w http.ResponseWriter, r *http.Request) {
			_, _ = io.Copy(io.Discard, r.Body)
			w.Header().Set("Content-Type", "text/event-stream")
			fmt.Fprint(w, ": actividad\n\n")
			w.(http.Flusher).Flush()
			waitRequestClose(t, r)
		}, func(c *config.Config) { c.StreamTotal = 250 * time.Millisecond; c.StreamIdle = 3 * time.Second })
		response := callPublicAPI(handler, "POST", "/api/v1/transcription/estimate/stream", transcriptionRequest, "application/json")
		if response.Code != 200 || !strings.Contains(response.Body.String(), `"status_code":504`) {
			t.Fatalf("plazo total: %d %s", response.Code, response.Body.String())
		}
	})
}

func waitRequestClose(t *testing.T, r *http.Request) {
	t.Helper()
	select {
	case <-r.Context().Done():
	case <-time.After(3 * time.Second):
		t.Error("Python simulado no observó el cierre de la petición")
	}
}

func TestSSEInvalidPayloadStopsBeforeDone(t *testing.T) {
	for _, tc := range []struct {
		name, kind, data string
		structured       bool
	}{
		{"resumen nulo", "result", strings.Replace(estimateResult, `"Resultado"`, "null", 1), true},
		{"fase incompleta", "result", `{"summary":"fake","confidence_pct":20,"phases":[{}],"total_duration_weeks":1,"total_cost_eur":0,"out_of_scope":true}`, true},
		{"uso nulo", "metadata", strings.Replace(structuredMetadataFixture, `{"input_tokens":1,"output_tokens":2,"total_tokens":3}`, "null", 1), true},
		{"uso incompleto", "metadata", strings.Replace(transcriptionMetadataFixture, `"input_tokens":1,`, "", 1), false},
		{"token nulo", "token", `{"text":null}`, false},
		{"error sin mensaje", "error", `{"status_code":502}`, false},
		{"dato obligatorio nulo", "metadata", strings.Replace(transcriptionMetadataFixture, `"finish_reason":"stop"`, `"finish_reason":null`, 1), false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			closed := make(chan struct{})
			handler := testAPI(t, func(w http.ResponseWriter, r *http.Request) {
				defer close(closed)
				_, _ = io.Copy(io.Discard, r.Body)
				w.Header().Set("Content-Type", "text/event-stream")
				if tc.structured && tc.kind == "metadata" {
					fmt.Fprintf(w, "event: result\ndata: %s\n\n", estimateResult)
				}
				fmt.Fprintf(w, "event: %s\ndata: %s\n\nevent: done\ndata: {\"status\":\"complete\"}\n\n", tc.kind, tc.data)
				w.(http.Flusher).Flush()
				waitRequestClose(t, r)
			}, nil)
			path, payload := "/api/v1/transcription/estimate/stream", transcriptionRequest
			if tc.structured {
				path, payload = "/api/v1/estimate/stream", estimateRequest
			}
			w := callPublicAPI(handler, "POST", path, payload, "application/json")
			got := w.Body.String()
			if w.Code != 200 || strings.Count(got, "event: error\n") != 1 ||
				!strings.Contains(got, `"status_code":502`) || strings.Contains(got, "event: done") || strings.Contains(got, tc.data) {
				t.Fatalf("cierre incorrecto: %d %s", w.Code, got)
			}
			select {
			case <-closed:
			case <-time.After(4 * time.Second):
				t.Fatal("no se cerró el upstream")
			}
		})
	}
}

func TestSSEStructuredKeepsValidAdditivePayload(t *testing.T) {
	handler := testAPI(t, func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/event-stream")
		fmt.Fprintf(w, "event: result\ndata: %s\n\nevent: metadata\ndata: %s\n\nevent: done\ndata: {\"status\":\"complete\",\"extra\":null}\n\n", estimateResult, structuredMetadataFixture)
	}, nil)
	w := callPublicAPI(handler, "POST", "/api/v1/estimate/stream", estimateRequest, "application/json")
	if w.Code != 200 || !strings.Contains(w.Body.String(), structuredMetadataFixture) || !strings.Contains(w.Body.String(), `"extra":null`) {
		t.Fatalf("respuesta alterada: %d %s", w.Code, w.Body.String())
	}
}

type blockedInitialWriter struct {
	*httptest.ResponseRecorder
	deadline       time.Time
	headerDeadline time.Time
	flushStarted   chan time.Time
	expired        chan struct{}
}

func (w *blockedInitialWriter) SetWriteDeadline(deadline time.Time) error {
	w.deadline = deadline
	return nil
}

func (w *blockedInitialWriter) WriteHeader(status int) {
	w.headerDeadline = w.deadline
	w.ResponseRecorder.WriteHeader(status)
}

func (w *blockedInitialWriter) FlushError() error {
	w.flushStarted <- w.deadline
	<-w.expired
	return os.ErrDeadlineExceeded
}

func TestSSEInitialFlushDeadlineClosesUpstream(t *testing.T) {
	closed := make(chan struct{})
	handler := testAPI(t, func(w http.ResponseWriter, r *http.Request) {
		defer close(closed)
		_, _ = io.Copy(io.Discard, r.Body)
		w.Header().Set("Content-Type", "text/event-stream")
		w.(http.Flusher).Flush()
		waitRequestClose(t, r)
	}, nil)
	writer := &blockedInitialWriter{ResponseRecorder: httptest.NewRecorder(), flushStarted: make(chan time.Time, 1), expired: make(chan struct{})}
	defer close(writer.expired)
	req := httptest.NewRequest("POST", "/api/v1/transcription/estimate/stream", strings.NewReader(transcriptionRequest))
	req.Header.Set("Content-Type", "application/json")
	done := make(chan struct{})
	start := time.Now()
	go func() { defer close(done); handler.ServeHTTP(writer, req) }()
	select {
	case deadline := <-writer.flushStarted:
		if deadline.Before(start.Add(29*time.Second)) || deadline.After(time.Now().Add(30*time.Second)) || !writer.headerDeadline.Equal(deadline) {
			t.Errorf("plazo inicial inválido: %v", deadline)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("no empezó el flush inicial")
	}
	writer.expired <- struct{}{}
	select {
	case <-done:
	case <-time.After(4 * time.Second):
		t.Fatal("no terminó el handler tras el fallo del flush")
	}
	select {
	case <-closed:
	case <-time.After(4 * time.Second):
		t.Fatal("no se cerró el upstream tras el fallo del flush")
	}
	if writer.Body.Len() != 0 {
		t.Fatal("se intentó escribir después del fallo de flush")
	}
}

func TestSSEUnexpectedUpstreamMediaTypeBeforeHeaders(t *testing.T) {
	handler := testAPI(t, func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		io.WriteString(w, `{"detail":"dato reservado del upstream"}`)
	}, nil)
	w := callPublicAPI(handler, "POST", "/api/v1/estimate/stream", estimateRequest, "application/json")
	if w.Code != 502 || w.Header().Get("Content-Type") != "application/json" ||
		strings.Contains(w.Body.String(), "dato reservado") || strings.Contains(w.Body.String(), "event:") {
		t.Fatalf("se abrió un stream inválido: %d %s", w.Code, w.Body.String())
	}
}
