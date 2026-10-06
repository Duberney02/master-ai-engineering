import { useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { useNavSlot } from "./Layout";

interface Props {
  sidebar: ReactNode;
  children: ReactNode;
}

/** Rejilla con la barra lateral a la izquierda y botón «/» (en la cabecera) para ocultarla. */
export function WithSidebar({ sidebar, children }: Props) {
  const [collapsed, setCollapsed] = useState(false);
  const slot = useNavSlot();

  return (
    <>
      {slot &&
        createPortal(
          <button
            type="button"
            id="sidebar-toggle"
            aria-controls="sidebar"
            aria-expanded={!collapsed}
            title="Mostrar u ocultar el contexto del prompt"
            onClick={() => setCollapsed((value) => !value)}
          >
            {collapsed ? "»" : "«"}
          </button>,
          slot,
        )}
      <div className={`layout${collapsed ? " collapsed" : ""}`} id="layout">
        <aside id="sidebar">{sidebar}</aside>
        <main>{children}</main>
      </div>
    </>
  );
}
