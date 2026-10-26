// Comando estimator-web: servicio web del estimador. Cliente HTTP de la API de IA (FastAPI); PostgreSQL solo para el
// historial del Chunking Lab.
//
//	estimator-web               arranca el servidor
//	estimator-web healthcheck   sonda para Docker: GET /up del propio servicio (la imagen no tiene curl ni shell)
package main

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"net"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"estimator-web/internal/config"
	"estimator-web/internal/rag"
	"estimator-web/internal/web"
)

func main() {
	logger := slog.New(slog.NewTextHandler(os.Stdout, nil))
	cfg, err := config.FromEnv(os.Getenv)
	if err != nil {
		logger.Error("configuración inválida", "error", err.Error())
		os.Exit(1)
	}

	if len(os.Args) > 1 && os.Args[1] == "healthcheck" {
		os.Exit(healthcheck(cfg.Port))
	}

	if err := run(cfg, logger); err != nil {
		logger.Error("el servicio terminó con error", "error", err.Error())
		os.Exit(1)
	}
}

func healthcheck(port string) int {
	client := http.Client{Timeout: 3 * time.Second}
	response, err := client.Get("http://" + net.JoinHostPort("127.0.0.1", port) + "/up")
	if err != nil {
		return 1
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return 1
	}
	return 0
}

func run(cfg config.Config, logger *slog.Logger) error {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	if cfg.EphemeralSecret {
		logger.Warn("SECRET_KEY_BASE no está definido: se usa un secreto efímero y las conversaciones se reinician al reiniciar el servicio")
	}

	store := openStore(ctx, cfg, logger)
	server, err := web.New(cfg, store, logger)
	if err != nil {
		return err
	}

	httpServer := &http.Server{
		Addr:              net.JoinHostPort("", cfg.Port),
		Handler:           server.Handler(),
		ReadHeaderTimeout: 10 * time.Second,
		// Sin WriteTimeout: una estimación o una comparación de pago pueden tardar minutos antes de responder.
		IdleTimeout: 120 * time.Second,
		BaseContext: func(net.Listener) context.Context { return context.WithoutCancel(ctx) },
	}

	failed := make(chan error, 1)
	go func() {
		logger.Info("escuchando", "addr", httpServer.Addr, "api", cfg.APIURL, "history", store != nil)
		if err := httpServer.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			failed <- err
		}
	}()

	select {
	case err := <-failed:
		return err
	case <-ctx.Done():
	}
	logger.Info("apagando")
	shutdown, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	if err := httpServer.Shutdown(shutdown); err != nil {
		return fmt.Errorf("apagado ordenado: %w", err)
	}
	return nil
}

// openStore abre el historial del Chunking Lab. Sin DATABASE_URL, o si la base no responde, el servicio arranca igual
// y el laboratorio muestra el aviso de historial no disponible.
func openStore(ctx context.Context, cfg config.Config, logger *slog.Logger) rag.Store {
	if cfg.DatabaseURL == "" {
		logger.Warn("DATABASE_URL no está definido: el Chunking Lab no podrá guardar sus ejecuciones")
		return nil
	}
	store, err := rag.NewPgStore(ctx, cfg.DatabaseURL)
	if err != nil {
		logger.Error("no se pudo abrir la base de datos del historial", "error_type", fmt.Sprintf("%T", err))
		return nil
	}
	// La base puede tardar en estar lista: se reintenta la creación de la tabla unos segundos.
	var migrateErr error
	for attempt := 0; attempt < 10; attempt++ {
		attemptCtx, cancel := context.WithTimeout(ctx, 5*time.Second)
		migrateErr = store.Migrate(attemptCtx)
		cancel()
		if migrateErr == nil {
			return store
		}
		select {
		case <-ctx.Done():
			return store
		case <-time.After(2 * time.Second):
		}
	}
	logger.Error("no se pudo preparar la tabla del historial; el laboratorio la reintentará al guardar", "error_type", fmt.Sprintf("%T", migrateErr))
	return store
}
