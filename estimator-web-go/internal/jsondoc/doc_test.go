package jsondoc

import "testing"

func TestNumbersKeepTheirOriginalText(t *testing.T) {
	doc := ParseDoc([]byte(`{"a":70,"b":70.5,"c":20000.0,"d":"x","e":null,"f":true}`))
	if doc.S("a") != "70" || doc.S("b") != "70.5" || doc.S("c") != "20000.0" || doc.S("d") != "x" || doc.S("e") != "" || doc.S("f") != "true" || doc.S("zz") != "" {
		t.Errorf("S: %v", doc)
	}
	if doc.Float("b") != 70.5 || doc.Int("c") != 20000 || doc.Int("d") != 0 {
		t.Errorf("números: %v %v", doc.Float("b"), doc.Int("c"))
	}
}

func TestRubyTruthinessAndPresence(t *testing.T) {
	doc := ParseDoc([]byte(`{"zero":0,"no":false,"nulo":null,"blanco":"  ","texto":"x","lista":[],"llena":[1],"objeto":{}}`))
	truthy := map[string]bool{"zero": true, "no": false, "nulo": false, "blanco": true, "texto": true, "zz": false}
	for key, want := range truthy {
		if doc.Truthy(key) != want {
			t.Errorf("Truthy(%s)", key)
		}
	}
	present := map[string]bool{"zero": true, "no": false, "nulo": false, "blanco": false, "texto": true, "lista": false, "llena": true, "objeto": false}
	for key, want := range present {
		if doc.Present(key) != want {
			t.Errorf("Present(%s)", key)
		}
	}
}

func TestNestedAccessIsTolerant(t *testing.T) {
	doc := ParseDoc([]byte(`{"a":{"b":[{"c":1},3,{"c":2}]},"t":["x",1]}`))
	if got := doc.Doc("a").List("b"); len(got) != 2 || got[1].S("c") != "2" {
		t.Errorf("lista: %v", got)
	}
	if doc.Doc("nada").Doc("peor").S("x") != "" || doc.Doc("t") != nil {
		t.Error("lo ausente o de otro tipo es vacío, nunca un error")
	}
	if got := doc.Strings("t"); len(got) != 2 || got[1] != "1" || !doc.IsArray("t") || doc.IsArray("a") {
		t.Errorf("Strings: %v", got)
	}
}

func TestParseRejectsEmptyAndTrailingData(t *testing.T) {
	for _, body := range []string{"", "{} {}", "no json", "{"} {
		if _, err := Parse([]byte(body)); err == nil {
			t.Errorf("%q debería rechazarse", body)
		}
	}
	if ParseDoc([]byte(`[1]`)) != nil {
		t.Error("un array no es un Doc")
	}
}

func TestRubyToI(t *testing.T) {
	cases := map[string]int{"3": 3, " 12abc": 12, "": 0, "abc": 0, "-5": -5, "+7": 7, "3.9": 3, "99": 99}
	for text, want := range cases {
		if got := RubyToI(text); got != want {
			t.Errorf("RubyToI(%q) = %d, se esperaba %d", text, got, want)
		}
	}
}
