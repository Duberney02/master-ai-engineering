package web

import (
	"math"
	"math/big"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"

	"estimator-web/internal/jsondoc"
)

// Helpers de presentación: reproducen las salidas de los helpers de Rails (`number_with_precision`,
// `number_with_delimiter`, `truncate`…) para que las pantallas muestren exactamente lo mismo.

var labels = map[string]string{
	"mobile_app": "App móvil", "web_saas": "SaaS web", "internal_tool": "Herramienta interna", "data_pipeline": "Pipeline de datos",
	"summary": "Resumen", "medium": "Medio", "detailed": "Detallado",
	"phases_table": "Tabla de fases", "line_items": "Partidas", "narrative": "Narrativa",
}

var cacheSources = map[string]string{"none": "Generada", "exact": "Caché exacta", "semantic": "Caché semántica"}

const outOfScopePrefix = "Out of scope:"

// labelFor traduce un valor de la API a su etiqueta; los desconocidos se muestran tal cual.
func labelFor(value any) string {
	text := jsondoc.String(value)
	if label, ok := labels[text]; ok {
		return label
	}
	return text
}

// Option es una opción de un `<select>`.
type Option struct{ Label, Value string }

func optionsForLabels(values []string) []Option {
	options := make([]Option, len(values))
	for index, value := range values {
		options[index] = Option{Label: labelFor(value), Value: value}
	}
	return options
}

func cacheSourceLabel(source any) string {
	if label, ok := cacheSources[jsondoc.String(source)]; ok {
		return label
	}
	return "Generada"
}

// formatCost: «20.000,00 EUR».
func formatCost(value any) string { return numberWithPrecision(value, 2, ".", ",", false) + " EUR" }

// formatWeeks: «10 semanas», «2,5 semanas».
func formatWeeks(value any) string { return numberWithPrecision(value, 1, "", ",", true) + " semanas" }

// formatUSD: «0,000412 USD»; sin tarifa, «Sin tarifa».
func formatUSD(value any) string {
	if value == nil {
		return "Sin tarifa"
	}
	return numberWithPrecision(value, 6, "", ",", false) + " USD"
}

// formatTime: «05/10/2026 10:30 UTC»; un valor que no es ISO 8601 se muestra tal cual.
func formatTime(value any) string {
	text := jsondoc.String(value)
	parsed, err := time.Parse(time.RFC3339, text)
	if err != nil {
		return text
	}
	return parsed.UTC().Format("02/01/2006 15:04") + " UTC"
}

func outOfScopeReason(summary any) string {
	return strings.TrimSpace(strings.TrimPrefix(jsondoc.String(summary), outOfScopePrefix))
}

// truncate replica `String#truncate`: si supera `length` caracteres, corta y añade «...» dentro del mismo límite.
func truncate(value any, length int) string {
	text := jsondoc.String(value)
	if utf8.RuneCountInString(text) <= length {
		return text
	}
	return string([]rune(text)[:max(length-3, 0)]) + "..."
}

// delimited replica `number_with_delimiter(n, delimiter: ".")` para enteros.
func delimited(value any) string {
	number := int64(jsondoc.ToInt(value))
	text := strconv.FormatInt(number, 10)
	sign := ""
	if number < 0 {
		sign, text = "-", text[1:]
	}
	return sign + groupThousands(text, ".")
}

func groupThousands(digits, delimiter string) string {
	if delimiter == "" || len(digits) <= 3 {
		return digits
	}
	var out strings.Builder
	lead := len(digits) % 3
	if lead > 0 {
		out.WriteString(digits[:lead])
	}
	for index := lead; index < len(digits); index += 3 {
		if out.Len() > 0 {
			out.WriteString(delimiter)
		}
		out.WriteString(digits[index : index+3])
	}
	return out.String()
}

// numberWithPrecision replica `number_with_precision`: redondeo decimal «half up» sobre la representación más corta del
// número (como BigDecimal), separador decimal y de miles configurables y, opcionalmente, sin ceros finales. Un valor
// ausente es «»; uno que no es numérico se muestra tal cual.
func numberWithPrecision(value any, precision int, delimiter, separator string, stripZeros bool) string {
	if value == nil {
		return ""
	}
	text, numeric := decimalText(value)
	if !numeric {
		return jsondoc.String(value)
	}
	rational, ok := new(big.Rat).SetString(text)
	if !ok {
		return jsondoc.String(value)
	}

	negative := rational.Sign() < 0
	rational.Abs(rational)
	scale := new(big.Int).Exp(big.NewInt(10), big.NewInt(int64(precision)), nil)
	rational.Mul(rational, new(big.Rat).SetInt(scale))
	rational.Add(rational, big.NewRat(1, 2)) // half up
	rounded := new(big.Int).Quo(rational.Num(), rational.Denom())

	digits := rounded.String()
	for len(digits) <= precision {
		digits = "0" + digits
	}
	whole, fraction := digits[:len(digits)-precision], digits[len(digits)-precision:]
	if stripZeros {
		fraction = strings.TrimRight(fraction, "0")
	}
	result := groupThousands(whole, delimiter)
	if fraction != "" {
		result += separator + fraction
	}
	if negative && rounded.Sign() != 0 {
		result = "-" + result
	}
	return result
}

// decimalText devuelve la representación decimal de un valor numérico (JSON, Go o texto numérico).
func decimalText(value any) (string, bool) {
	switch typed := value.(type) {
	case float64:
		if math.IsNaN(typed) || math.IsInf(typed, 0) {
			return "", false
		}
		return strconv.FormatFloat(typed, 'f', -1, 64), true
	case float32:
		return strconv.FormatFloat(float64(typed), 'f', -1, 32), true
	case int:
		return strconv.Itoa(typed), true
	case int64:
		return strconv.FormatInt(typed, 10), true
	}
	if _, ok := jsondoc.ToFloat(value); ok {
		return strings.TrimSpace(jsondoc.String(value)), true
	}
	return "", false
}

func numPrec1(value any) string      { return numberWithPrecision(value, 1, "", ",", false) }
func numPrec1Strip(value any) string { return numberWithPrecision(value, 1, "", ",", true) }
func numPrec2(value any) string      { return numberWithPrecision(value, 2, "", ",", false) }
func numPrec3(value any) string      { return numberWithPrecision(value, 3, "", ",", false) }

// roundedPct formatea un porcentaje con un decimal, como `Float#round(1)` de Ruby («100.0», «33.3»).
func roundedPct(value float64) string {
	return strconv.FormatFloat(math.Round(value*10)/10, 'f', 1, 64)
}

// plainInt muestra un número sin decimales (los contadores de la API son enteros).
func plainInt(value float64) string { return strconv.FormatInt(int64(math.Round(value)), 10) }
