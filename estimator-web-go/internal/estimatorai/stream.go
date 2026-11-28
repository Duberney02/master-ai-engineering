package estimatorai

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"mime"
	"net/url"
)

type TranscriptionInput struct {
	Transcription       string          `json:"transcription"`
	Preprocessing       json.RawMessage `json:"preprocessing,omitempty"`
	ExampleFormat       json.RawMessage `json:"example_format,omitempty"`
	NumExamples         json.RawMessage `json:"num_examples,omitempty"`
	UseExamples         json.RawMessage `json:"use_examples,omitempty"`
	Model               json.RawMessage `json:"model,omitempty"`
	MaxTokens           json.RawMessage `json:"max_tokens,omitempty"`
	Evaluate            json.RawMessage `json:"evaluate,omitempty"`
	ThinkingBudget      json.RawMessage `json:"thinking_budget,omitempty"`
	IncludeProjectCosts json.RawMessage `json:"include_project_costs,omitempty"`
	DeveloperRate       json.RawMessage `json:"developer_rate_eur,omitempty"`
	DesignerRate        json.RawMessage `json:"designer_rate_eur,omitempty"`
}

func (c *PublicClient) StreamEstimate(ctx context.Context, version string, input EstimateInput) (io.ReadCloser, error) {
	return c.structured.stream(ctx, "/api/v1/estimate/stream", url.Values{"prompt_version": {version}}, input)
}

func (c *PublicClient) StreamTranscription(ctx context.Context, input TranscriptionInput) (io.ReadCloser, error) {
	return c.transcription.stream(ctx, "/api/v1/transcription/estimate/stream", nil, input)
}

func (b baseClient) stream(ctx context.Context, path string, query url.Values, input any) (io.ReadCloser, error) {
	payload, err := json.Marshal(input)
	if err != nil {
		return nil, invalidResponse()
	}
	res, err := b.publicRequest(ctx, "POST", path, query, bytes.NewReader(payload), "application/json", "text/event-stream")
	if err != nil {
		return nil, err
	}
	if res.StatusCode != 200 {
		defer res.Body.Close()
		return nil, publicError(res)
	}
	kind, _, _ := mime.ParseMediaType(res.Header.Get("Content-Type"))
	if kind != "text/event-stream" {
		res.Body.Close()
		return nil, invalidResponse()
	}
	return res.Body, nil
}
