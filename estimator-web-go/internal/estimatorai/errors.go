// Package estimatorai es la capa HTTP del cliente: la ÚNICA que habla con el servicio de IA (FastAPI).
//
// Cada cliente de contexto (estimaciones, sesiones, embeddings, configuración) comparte la conexión, el mapeo
// respuesta → error tipado y los mensajes del cliente base. No tiene lógica de negocio ni opinión sobre el significado
// de los payloads. Traduce cualquier fallo a un *Error con un mensaje en español apto para el usuario: nunca un cuerpo
// crudo, una traza, una clave ni la URL interna.
package estimatorai

import "errors"

// Kind es la clase de un error de la capa HTTP.
//
//	ConnectionFailed            el servicio no responde
//	└── RequestTimeout          …o tardó más del tiempo de espera
//	InvalidRequest              400/413/415/422: la petición no es válida
//	GuardrailViolation          400 de los guardrails de entrada (mensaje redactado por la API)
//	NotFound                    404
//	└── SessionExpired          la API perdió la sesión de conversación
//	ServiceUnavailable          503
//	ServerError                 otros 5xx
//	InvalidResponse             respuesta que no cumple el contrato
type Kind int

const (
	ConnectionFailed Kind = iota + 1
	RequestTimeout
	InvalidRequest
	GuardrailViolation
	NotFound
	SessionExpired
	ServiceUnavailable
	ServerError
	InvalidResponse
)

// Mensajes saneados (los mismos que el cliente Rails).
const (
	ConnectionMessage         = "No se pudo conectar con la API del estimador. Inténtalo de nuevo en unos instantes."
	InvalidResponseMessage    = "La API del estimador devolvió una respuesta inválida."
	ServerMessage             = "La API del estimador no pudo completar la solicitud. Inténtalo de nuevo."
	ValidationMessage         = "La solicitud no es válida. Revisa los campos del formulario."
	NotFoundMessage           = "No se encontró la estimación solicitada."
	HistoryUnavailableMessage = "El historial no está disponible en este momento."
	RejectedMessage           = "La API rechazó la solicitud."
	SessionExpiredMessage     = "La conversación anterior expiró en el servidor; se inició una nueva. Vuelve a enviar tu mensaje."
	// MessageLimit acota los mensajes redactados por la API (guardrails y `detail`).
	MessageLimit = 300
)

// Error es el error tipado de la capa HTTP. Su mensaje es siempre apto para mostrar al usuario.
type Error struct {
	Kind    Kind
	Message string
	// Status es el estado HTTP de la API (0 si no hubo respuesta).
	Status int
}

func (e *Error) Error() string { return e.Message }

// IsA indica si el error es de la clase dada o de una subclase suya.
func (e *Error) IsA(kind Kind) bool {
	if e.Kind == kind {
		return true
	}
	switch kind {
	case ConnectionFailed:
		return e.Kind == RequestTimeout
	case NotFound:
		return e.Kind == SessionExpired
	}
	return false
}

func newError(kind Kind, message string, status int) *Error {
	return &Error{Kind: kind, Message: message, Status: status}
}

// As extrae el *Error de la cadena de errores.
func As(err error) (*Error, bool) {
	var typed *Error
	if errors.As(err, &typed) {
		return typed, true
	}
	return nil, false
}

// IsKind indica si err es un *Error de la clase dada (o de una subclase).
func IsKind(err error, kind Kind) bool {
	typed, ok := As(err)
	return ok && typed.IsA(kind)
}
