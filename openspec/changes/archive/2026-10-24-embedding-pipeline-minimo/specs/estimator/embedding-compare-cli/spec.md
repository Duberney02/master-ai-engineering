# Spec Delta

## Purpose

Comparar dos textos por similitud coseno desde la línea de comandos y registrar una comprobación con tres parejas.

## ADDED Requirements

### Requirement: CLI de similitud coseno
`scripts/compare.py` SHALL aceptar los argumentos obligatorios `--text-a` y `--text-b`, obtener ambos embeddings con `OpenAIEmbedder`, calcular `dot(a, b) / (norm(a) * norm(b))` solo con la biblioteca estándar (sin NumPy ni scikit-learn) y mostrar ambos textos y el valor numérico. SHALL funcionar dentro del contenedor (`docker compose exec estimador-cag python scripts/compare.py ...`) y fuera de él (`uv run python scripts/compare.py ...`).

#### Scenario: Textos idénticos
- **WHEN** se calcula la similitud de un vector consigo mismo
- **THEN** el resultado es 1.0 dentro de la tolerancia de coma flotante.

#### Scenario: Vectores ortogonales
- **WHEN** se calcula la similitud de `[1, 0]` y `[0, 1]`
- **THEN** el resultado es 0.0.

#### Scenario: Vector nulo
- **WHEN** alguno de los vectores tiene norma cero
- **THEN** el cálculo falla con un error explícito y no devuelve NaN.

#### Scenario: Argumentos ausentes
- **WHEN** falta `--text-a` o `--text-b`
- **THEN** la CLI termina con código distinto de cero y un mensaje de uso.

### Requirement: Sanity check con tres parejas
`app/embedding_pipeline/SANITY_CHECK.md` SHALL contener los tres valores de similitud realmente obtenidos con la CLI para las parejas A (cercanos, orientativo > 0.6), B (no relacionados, orientativo < 0.4) y C (genéricos, sin umbral), y un comentario de tres a cinco líneas sobre su relación con las expectativas. Los resultados SHALL provenir de ejecuciones reales y los umbrales SHALL declararse orientativos.

#### Scenario: Resultados reales registrados
- **WHEN** se ejecutan las tres parejas en el contenedor
- **THEN** el archivo recoge los tres valores obtenidos y el comentario; si una ejecución no pudo realizarse, se declara como pendiente.
