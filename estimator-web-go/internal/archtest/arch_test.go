// Package archtest verifica las reglas de arquitectura del servicio (las 4 de ARCHITECTURE.md): cada capa solo importa
// lo permitido y solo la capa HTTP habla con la API de IA.
package archtest

import (
	"go/ast"
	"go/parser"
	"go/token"
	"io/fs"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

const module = "estimator-web/internal/"

// allowed son los paquetes internos que puede importar cada paquete (el resto está prohibido).
var allowed = map[string][]string{
	"config":       {},
	"jsondoc":      {},
	"estimatorai":  {"jsondoc"},
	"rag":          {"jsondoc"},
	"ai":           {"jsondoc"},
	"estimation":   {},
	"session":      {"jsondoc"},
	"web":          {"config", "jsondoc", "estimatorai", "rag", "ai", "estimation", "session"},
	"archtest":     {},
}

func internalDir(t *testing.T) string {
	t.Helper()
	directory, err := filepath.Abs("..")
	if err != nil {
		t.Fatal(err)
	}
	return directory
}

// goFiles devuelve los archivos .go de producción (sin pruebas) de un directorio.
func goFiles(t *testing.T, directory string) []string {
	t.Helper()
	var files []string
	err := filepath.WalkDir(directory, func(path string, entry fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if !entry.IsDir() && strings.HasSuffix(path, ".go") && !strings.HasSuffix(path, "_test.go") {
			files = append(files, path)
		}
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	return files
}

func TestPackagesOnlyImportWhatTheirLayerAllows(t *testing.T) {
	root := internalDir(t)
	entries, err := os.ReadDir(root)
	if err != nil {
		t.Fatal(err)
	}
	for _, entry := range entries {
		if !entry.IsDir() {
			continue
		}
		permitted, known := allowed[entry.Name()]
		if !known {
			t.Errorf("paquete %q sin regla de dependencias: añádelo a `allowed`", entry.Name())
			continue
		}
		for _, file := range goFiles(t, filepath.Join(root, entry.Name())) {
			parsed, err := parser.ParseFile(token.NewFileSet(), file, nil, parser.ImportsOnly)
			if err != nil {
				t.Fatal(err)
			}
			for _, spec := range parsed.Imports {
				path := strings.Trim(spec.Path.Value, `"`)
				if !strings.HasPrefix(path, module) {
					continue
				}
				dependency := strings.TrimPrefix(path, module)
				if !contains(permitted, dependency) {
					t.Errorf("%s importa internal/%s, que su capa no permite", filepath.Base(file), dependency)
				}
			}
		}
	}
}

// outbound son los usos de net/http que abren una conexión hacia otro servicio.
var outbound = map[string]bool{"NewRequest": true, "NewRequestWithContext": true, "Get": true, "Post": true, "PostForm": true, "Head": true, "Client": true, "DefaultClient": true}

func TestOnlyTheHTTPLayerTalksToTheAIService(t *testing.T) {
	root := internalDir(t)
	entries, _ := os.ReadDir(root)
	for _, entry := range entries {
		if !entry.IsDir() || entry.Name() == "estimatorai" || entry.Name() == "archtest" {
			continue
		}
		for _, file := range goFiles(t, filepath.Join(root, entry.Name())) {
			parsed, err := parser.ParseFile(token.NewFileSet(), file, nil, 0)
			if err != nil {
				t.Fatal(err)
			}
			ast.Inspect(parsed, func(node ast.Node) bool {
				selector, ok := node.(*ast.SelectorExpr)
				if !ok {
					return true
				}
				if pkg, ok := selector.X.(*ast.Ident); ok && pkg.Name == "http" && outbound[selector.Sel.Name] {
					t.Errorf("%s usa http.%s: solo internal/estimatorai habla HTTP con el servicio IA", filepath.Base(file), selector.Sel.Name)
				}
				return true
			})
		}
	}
}

func contains(list []string, value string) bool {
	for _, item := range list {
		if item == value {
			return true
		}
	}
	return false
}
