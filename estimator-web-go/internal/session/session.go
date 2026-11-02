// Package session guarda el estado del navegador en una cookie firmada: el `session_id` de la conversación con la API
// y los metadatos compactados del proyecto (la API guarda las sesiones solo en memoria, se pierden al reiniciarla), los
// avisos `flash` que sobreviven a una redirección y el token CSRF.
//
// La cookie va firmada con HMAC-SHA256 (SECRET_KEY_BASE) pero no cifrada: solo contiene datos que el usuario ya ve.
// Una cookie manipulada o firmada con otro secreto se trata como sesión vacía. Los navegadores admiten ~4 KB por
// cookie, por eso los metadatos se compactan antes de guardarlos.
package session

import (
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/base64"
	"encoding/json"
	"net/http"
	"strings"
	"unicode/utf8"

	"estimator-web/internal/jsondoc"
)

// CookieName es el nombre de la cookie de sesión.
const CookieName = "_estimator_web_session"

// Límites de los metadatos guardados (caracteres).
const (
	MaxNameLength       = 80
	MaxTechnologies     = 10
	MaxTechnologyLength = 40
	MaxScopeLength      = 300
)

// Metadata son los metadatos compactados del proyecto que devuelve la API.
type Metadata struct {
	ProjectName           string   `json:"n,omitempty"`
	AssumedTeamSize       string   `json:"s,omitempty"`
	MentionedTechnologies []string `json:"t,omitempty"`
	AgreedScope           string   `json:"a,omitempty"`
}

// Present indica si hay algún dato que mostrar.
func (m Metadata) Present() bool {
	return strings.TrimSpace(m.ProjectName) != "" || strings.TrimSpace(m.AssumedTeamSize) != "" ||
		len(m.MentionedTechnologies) > 0 || strings.TrimSpace(m.AgreedScope) != ""
}

// Flash es un aviso de una sola vista. Type es «notice» o «alert».
type Flash struct {
	Type    string `json:"y"`
	Message string `json:"m"`
}

type payload struct {
	ConversationID string    `json:"c,omitempty"`
	Metadata       *Metadata `json:"m,omitempty"`
	Flash          []Flash   `json:"f,omitempty"`
	CSRF           string    `json:"x,omitempty"`
}

// Manager firma y verifica las cookies de sesión.
type Manager struct{ secret []byte }

// NewManager crea el gestor con el secreto de firma.
func NewManager(secret string) *Manager { return &Manager{secret: []byte(secret)} }

// Session es el estado de una petición.
type Session struct {
	manager *Manager
	data    payload
	current []Flash // avisos que se muestran en esta petición (los guardados antes + los `now`)
	dirty   bool
}

// Load lee la sesión de la petición; si falta o es inválida, devuelve una sesión vacía.
func (m *Manager) Load(r *http.Request) *Session {
	session := &Session{manager: m}
	cookie, err := r.Cookie(CookieName)
	if err != nil {
		return session
	}
	decoded, ok := m.verify(cookie.Value)
	if !ok {
		return session
	}
	if err := json.Unmarshal(decoded, &session.data); err != nil {
		session.data = payload{}
		return session
	}
	// El flash guardado se muestra en esta petición y se descarta.
	if len(session.data.Flash) > 0 {
		session.current = session.data.Flash
		session.data.Flash = nil
		session.dirty = true
	}
	return session
}

func (m *Manager) sign(data []byte) string {
	mac := hmac.New(sha256.New, m.secret)
	mac.Write(data)
	return base64.RawURLEncoding.EncodeToString(data) + "." + base64.RawURLEncoding.EncodeToString(mac.Sum(nil))
}

func (m *Manager) verify(value string) ([]byte, bool) {
	encoded, signature, found := strings.Cut(value, ".")
	if !found {
		return nil, false
	}
	data, err := base64.RawURLEncoding.DecodeString(encoded)
	if err != nil {
		return nil, false
	}
	given, err := base64.RawURLEncoding.DecodeString(signature)
	if err != nil {
		return nil, false
	}
	mac := hmac.New(sha256.New, m.secret)
	mac.Write(data)
	if !hmac.Equal(given, mac.Sum(nil)) {
		return nil, false
	}
	return data, true
}

// Commit escribe la cookie si la sesión cambió. Debe llamarse antes de escribir la respuesta.
func (s *Session) Commit(w http.ResponseWriter) {
	if !s.dirty {
		return
	}
	raw, err := json.Marshal(s.data)
	if err != nil {
		return
	}
	http.SetCookie(w, &http.Cookie{
		Name: CookieName, Value: s.manager.sign(raw), Path: "/", HttpOnly: true, SameSite: http.SameSiteLaxMode,
	})
	s.dirty = false
}

// ConversationID es el `session_id` vigente de la API ("" si no hay conversación).
func (s *Session) ConversationID() string { return s.data.ConversationID }

// SetConversation guarda el `session_id` de la API.
func (s *Session) SetConversation(id string) {
	s.data.ConversationID = id
	s.dirty = true
}

// ResetConversation descarta la conversación y sus metadatos.
func (s *Session) ResetConversation() {
	s.data.ConversationID = ""
	s.data.Metadata = nil
	s.dirty = true
}

// Metadata devuelve los metadatos guardados (vacíos si no hay).
func (s *Session) Metadata() Metadata {
	if s.data.Metadata == nil {
		return Metadata{}
	}
	return *s.data.Metadata
}

// RememberMetadata guarda los `project_metadata` de la API, compactados para no desbordar la cookie.
func (s *Session) RememberMetadata(metadata jsondoc.Doc) {
	compact := Metadata{
		ProjectName:     firstRunes(metadata.S("project_name"), MaxNameLength),
		AssumedTeamSize: metadata.S("assumed_team_size"),
		AgreedScope:     firstRunes(metadata.S("agreed_scope"), MaxScopeLength),
	}
	for index, technology := range metadata.Strings("mentioned_technologies") {
		if index >= MaxTechnologies {
			break
		}
		compact.MentionedTechnologies = append(compact.MentionedTechnologies, firstRunes(technology, MaxTechnologyLength))
	}
	s.data.Metadata = &compact
	s.dirty = true
}

// CSRFToken devuelve el token de la sesión, creándolo si hace falta.
func (s *Session) CSRFToken() string {
	if s.data.CSRF == "" {
		random := make([]byte, 32)
		if _, err := rand.Read(random); err != nil {
			panic("session: sin entropía para el token CSRF: " + err.Error())
		}
		s.data.CSRF = base64.RawURLEncoding.EncodeToString(random)
		s.dirty = true
	}
	return s.data.CSRF
}

// VerifyCSRF compara en tiempo constante el token recibido con el de la sesión.
func (s *Session) VerifyCSRF(token string) bool {
	if s.data.CSRF == "" || token == "" {
		return false
	}
	return subtle.ConstantTimeCompare([]byte(token), []byte(s.data.CSRF)) == 1
}

// Flashes devuelve los avisos que se muestran en esta petición.
func (s *Session) Flashes() []Flash { return s.current }

// FlashNow añade un aviso solo para esta respuesta (`flash.now`).
func (s *Session) FlashNow(kind, message string) {
	s.current = append(s.current, Flash{Type: kind, Message: message})
}

// FlashNext guarda un aviso para la siguiente petición (el de una redirección).
func (s *Session) FlashNext(kind, message string) {
	s.data.Flash = append(s.data.Flash, Flash{Type: kind, Message: message})
	s.dirty = true
}

func firstRunes(text string, limit int) string {
	if utf8.RuneCountInString(text) <= limit {
		return text
	}
	return string([]rune(text)[:limit])
}
