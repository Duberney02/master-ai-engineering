import { Link } from "react-router-dom";
import { PlainPage } from "./Layout";

/** Vista administrativa denegada por Go: no muestra datos y permite volver a las estimaciones. */
export function AccessRestricted({ section }: { section: string }) {
  return (
    <PlainPage>
      <h1>Acceso restringido</h1>
      <div className="alert warn" id="access-restricted">
        {section} solo está disponible para operadores autorizados. En este entorno de integración el acceso administrativo
        permanece cerrado.
      </div>
      <p>
        <Link to="/">← Volver a estimaciones</Link> · <Link to="/estimations">Historial</Link>
      </p>
    </PlainPage>
  );
}
