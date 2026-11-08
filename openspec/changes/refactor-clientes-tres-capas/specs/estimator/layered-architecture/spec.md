## ADDED Requirements

### Requirement: Servicio de IA sin clientes embebidos
`estimador-cag` SHALL NOT contener ni depender de ningún cliente de usuario: el árbol del proyecto, su `pyproject.toml`, su `uv.lock`, su `Dockerfile`, su `ARCHITECTURE.md` y sus pruebas SHALL NOT mencionar `streamlit`. El servicio SHALL ser consumido únicamente por el backend `estimator-web-go`, que es el único cliente de su API HTTP; los contratos HTTP del servicio SHALL permanecer sin cambios.

#### Scenario: Sin Streamlit
- **WHEN** se busca `streamlit` en `estimador-cag/` (código, `pyproject.toml`, `uv.lock`, `Dockerfile`, docs y tests)
- **THEN** no hay coincidencias y la imagen `estimador-cag:latest` no incluye `streamlit_app.py`.

#### Scenario: Contratos HTTP intactos
- **WHEN** se ejecuta la suite de pruebas de los endpoints existentes
- **THEN** todas pasan sin modificar sus aserciones sobre rutas o JSON.
