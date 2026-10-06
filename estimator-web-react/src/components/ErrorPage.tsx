import { Link } from "react-router-dom";
import { Alert } from "./Alert";
import { PlainPage } from "./Layout";

export function ErrorContent({ message }: { message: string }) {
  return (
    <>
      <h1>No se pudo completar la operación</h1>
      <Alert kind="error" id="api-error">{message}</Alert>
      <p>
        <Link to="/estimations">← Historial</Link> · <Link to="/">Nueva estimación</Link>
      </p>
    </>
  );
}

/** Pantalla de error (sin barra lateral), equivalente a `estimations/error.html.erb`. */
export function ErrorPage({ message }: { message: string }) {
  return (
    <PlainPage>
      <ErrorContent message={message} />
    </PlainPage>
  );
}

export function NotFoundPage() {
  return (
    <PlainPage>
      <h1>Página no encontrada</h1>
      <p>La página que buscas no existe.</p>
      <p>
        <Link to="/estimations">← Historial</Link> · <Link to="/">Nueva estimación</Link>
      </p>
    </PlainPage>
  );
}
