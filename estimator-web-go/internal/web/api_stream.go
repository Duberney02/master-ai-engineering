package web

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"net"
	"net/http"
	"net/url"
	"time"
	"unicode/utf8"

	"estimator-web/internal/estimatorai"
)

const eventLimit = 1 << 20

var errInvalidEvent = errors.New("evento SSE inválido")

type eventFrame struct {
	wire    []byte
	kind    string
	data    []byte
	hasData bool
}

func readEvent(reader *bufio.Reader) (eventFrame, error) {
	var frame eventFrame
	for {
		start := len(frame.wire)
		for {
			chunk, err := reader.ReadSlice('\n')
			if len(frame.wire)+len(chunk) > eventLimit {
				return frame, errInvalidEvent
			}
			frame.wire = append(frame.wire, chunk...)
			if errors.Is(err, bufio.ErrBufferFull) {
				continue
			}
			if err != nil {
				return frame, err
			}
			break
		}
		line := bytes.TrimSuffix(bytes.TrimSuffix(frame.wire[start:], []byte("\n")), []byte("\r"))
		if len(line) == 0 {
			frame.data = bytes.TrimSuffix(frame.data, []byte("\n"))
			return frame, nil
		}
		field, value, _ := bytes.Cut(line, []byte(":"))
		value = bytes.TrimPrefix(value, []byte(" "))
		switch string(field) {
		case "event":
			frame.kind = string(value)
		case "data":
			frame.hasData = true
			frame.data = append(frame.data, value...)
			frame.data = append(frame.data, '\n')
		}
	}
}

func (s *Server) apiEstimateStream(w http.ResponseWriter, r *http.Request) {
	input, version, ok := readEstimate(w, r)
	if !ok {
		return
	}
	s.relayStream(w, r, true, func(ctx context.Context) (io.ReadCloser, error) {
		return s.publicAI.StreamEstimate(ctx, version, input)
	})
}

func (s *Server) apiTranscriptionStream(w http.ResponseWriter, r *http.Request) {
	var input estimatorai.TranscriptionInput
	if !readJSON(w, r, &input) {
		return
	}
	if _, err := url.ParseQuery(r.URL.RawQuery); err != nil || !runeLength(input.Transcription, 20, 50000) {
		apiFailure(w, 422, estimatorai.ValidationMessage)
		return
	}
	s.relayStream(w, r, false, func(ctx context.Context) (io.ReadCloser, error) {
		return s.publicAI.StreamTranscription(ctx, input)
	})
}

func (s *Server) relayStream(w http.ResponseWriter, r *http.Request, structured bool, open func(context.Context) (io.ReadCloser, error)) {
	ctx, cancel := context.WithCancel(r.Context())
	defer cancel()
	body, err := open(ctx)
	if err != nil {
		apiReply(w, r, 200, nil, err)
		return
	}
	closeUpstream := func() {
		cancel()
		if body != nil {
			_ = body.Close()
			body = nil
		}
	}
	defer closeUpstream()
	controller := http.NewResponseController(w)
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("X-Accel-Buffering", "no")
	if err := controller.SetWriteDeadline(time.Now().Add(30 * time.Second)); err != nil && !errors.Is(err, http.ErrNotSupported) {
		apiFailure(w, http.StatusBadGateway, estimatorai.ServerMessage)
		return
	}
	w.WriteHeader(200)
	if controller.Flush() != nil {
		return
	}

	_ = controller.SetWriteDeadline(time.Time{})

	inactivity := s.cfg.StreamIdle
	if structured {
		inactivity = s.cfg.StructuredStreamIdle
	}
	if inactivity <= 0 {
		inactivity = 600 * time.Second
	}
	reader := bufio.NewReader(body)
	state := 0
	for {
		timer := time.AfterFunc(inactivity, cancel)
		frame, err := readEvent(reader)
		timedOut := !timer.Stop()
		if r.Context().Err() != nil {
			return
		}
		if err != nil || timedOut || !validFrame(frame, structured, &state) {
			status := 502
			var netErr net.Error
			if timedOut || errors.Is(err, context.DeadlineExceeded) || (errors.As(err, &netErr) && netErr.Timeout()) {
				status = 504
			}
			closeUpstream()
			writeStreamError(w, controller, status)
			return
		}
		if frame.kind == "error" {
			var failure struct {
				Status int `json:"status_code"`
			}
			_ = json.Unmarshal(frame.data, &failure)
			closeUpstream()
			writeStreamError(w, controller, failure.Status)
			return
		}
		_ = controller.SetWriteDeadline(time.Now().Add(30 * time.Second))
		if _, err = w.Write(frame.wire); err != nil {
			return
		}
		if controller.Flush() != nil {
			return
		}
		_ = controller.SetWriteDeadline(time.Time{})
		if frame.kind == "done" {
			return
		}
	}
}

func validFrame(frame eventFrame, structured bool, state *int) bool {
	if !utf8.Valid(frame.wire) {
		return false
	}
	if frame.kind == "" && !frame.hasData {
		return true
	}
	if !estimatorai.ValidStreamPayload(frame.kind, structured, frame.data) {
		return false
	}
	switch frame.kind {
	case "error":
		return true
	case "result":
		if *state != 0 {
			return false
		}
		*state = 1
		return true
	case "token":
		return *state == 0
	case "metadata":
		if (structured && *state != 1) || (!structured && *state != 0) {
			return false
		}
		*state = 2
		return true
	case "done":
		return *state == 2
	default:
		return false
	}
}

func writeStreamError(w http.ResponseWriter, controller *http.ResponseController, status int) {
	message := estimatorai.ServerMessage
	switch status {
	case 400, 404, 413, 415, 422, 429, 502, 503:
	case 504:
		message = estimatorai.ConnectionMessage
	default:
		status = 502
	}
	payload, _ := json.Marshal(struct {
		Status  int    `json:"status_code"`
		Message string `json:"message"`
	}{status, message})
	_ = controller.SetWriteDeadline(time.Now().Add(30 * time.Second))
	_, _ = w.Write(append(append([]byte("event: error\ndata: "), payload...), '\n', '\n'))
	_ = controller.Flush()
}
