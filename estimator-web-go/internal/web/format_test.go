package web

import (
	"encoding/json"
	"strings"
	"testing"
)

func TestFormatCostMatchesRails(t *testing.T) {
	cases := map[any]string{
		json.Number("20000"): "20.000,00 EUR", json.Number("16000"): "16.000,00 EUR", 20000.0: "20.000,00 EUR",
		0: "0,00 EUR", json.Number("1234567.891"): "1.234.567,89 EUR", json.Number("0.005"): "0,01 EUR",
		2.675: "2,68 EUR", json.Number("999.995"): "1.000,00 EUR", nil: " EUR",
	}
	for input, want := range cases {
		if got := formatCost(input); got != want {
			t.Errorf("formatCost(%v) = %q, se esperaba %q", input, got, want)
		}
	}
}

func TestFormatWeeksStripsInsignificantZeros(t *testing.T) {
	cases := map[any]string{json.Number("10"): "10 semanas", json.Number("2.5"): "2,5 semanas", 2.0: "2 semanas", json.Number("0.04"): "0 semanas", json.Number("1234.56"): "1234,6 semanas"}
	for input, want := range cases {
		if got := formatWeeks(input); got != want {
			t.Errorf("formatWeeks(%v) = %q, se esperaba %q", input, got, want)
		}
	}
}

func TestFormatUSD(t *testing.T) {
	cases := map[any]string{
		json.Number("0.000412"): "0,000412 USD", 0.14: "0,140000 USD", 0.0: "0,000000 USD", nil: "Sin tarifa", json.Number("12400"): "12400,000000 USD",
	}
	for input, want := range cases {
		if got := formatUSD(input); got != want {
			t.Errorf("formatUSD(%v) = %q, se esperaba %q", input, got, want)
		}
	}
}

func TestNumberHelpersWithoutDelimiter(t *testing.T) {
	if numPrec1(79.0) != "79,0" || numPrec1(120.5) != "120,5" || numPrec2(0.012) != "0,01" || numPrec3(0.64) != "0,640" || numPrec1Strip(json.Number("2")) != "2" {
		t.Errorf("%s %s %s %s %s", numPrec1(79.0), numPrec1(120.5), numPrec2(0.012), numPrec3(0.64), numPrec1Strip(json.Number("2")))
	}
	if numPrec1(nil) != "" || numPrec1("no numérico") != "no numérico" {
		t.Error("los valores ausentes son vacíos y los no numéricos se muestran tal cual")
	}
	if numberWithPrecision(-1234.5, 2, ".", ",", false) != "-1.234,50" {
		t.Errorf("negativos: %s", numberWithPrecision(-1234.5, 2, ".", ",", false))
	}
}

func TestDelimited(t *testing.T) {
	cases := map[any]string{12400: "12.400", json.Number("860"): "860", 0: "0", 80000: "80.000", 1234567: "1.234.567", nil: "0", "8450": "8.450"}
	for input, want := range cases {
		if got := delimited(input); got != want {
			t.Errorf("delimited(%v) = %q, se esperaba %q", input, got, want)
		}
	}
}

func TestFormatTime(t *testing.T) {
	cases := map[string]string{
		"2026-10-05T10:30:00Z": "05/10/2026 10:30 UTC", "2026-10-05T12:30:00+02:00": "05/10/2026 10:30 UTC",
		"2026-10-05T10:30:00.123456Z": "05/10/2026 10:30 UTC", "ayer": "ayer", "": "",
	}
	for input, want := range cases {
		if got := formatTime(input); got != want {
			t.Errorf("formatTime(%q) = %q, se esperaba %q", input, got, want)
		}
	}
}

func TestTruncateCountsCharactersAndReservesTheEllipsis(t *testing.T) {
	long := strings.Repeat("ñ", 100)
	if got := truncate(long, 90); got != strings.Repeat("ñ", 87)+"..." {
		t.Errorf("truncate: %q", got)
	}
	if truncate("corto", 90) != "corto" || truncate(strings.Repeat("a", 90), 90) != strings.Repeat("a", 90) {
		t.Error("los textos que caben no se tocan")
	}
	if len([]rune(truncate(strings.Repeat("palabra ", 10_000), 2000))) != 2000 {
		t.Error("el resultado ocupa exactamente `length` caracteres")
	}
}

func TestLabelsAndSources(t *testing.T) {
	if labelFor("web_saas") != "SaaS web" || labelFor("v3") != "v3" || labelFor(nil) != "" {
		t.Error("etiquetas")
	}
	if cacheSourceLabel("semantic") != "Caché semántica" || cacheSourceLabel("exact") != "Caché exacta" || cacheSourceLabel("none") != "Generada" || cacheSourceLabel("x") != "Generada" || cacheSourceLabel(nil) != "Generada" {
		t.Error("procedencia")
	}
	if outOfScopeReason("Out of scope: la reunión no define el alcance.") != "la reunión no define el alcance." {
		t.Error("motivo fuera de alcance")
	}
	options := optionsForLabels([]string{"summary", "medium"})
	if options[0].Label != "Resumen" || options[1].Value != "medium" {
		t.Errorf("opciones: %+v", options)
	}
}

func TestRoundedPctAndPlainInt(t *testing.T) {
	if roundedPct(100) != "100.0" || roundedPct(33.333) != "33.3" || roundedPct(0) != "0.0" || plainInt(40) != "40" || plainInt(79.6) != "80" {
		t.Error("redondeos")
	}
}
