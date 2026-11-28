// Package config lee la configuración del servicio web desde variables de entorno.
//
// Los nombres y valores por defecto se conservan para que el Compose y los entornos existentes no cambien. Las
// variables que dejaron de tener consumidor (p. ej. `SECRET_KEY_BASE`, de la cookie del cliente HTML) se ignoran.
package config

import (
	"fmt"
	"math"
	"net/url"

	"strconv"
	"strings"
	"time"
)

// Config reúne los ajustes del servicio.
type Config struct {
	StreamTotal, StructuredStreamTotal                                                        time.Duration
	StreamIdle, StructuredStreamIdle                                                          time.Duration
	Port                                                                                      string
	PublicOrigin                                                                              string
	PublicRegularHeaders, PublicRegularTotal, PublicLongHeaders, PublicLongTotal, PublicProbe time.Duration
	APIURL                                                                                    string
	OpenTimeout                                                                               time.Duration
	ReadTimeout                                                                               time.Duration
	CompareTimeout                                                                            time.Duration
	BadgeTimeout                                                                              time.Duration
	DatabaseURL                                                                               string
}

// FromEnv construye la configuración con la función de lectura dada (os.Getenv en producción).
func FromEnv(getenv func(string) string) (Config, error) {
	value := func(name, fallback string) string {
		if found := strings.TrimSpace(getenv(name)); found != "" {
			return found
		}
		return fallback
	}
	seconds := func(name, fallback string) (time.Duration, error) {
		raw := value(name, fallback)
		parsed, err := strconv.ParseFloat(raw, 64)
		if err != nil || parsed <= 0 || math.IsNaN(parsed) || parsed >= float64(math.MaxInt64)/float64(time.Second) {
			return 0, fmt.Errorf("%s debe ser un número de segundos positivo (recibido %q)", name, raw)
		}
		return time.Duration(parsed * float64(time.Second)), nil
	}

	cfg := Config{
		Port:        value("PORT", "3000"),
		APIURL:      strings.TrimRight(value("ESTIMATOR_API_URL", "http://localhost:8000"), "/"),
		DatabaseURL: getenv("DATABASE_URL"),
	}
	var err error
	if cfg.OpenTimeout, err = seconds("ESTIMATOR_OPEN_TIMEOUT", "5"); err != nil {
		return Config{}, err
	}
	if cfg.ReadTimeout, err = seconds("ESTIMATOR_READ_TIMEOUT", "300"); err != nil {
		return Config{}, err
	}
	if cfg.CompareTimeout, err = seconds("ESTIMATOR_COMPARE_TIMEOUT", "600"); err != nil {
		return Config{}, err
	}
	if cfg.BadgeTimeout, err = seconds("ESTIMATOR_BADGE_TIMEOUT", "2"); err != nil {
		return Config{}, err
	}

	cfg.PublicOrigin = value("ESTIMATOR_PUBLIC_ORIGIN", "")
	if cfg.PublicOrigin != "" {
		u, parseErr := url.Parse(cfg.PublicOrigin)
		if parseErr != nil || (u.Scheme != "http" && u.Scheme != "https") || u.Hostname() == "" ||
			u.User != nil || u.Path != "" || u.ForceQuery || u.RawQuery != "" || u.Fragment != "" {
			return Config{}, fmt.Errorf("ESTIMATOR_PUBLIC_ORIGIN debe ser un origen HTTP válido")
		}
	}
	for _, item := range []struct {
		name, fallback string
		destination    *time.Duration
	}{
		{"ESTIMATOR_REGULAR_HEADERS_TIMEOUT", "30", &cfg.PublicRegularHeaders},
		{"ESTIMATOR_REGULAR_TOTAL_TIMEOUT", "30", &cfg.PublicRegularTotal},
		{"ESTIMATOR_LONG_HEADERS_TIMEOUT", "600", &cfg.PublicLongHeaders},
		{"ESTIMATOR_LONG_TOTAL_TIMEOUT", "600", &cfg.PublicLongTotal},
		{"ESTIMATOR_PROBE_TIMEOUT", "3", &cfg.PublicProbe},
		{"ESTIMATOR_TRANSCRIPTION_IDLE_TIMEOUT", "600", &cfg.StreamIdle},
		{"ESTIMATOR_TRANSCRIPTION_TOTAL_TIMEOUT", "600", &cfg.StreamTotal},
		{"ESTIMATOR_STRUCTURED_TOTAL_TIMEOUT", "600", &cfg.StructuredStreamTotal},
		{"ESTIMATOR_STRUCTURED_IDLE_TIMEOUT", "600", &cfg.StructuredStreamIdle},
	} {
		if *item.destination, err = seconds(item.name, item.fallback); err != nil {
			return Config{}, err
		}
	}

	return cfg, nil
}

type APITimeouts struct {
	Connection, RegularHeaders, RegularTotal, LongHeaders, LongTotal, Probe time.Duration
	StructuredTotal, TranscriptionTotal                                     time.Duration
}

func (c Config) PublicTimeouts() APITimeouts {
	defaultSeconds := func(value time.Duration, fallback time.Duration) time.Duration {
		if value > 0 {
			return value
		}
		return fallback * time.Second
	}
	return APITimeouts{
		Connection:         defaultSeconds(c.OpenTimeout, 5),
		RegularHeaders:     defaultSeconds(c.PublicRegularHeaders, 30),
		RegularTotal:       defaultSeconds(c.PublicRegularTotal, 30),
		LongHeaders:        defaultSeconds(c.PublicLongHeaders, 600),
		LongTotal:          defaultSeconds(c.PublicLongTotal, 600),
		Probe:              defaultSeconds(c.PublicProbe, 3),
		StructuredTotal:    defaultSeconds(c.StructuredStreamTotal, 600),
		TranscriptionTotal: defaultSeconds(c.StreamTotal, 600),
	}
}
