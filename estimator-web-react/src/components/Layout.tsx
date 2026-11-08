import { createContext, useContext, useState, type ReactNode } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { usePrimaryModel } from "../hooks/usePrimaryModel";

// El botón de ocultar la barra vive en la cabecera (como en Rails) pero lo controla la página que
// tiene barra lateral: Layout ofrece un hueco y WithSidebar le inyecta el botón con un portal.
const NavSlotContext = createContext<HTMLElement | null>(null);

export function useNavSlot(): HTMLElement | null {
  return useContext(NavSlotContext);
}

export function Layout() {
  const [slot, setSlot] = useState<HTMLElement | null>(null);
  const { model } = usePrimaryModel();

  return (
    <NavSlotContext.Provider value={slot}>
      <header>
        <nav aria-label="Principal">
          <span ref={setSlot} />
          <NavLink to="/" end>Nueva estimación</NavLink>
          <NavLink to="/estimations" end>Historial</NavLink>
          <NavLink to="/rag/chunking_comparisons">Chunking Lab</NavLink>
          <NavLink to="/ai_settings">Ajustes</NavLink>
          {model && (
            <NavLink to="/ai_settings" className="model-badge" id="primary-model" title="Modelo primario del servicio IA">
              {model}
            </NavLink>
          )}
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
