package session

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"unicode/utf8"

	"estimator-web/internal/jsondoc"
)

func roundTrip(t *testing.T, manager *Manager, mutate func(*Session)) *http.Request {
	t.Helper()
	session := manager.Load(httptest.NewRequest("GET", "/", nil))
	mutate(session)
	recorder := httptest.NewRecorder()
	session.Commit(recorder)
	request := httptest.NewRequest("GET", "/", nil)
	for _, cookie := range recorder.Result().Cookies() {
		request.AddCookie(cookie)
	}
	return request
}

func TestConversationAndMetadataSurviveTheCookie(t *testing.T) {
	manager := NewManager("secreto")
	request := roundTrip(t, manager, func(s *Session) {
		s.SetConversation("abc-123")
		s.RememberMetadata(jsondoc.ParseDoc([]byte(`{"project_name":"Orion","assumed_team_size":4,"mentioned_technologies":["FastAPI","Kafka"],"agreed_scope":"Portal"}`)))
	})
	loaded := manager.Load(request)
	if loaded.ConversationID() != "abc-123" {
		t.Errorf("conversación: %q", loaded.ConversationID())
	}
	metadata := loaded.Metadata()
	if metadata.ProjectName != "Orion" || metadata.AssumedTeamSize != "4" || strings.Join(metadata.MentionedTechnologies, ",") != "FastAPI,Kafka" || !metadata.Present() {
		t.Errorf("metadatos: %+v", metadata)
	}
}

func TestResetConversationClearsMetadataToo(t *testing.T) {
	manager := NewManager("secreto")
	request := roundTrip(t, manager, func(s *Session) {
		s.SetConversation("abc")
		s.RememberMetadata(jsondoc.Doc{"project_name": "Orion"})
	})
	again := roundTrip(t, manager, func(s *Session) {})
	_ = again
	loaded := manager.Load(request)
	loaded.ResetConversation()
	recorder := httptest.NewRecorder()
	loaded.Commit(recorder)
	next := httptest.NewRequest("GET", "/", nil)
	next.AddCookie(recorder.Result().Cookies()[0])
	final := manager.Load(next)
	if final.ConversationID() != "" || final.Metadata().Present() {
		t.Errorf("la conversación debe quedar limpia: %q %+v", final.ConversationID(), final.Metadata())
	}
}

func TestHugeMetadataIsCompactedToFitTheCookie(t *testing.T) {
	manager := NewManager("secreto")
	technologies := make([]any, 30)
	for index := range technologies {
		technologies[index] = strings.Repeat("t", 60)
	}
	huge := jsondoc.Doc{
		"project_name": strings.Repeat("n", 120), "assumed_team_size": 1000,
		"mentioned_technologies": technologies, "agreed_scope": strings.Repeat("ñ", 1000),
	}
	var cookieSize int
	request := roundTrip(t, manager, func(s *Session) {
		s.SetConversation("6f1c2c1e-6d0a-4a5e-9c1a-0d6f5b1f4a10")
		s.CSRFToken()
		s.RememberMetadata(huge)
	})
	cookie, _ := request.Cookie(CookieName)
	cookieSize = len(cookie.Value)
	if cookieSize > 4000 {
		t.Errorf("la cookie ocupa %d bytes, debe caber en ~4 KB", cookieSize)
	}
	metadata := manager.Load(request).Metadata()
	if utf8.RuneCountInString(metadata.ProjectName) != MaxNameLength || utf8.RuneCountInString(metadata.AgreedScope) != MaxScopeLength ||
		len(metadata.MentionedTechnologies) != MaxTechnologies || utf8.RuneCountInString(metadata.MentionedTechnologies[0]) != MaxTechnologyLength {
		t.Errorf("límites de compactado no aplicados: %d %d %d", utf8.RuneCountInString(metadata.ProjectName),
			utf8.RuneCountInString(metadata.AgreedScope), len(metadata.MentionedTechnologies))
	}
}

func TestTamperedOrForeignCookieIsAnEmptySession(t *testing.T) {
	manager := NewManager("secreto")
	request := roundTrip(t, manager, func(s *Session) { s.SetConversation("abc") })
	cookie, _ := request.Cookie(CookieName)

	forged := httptest.NewRequest("GET", "/", nil)
	forged.AddCookie(&http.Cookie{Name: CookieName, Value: "eyJjIjoieCJ9" + cookie.Value[strings.Index(cookie.Value, "."):]})
	if NewManager("secreto").Load(forged).ConversationID() != "" {
		t.Error("una cookie con el cuerpo cambiado debe ignorarse")
	}
	if NewManager("otro-secreto").Load(request).ConversationID() != "" {
		t.Error("una cookie firmada con otro secreto debe ignorarse")
	}
	garbage := httptest.NewRequest("GET", "/", nil)
	garbage.AddCookie(&http.Cookie{Name: CookieName, Value: "basura"})
	if manager.Load(garbage).ConversationID() != "" {
		t.Error("una cookie sin firma debe ignorarse")
	}
}

func TestFlashIsShownOnceAfterTheRedirect(t *testing.T) {
	manager := NewManager("secreto")
	request := roundTrip(t, manager, func(s *Session) { s.FlashNext("notice", "Guardado") })

	first := manager.Load(request)
	if flashes := first.Flashes(); len(flashes) != 1 || flashes[0].Type != "notice" || flashes[0].Message != "Guardado" {
		t.Fatalf("flash: %+v", flashes)
	}
	recorder := httptest.NewRecorder()
	first.Commit(recorder)
	next := httptest.NewRequest("GET", "/", nil)
	for _, cookie := range recorder.Result().Cookies() {
		next.AddCookie(cookie)
	}
	if len(manager.Load(next).Flashes()) != 0 {
		t.Error("el aviso debe mostrarse una sola vez")
	}
}

func TestFlashNowIsNotPersisted(t *testing.T) {
	manager := NewManager("secreto")
	session := manager.Load(httptest.NewRequest("GET", "/", nil))
	session.FlashNow("alert", "Error")
	recorder := httptest.NewRecorder()
	session.Commit(recorder)
	if len(session.Flashes()) != 1 || len(recorder.Result().Cookies()) != 0 {
		t.Error("flash.now solo vale para esta respuesta y no escribe cookie")
	}
}

func TestCSRFToken(t *testing.T) {
	manager := NewManager("secreto")
	request := roundTrip(t, manager, func(s *Session) { _ = s.CSRFToken() })
	session := manager.Load(request)
	token := session.CSRFToken()
	if token == "" || session.CSRFToken() != token {
		t.Fatal("el token debe ser estable dentro de la sesión")
	}
	if !session.VerifyCSRF(token) || session.VerifyCSRF("") || session.VerifyCSRF(token+"x") {
		t.Error("verificación de CSRF incorrecta")
	}
	if manager.Load(httptest.NewRequest("GET", "/", nil)).VerifyCSRF(token) {
		t.Error("una sesión sin token nunca valida")
	}
}

func TestCookieAttributes(t *testing.T) {
	manager := NewManager("secreto")
	session := manager.Load(httptest.NewRequest("GET", "/", nil))
	session.SetConversation("abc")
	recorder := httptest.NewRecorder()
	session.Commit(recorder)
	cookie := recorder.Result().Cookies()[0]
	if !cookie.HttpOnly || cookie.SameSite != http.SameSiteLaxMode || cookie.Path != "/" || cookie.Name != CookieName {
		t.Errorf("atributos de la cookie: %+v", cookie)
	}
}
