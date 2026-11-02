package web

import (
	"fmt"
	"html/template"
	"io/fs"
	"path"
	"strings"
	"time"
	"unicode/utf8"

	"estimator-web/internal/estimation"
	"estimator-web/internal/estimatorai"
	"estimator-web/internal/rag"
)

// templateFuncs son los helpers de las vistas (los de Rails: ApplicationHelper, NavigationHelper…).
func templateFuncs() template.FuncMap {
	return template.FuncMap{
		"labelFor":         labelFor,
		"optionsForLabels": optionsForLabels,
		"cacheSourceLabel": cacheSourceLabel,
		"formatCost":       formatCost,
		"formatWeeks":      formatWeeks,
		"formatUSD":        formatUSD,
		"formatTime":       formatTime,
		"outOfScopeReason": outOfScopeReason,
		"numPrec1":         numPrec1,
		"numPrec1Strip":    numPrec1Strip,
		"numPrec2":         numPrec2,
		"numPrec3":         numPrec3,
		"delimited":        delimited,
		"truncate":         truncate,
		"lower":            strings.ToLower,
		"roundedPct":       roundedPct,
		"plainInt":         plainInt,
		"contains":         contains,
		"strategyLabel":    rag.LabelFor,
		"catalog":          func() []rag.Strategy { return rag.Catalog },
		"maxDescription":   func() int { return estimation.MaxDescription },
		"minDescription":   func() int { return estimation.MinDescription },
		"maxUploadKB":      func() int { return estimation.MaxUploadBytes / 1000 },
		"maxAttachments":   func() int { return estimation.MaxAttachments },
		"maxAttachmentMB":  func() int { return estimation.MaxAttachmentBytes / (1024 * 1024) },
		"projectTypes":     func() []string { return estimation.ProjectTypes },
		"detailLevels":     func() []string { return estimation.DetailLevels },
		"outputFormats":    func() []string { return estimation.OutputFormats },
		"promptVersions":   func() []string { return estimation.PromptVersions },
		"budgetCount":      func() int { return len(estimatorai.Budgets()) },
		"sampleQueries":    estimatorai.SampleQueries,
		"durationSeconds":  durationSeconds,
		"navLink":          navLink,
		"join":             strings.Join,
		"runeCount":        utf8.RuneCountInString,
		"isoTime":          isoTime,
		"barWidth":         func(cost, maximum float64) string { return roundedPct(cost / maximum * 100) },
	}
}

// navItem es un enlace de la barra de navegación: marca la sección activa con `aria-current` y la clase `active`.
type navItem struct {
	Label, Path string
	Active      bool
}

func navLink(label, path, section, current string) navItem {
	return navItem{Label: label, Path: path, Active: section == current}
}

// isoTime formatea una fecha en ISO 8601 UTC, como la entiende `formatTime`.
func isoTime(moment time.Time) string { return moment.UTC().Format(time.RFC3339) }

func contains(list []string, value string) bool {
	for _, item := range list {
		if item == value {
			return true
		}
	}
	return false
}

// durationSeconds devuelve la duración de una comparación con un decimal ("" si no se midió).
func durationSeconds(comparison rag.Comparison) string {
	seconds, ok := comparison.DurationSeconds()
	if !ok {
		return ""
	}
	return fmt.Sprintf("%.1f", seconds)
}

// pageFiles asigna a cada pantalla su archivo; todas comparten el layout y los parciales (`_*.html`).
var pageFiles = map[string]string{
	"home":              "home.html",
	"estimations_new":   "estimations_new.html",
	"estimations_show":  "estimations_show.html",
	"estimations_index": "estimations_index.html",
	"estimations_error": "estimations_error.html",
	"lab_index":         "lab_index.html",
	"lab_new":           "lab_new.html",
	"lab_show":          "lab_show.html",
	"settings":          "settings.html",
}

func loadPages() (map[string]*template.Template, error) {
	partials, err := fs.Glob(templateFiles, "templates/_*.html")
	if err != nil {
		return nil, err
	}
	pages := make(map[string]*template.Template, len(pageFiles))
	for name, file := range pageFiles {
		files := append([]string{"templates/layout.html"}, partials...)
		files = append(files, path.Join("templates", file))
		parsed, err := template.New(name).Funcs(templateFuncs()).ParseFS(templateFiles, files...)
		if err != nil {
			return nil, fmt.Errorf("plantilla %s: %w", name, err)
		}
		pages[name] = parsed
	}
	return pages, nil
}
