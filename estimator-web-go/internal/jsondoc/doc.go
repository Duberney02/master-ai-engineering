// Package jsondoc ofrece acceso tolerante a documentos JSON dinámicos.
//
// Los payloads de la API de IA que el cliente solo muestra (estimaciones, métricas, configuración) se leen como
// documentos: un campo ausente o de otro tipo es el valor vacío, nunca un error. Los números conservan su texto
// original (`json.Number`), de modo que `70` se muestra «70» y `70.5` «70.5», igual que en el servicio.
package jsondoc

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"strconv"
	"strings"
)

// Doc es un objeto JSON.
type Doc map[string]any

// Parse decodifica un único valor JSON conservando los números como json.Number. Rechaza cuerpos vacíos y datos
// sobrantes.
func Parse(body []byte) (any, error) {
	decoder := json.NewDecoder(bytes.NewReader(body))
	decoder.UseNumber()
	var value any
	if err := decoder.Decode(&value); err != nil {
		return nil, err
	}
	if _, err := decoder.Token(); err != io.EOF {
		return nil, fmt.Errorf("jsondoc: datos tras el valor JSON")
	}
	return value, nil
}

// ParseDoc decodifica un objeto JSON; devuelve un Doc nulo si el cuerpo no es un objeto.
func ParseDoc(body []byte) Doc {
	value, err := Parse(body)
	if err != nil {
		return nil
	}
	return From(value)
}

// From convierte un valor decodificado en Doc (nulo si no es un objeto).
func From(value any) Doc {
	if object, ok := value.(map[string]any); ok {
		return Doc(object)
	}
	if doc, ok := value.(Doc); ok {
		return doc
	}
	return nil
}

// Get devuelve el valor de una clave (nil si no existe).
func (d Doc) Get(key string) any { return d[key] }

// Has indica si la clave existe, aunque su valor sea null.
func (d Doc) Has(key string) bool {
	_, ok := d[key]
	return ok
}

// S devuelve el valor como texto, como `to_s` de Ruby: nil es «».
func (d Doc) S(key string) string { return String(d[key]) }

// Doc devuelve el sub-objeto (nulo si no lo es).
func (d Doc) Doc(key string) Doc { return From(d[key]) }

// List devuelve los objetos de un array, ignorando los elementos que no lo son.
func (d Doc) List(key string) []Doc {
	items, _ := d[key].([]any)
	docs := make([]Doc, 0, len(items))
	for _, item := range items {
		if doc := From(item); doc != nil {
			docs = append(docs, doc)
		}
	}
	return docs
}

// Strings devuelve los elementos de un array como texto.
func (d Doc) Strings(key string) []string {
	items, _ := d[key].([]any)
	texts := make([]string, 0, len(items))
	for _, item := range items {
		texts = append(texts, String(item))
	}
	return texts
}

// IsArray indica si el valor de la clave es un array JSON.
func (d Doc) IsArray(key string) bool {
	_, ok := d[key].([]any)
	return ok
}

// Truthy replica la verdad de Ruby: todo salvo nil y false.
func (d Doc) Truthy(key string) bool { return Truthy(d[key]) }

// Float devuelve el valor numérico (0 y false si no es un número).
func (d Doc) Float(key string) float64 {
	number, _ := ToFloat(d[key])
	return number
}

// Truthy: todo salvo nil y false.
func Truthy(value any) bool {
	if value == nil {
		return false
	}
	if flag, ok := value.(bool); ok {
		return flag
	}
	return true
}

// String replica `to_s` de Ruby para los valores JSON.
func String(value any) string {
	switch typed := value.(type) {
	case nil:
		return ""
	case string:
		return typed
	case json.Number:
		return typed.String()
	case bool:
		return strconv.FormatBool(typed)
	case float64:
		return strconv.FormatFloat(typed, 'f', -1, 64)
	case int:
		return strconv.Itoa(typed)
	case int64:
		return strconv.FormatInt(typed, 10)
	}
	return fmt.Sprint(value)
}

// ToFloat convierte números (y textos numéricos) a float64.
func ToFloat(value any) (float64, bool) {
	switch typed := value.(type) {
	case json.Number:
		number, err := typed.Float64()
		return number, err == nil
	case float64:
		return typed, true
	case int:
		return float64(typed), true
	case int64:
		return float64(typed), true
	case string:
		number, err := strconv.ParseFloat(strings.TrimSpace(typed), 64)
		return number, err == nil
	}
	return 0, false
}
