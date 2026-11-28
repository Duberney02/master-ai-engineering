import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { getPrimaryModel } from "../api/adminApi";
import { useShell } from "../hooks/useShell";

// El botón de ocultar la barra vive en la cabecera (como en Rails) pero lo controla la página que
// tiene barra lateral: Layout ofrece un hueco y WithSidebar le inyecta el botón con un portal.
const NavSlotContext = createContext<HTMLElement | null>(null);

export function useNavSlot(): HTMLElement | null {
  return useContext(NavSlotContext);
}

/**
 * Indicador del modelo primario. Es pura decoración: si Go no responde o no hay valor, se omite sin afectar a la
 * navegación ni a la página. Go cachea el valor 15 s, así que consultarlo en cada navegación es barato; al guardar
 * Ajustes se vuelve a consultar de inmediato.
 */
function PrimaryModelIndicator() {
  const { pathname } = useLocation();
  const { access, modelVersion } = useShell();
  const [model, setModel] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    getPrimaryModel(controller.signal)
      .then(setModel)
      .catch(() => undefined);
    return () => controller.abort();
  }, [pathname, modelVersion]);

  if (!model) return null;
  const label = <span id="primary-model" className="model-badge" title="Modelo primario del servicio IA">{model}</span>;
  return access === "allowed" ? <Link to="/settings" className="model-badge-link">{label}</Link> : label;
}

export function Layout() {
  const [slot, setSlot] = useState<HTMLElement | null>(null);

  return (
    <NavSlotContext.Provider value={slot}>
      <header>
        <nav aria-label="Principal">
          <span ref={setSlot} />
          <NavLink to="/" end>Nueva estimación</NavLink>
          <NavLink to="/estimations" end>Historial</NavLink>
          <NavLink to="/rag/chunking-comparisons">RAG · Chunking Lab</NavLink>
          <NavLink to="/settings" end>Ajustes</NavLink>
          <PrimaryModelIndicator />
        </nav>
      </header>
      <Outlet />
    </NavSlotContext.Provider>
  );
}

/** Contenido principal sin barra lateral (historial vacío de contexto, errores, 404). */
export function PlainPage({ children }: { children: ReactNode }) {
  return (
    <div className="layout no-sidebar" id="layout">
      <main>{children}</main>
    </div>
  );
}
