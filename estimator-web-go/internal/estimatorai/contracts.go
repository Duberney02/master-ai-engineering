package estimatorai

import (
	"bytes"
	"encoding/json"
	"math"
	"strconv"
	"time"
	"unicode/utf8"
)

type rule func(json.RawMessage) bool
type fields map[string]rule

func object(required, optional fields) rule {
	return func(raw json.RawMessage) bool {
		var values map[string]json.RawMessage
		if json.Unmarshal(raw, &values) != nil || values == nil {
			return false
		}
		for key, check := range required {
			if !check(values[key]) {
				return false
			}
		}
		for key, check := range optional {
			if value, exists := values[key]; exists && !check(value) {
				return false
			}
		}
		return true
	}
}

func nullable(check rule) rule {
	return func(raw json.RawMessage) bool { return bytes.Equal(raw, []byte("null")) || check(raw) }
}

func list(check rule, min, max int) rule {
	return func(raw json.RawMessage) bool {
		var values []json.RawMessage
		if json.Unmarshal(raw, &values) != nil || values == nil || len(values) < min || len(values) > max {
			return false
		}
		for _, value := range values {
			if !check(value) {
				return false
			}
		}
		return true
	}
}

func text(min, max int) rule {
	return func(raw json.RawMessage) bool {
		var value *string
		if json.Unmarshal(raw, &value) != nil || value == nil {
			return false
		}
		n := utf8.RuneCountInString(*value)
		return n >= min && n <= max
	}
}

func choices(allowed ...string) rule {
	return func(raw json.RawMessage) bool {
		var value *string
		if json.Unmarshal(raw, &value) != nil || value == nil {
			return false
		}
		for _, option := range allowed {
			if *value == option {
				return true
			}
		}
		return false
	}
}

func integer(min, max int64) rule {
	return func(raw json.RawMessage) bool {
		n, err := strconv.ParseInt(string(raw), 10, 64)
		return err == nil && n >= min && n <= max
	}
}

func number(min, max float64, exclusiveMin bool) rule {
	return func(raw json.RawMessage) bool {
		n, err := strconv.ParseFloat(string(raw), 64)
		return err == nil && !math.IsNaN(n) && !math.IsInf(n, 0) &&
			n >= min && n <= max && (!exclusiveMin || n > min)
	}
}

func boolean(raw json.RawMessage) bool {
	return bytes.Equal(raw, []byte("true")) || bytes.Equal(raw, []byte("false"))
}

func timestamp(raw json.RawMessage) bool {
	var value string
	if json.Unmarshal(raw, &value) != nil {
		return false
	}
	for _, layout := range []string{time.RFC3339Nano, "2006-01-02T15:04:05"} {
		if _, err := time.Parse(layout, value); err == nil {
			return true
		}
	}
	return false
}

var (
	anyText        = text(0, math.MaxInt)
	anyInt         = integer(math.MinInt64, math.MaxInt64)
	nonnegativeInt = integer(0, math.MaxInt64)
	anyNumber      = number(-math.MaxFloat64, math.MaxFloat64, false)
	anyObject      = object(nil, nil)
	cacheSource    = choices("none", "exact", "semantic")
	projectType    = choices("mobile_app", "web_saas", "internal_tool", "data_pipeline")
	detailLevel    = choices("summary", "medium", "detailed")
	outputFormat   = choices("phases_table", "line_items", "narrative")

	phase = object(fields{
		"name": text(1, 120), "duration_weeks": number(0, 520, true), "cost_eur": number(0, 100000000, false),
	}, fields{"description": text(0, 1000)})

	estimateResult = object(fields{
		"summary": text(1, 2000), "confidence_pct": integer(0, 100), "phases": list(phase, 1, 30),
		"total_duration_weeks": number(0, 2600, true), "total_cost_eur": number(0, 100000000, false),
		"out_of_scope": boolean,
	}, nil)

	streamUsage   = object(fields{"input_tokens": nonnegativeInt, "output_tokens": nonnegativeInt, "total_tokens": nonnegativeInt}, nil)
	metricsFields = fields{
		"model": anyText, "provider": anyText, "finish_reason": anyText, "usage": streamUsage,
		"latency_ms": nonnegativeInt, "cache_hit": boolean,
		"estimated_cost_usd": nullable(anyNumber), "request_cost_usd": nullable(anyNumber),
	}
	metrics = object(metricsFields, nil)

	estimateRequired = fields{"result": estimateResult, "prompt_version": anyText}
	estimateOptional = fields{
		"cached": boolean, "cache_source": cacheSource, "estimation_id": nullable(anyInt), "metrics": nullable(metrics),
	}
	estimateResponse = object(estimateRequired, estimateOptional)
	projectMetadata  = object(nil, fields{
		"project_name": nullable(text(0, 120)), "assumed_team_size": nullable(integer(1, 1000)),
		"mentioned_technologies": list(text(0, 60), 0, 30), "agreed_scope": nullable(text(0, 1000)),
	})
	historyResponse = list(object(fields{
		"id": anyInt, "requested_at": timestamp, "project_type": projectType, "detail_level": detailLevel, "output_format": outputFormat,
		"prompt_version": anyText, "cache_source": cacheSource, "confidence_pct": anyInt, "total_cost_eur": anyNumber,
		"total_duration_weeks": anyNumber, "out_of_scope": boolean, "description_excerpt": anyText,
	}, nil), 0, math.MaxInt)
	reference = object(fields{
		"name": text(1, 120), "description": text(1, 500), "actual_hours": number(0, 100000, true),
	}, nil)
	detailResponse = object(fields{
		"id": anyInt, "requested_at": timestamp, "completed_at": timestamp, "description": anyText,
		"options": object(fields{"project_type": projectType, "detail_level": detailLevel, "output_format": outputFormat},
			fields{"reference_projects": nullable(list(reference, 0, math.MaxInt))}),
		"result": estimateResult, "prompt_version": anyText, "cached": boolean, "cache_source": cacheSource, "model": anyText, "provider": anyText,
	}, fields{"metrics": nullable(metrics), "conversation_id": nullable(anyText), "metadata_snapshot": nullable(anyObject)})
	previewResponse = object(fields{
		"prompt_version": anyText, "system_prompt": anyText,
		"examples": list(object(fields{"title": anyText, "description": anyText}, nil), 0, math.MaxInt),
	}, nil)
	healthResponse = object(fields{"status": choices("healthy"), "environment": anyText, "provider": anyText, "model": anyText}, nil)

	phaseUsage = object(fields{
		"phase": choices("preprocessing", "estimation"), "model": anyText, "finish_reason": anyText,
		"input_tokens": anyInt, "output_tokens": anyInt, "total_tokens": anyInt, "latency_ms": anyInt,
	}, fields{
		"provider": anyText, "cache_hit": boolean, "estimated_cost_usd": nullable(anyNumber),
		"request_cost_usd": nullable(anyNumber), "usage_available": boolean,
	})
	transcriptionUsage = object(fields{"input_tokens": anyInt, "output_tokens": anyInt, "total_tokens": anyInt},
		fields{"phases": list(phaseUsage, 0, math.MaxInt)})
	evaluation = object(fields{
		"sections": func(raw json.RawMessage) bool {
			var values map[string]json.RawMessage
			if json.Unmarshal(raw, &values) != nil || values == nil {
				return false
			}
			for _, value := range values {
				if !boolean(value) {
					return false
				}
			}
			return true
		},
		"sections_in_order": boolean, "has_breakdown_table": boolean, "table_rows": anyInt,
		"declared_total_hours": nullable(anyNumber), "sum_row_hours_min": nullable(anyNumber), "sum_row_hours_max": nullable(anyNumber),
		"hours_match": nullable(boolean), "range_min": nullable(anyNumber), "range_max": nullable(anyNumber),
		"range_consistent": nullable(boolean), "has_team": boolean, "has_duration": boolean, "finish_reason_ok": boolean,
		"truncated": boolean, "score": number(0, 1, false), "issues": list(anyText, 0, math.MaxInt),
	}, fields{"project_cost_match": nullable(boolean), "declared_project_cost_eur": nullable(anyNumber)})
	transcriptionMetadata = object(fields{
		"model": anyText, "provider": anyText, "finish_reason": anyText, "usage": transcriptionUsage,
		"estimated_cost_usd": nullable(anyNumber), "latency_ms": anyInt, "generated_at": timestamp,
	}, fields{
		"request_cost_usd": nullable(anyNumber), "cache_hit": boolean, "preprocessing": choices("none", "inline_cleaning", "two_phase"),
		"extracted_requirements": nullable(anyText), "evaluation": nullable(evaluation),
	})
	tokenEvent = object(fields{"text": anyText}, nil)
	doneEvent  = object(fields{"status": choices("complete")}, nil)
	errorEvent = object(fields{"status_code": integer(400, 599), "message": anyText}, nil)
)

func validEstimate(raw []byte) bool { return estimateResponse(raw) }

func validTurnResponse(raw []byte, id string) bool {
	return estimateResponse(raw) && object(fields{
		"session_id": choices(id), "project_metadata": projectMetadata,
		"turn_count": integer(1, math.MaxInt64), "max_turns": integer(1, math.MaxInt64),
	}, fields{
		"audience": nullable(choices("executive", "pm", "developer", "default")), "audience_rule": nullable(anyText),
	})(raw)
}

// ValidStreamPayload valida cada dato SSE sin reserializarlo.
func ValidStreamPayload(kind string, structured bool, raw []byte) bool {
	switch kind {
	case "result":
		return structured && estimateResult(raw)
	case "metadata":
		if structured {
			return metrics(raw) && object(fields{"prompt_version": anyText},
				fields{"cache_source": cacheSource, "estimation_id": nullable(anyInt)})(raw)
		}
		return transcriptionMetadata(raw)
	case "token":
		return !structured && tokenEvent(raw)
	case "done":
		return doneEvent(raw)
	case "error":
		return errorEvent(raw)
	default:
		return false
	}
}
