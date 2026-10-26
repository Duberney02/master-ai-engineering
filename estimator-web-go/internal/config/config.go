// Package config lee la configuración del servicio web desde variables de entorno.
//
// Los nombres y valores por defecto son los del cliente Rails (`config/application.rb`), de modo que el Compose y
// los entornos existentes no cambian.
package config

import (
	"crypto/rand"
	"encoding/hex"
	"fmt"
	"strconv"
	"strings"
	"time"
)

// Config reúne los ajustes del servicio.
type Config struct {
	Port           string
	APIURL         string
	OpenTimeout    time.Duration
	ReadTimeout    time.Duration
	CompareTimeout time.Duration
	BadgeTimeout   time.Duration
	DatabaseURL    string
	SecretKeyBase  string
	// EphemeralSecret indica que SECRET_KEY_BASE no estaba definido y se generó uno aleatorio para este proceso.
	EphemeralSecret bool
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
		if err != nil || parsed <= 0 {
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

	cfg.SecretKeyBase = strings.TrimSpace(getenv("SECRET_KEY_BASE"))
	if cfg.SecretKeyBase == "" {
		random := make([]byte, 32)
		if _, err := rand.Read(random); err != nil {
			return Config{}, fmt.Errorf("no se pudo generar un secreto de sesión: %w", err)
		}
		cfg.SecretKeyBase = hex.EncodeToString(random)
		cfg.EphemeralSecret = true
	}
	return cfg, nil
}
