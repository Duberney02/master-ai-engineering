package config

import (
	"strings"
	"testing"
	"time"
)

func env(values map[string]string) func(string) string {
	return func(name string) string { return values[name] }
}

func TestDefaultsMatchRails(t *testing.T) {
	cfg, err := FromEnv(env(nil))
	if err != nil {
		t.Fatal(err)
	}
	if cfg.APIURL != "http://localhost:8000" || cfg.Port != "3000" {
		t.Errorf("valores por defecto inesperados: %+v", cfg)
	}
	if cfg.OpenTimeout != 5*time.Second || cfg.ReadTimeout != 300*time.Second ||
		cfg.CompareTimeout != 600*time.Second || cfg.BadgeTimeout != 2*time.Second {
		t.Errorf("tiempos de espera por defecto inesperados: %+v", cfg)
	}
	if !cfg.EphemeralSecret || len(cfg.SecretKeyBase) < 32 {
		t.Errorf("sin SECRET_KEY_BASE debe generarse un secreto efímero")
	}
}

func TestOverridesAndFractionalSeconds(t *testing.T) {
	cfg, err := FromEnv(env(map[string]string{
		"ESTIMATOR_API_URL":         "http://api:8000/",
		"ESTIMATOR_BADGE_TIMEOUT":   "0.5",
		"ESTIMATOR_COMPARE_TIMEOUT": "42",
		"SECRET_KEY_BASE":           "abc",
		"DATABASE_URL":              "postgres://x",
	}))
	if err != nil {
		t.Fatal(err)
	}
	if cfg.APIURL != "http://api:8000" {
		t.Errorf("la barra final debe recortarse: %q", cfg.APIURL)
	}
	if cfg.BadgeTimeout != 500*time.Millisecond || cfg.CompareTimeout != 42*time.Second {
		t.Errorf("tiempos: %+v", cfg)
	}
	if cfg.EphemeralSecret || cfg.SecretKeyBase != "abc" || cfg.DatabaseURL != "postgres://x" {
		t.Errorf("secreto o base de datos: %+v", cfg)
	}
}

func TestInvalidTimeoutIsRejected(t *testing.T) {
	_, err := FromEnv(env(map[string]string{"ESTIMATOR_READ_TIMEOUT": "mucho"}))
	if err == nil || !strings.Contains(err.Error(), "ESTIMATOR_READ_TIMEOUT") {
		t.Fatalf("se esperaba un error que nombre la variable: %v", err)
	}
}
