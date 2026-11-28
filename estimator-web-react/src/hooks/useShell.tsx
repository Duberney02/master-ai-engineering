// Estado compartido de la cabecera: acceso administrativo observado y refresco del indicador del modelo primario.
//
// React no decide la autorización: Go responde 403 y las pantallas administrativas lo comunican aquí. El indicador solo
// enlaza a Ajustes cuando Go ya ha concedido acceso en esta sesión de navegación.

import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";

export type AdminAccess = "unknown" | "allowed" | "denied";

interface Shell {
  access: AdminAccess;
  /** Una pantalla administrativa informa del resultado de su última llamada. */
  reportAccess: (access: Exclude<AdminAccess, "unknown">) => void;
  /** Cambia con cada guardado de Ajustes: la barra vuelve a consultar el modelo primario. */
  modelVersion: number;
  refreshModel: () => void;
}

const inactive: Shell = { access: "unknown", reportAccess: () => undefined, modelVersion: 0, refreshModel: () => undefined };
const ShellContext = createContext<Shell>(inactive);

export function useShell(): Shell {
  return useContext(ShellContext);
}

export function ShellProvider({ children }: { children: ReactNode }) {
  const [access, setAccess] = useState<AdminAccess>("unknown");
  const [modelVersion, setModelVersion] = useState(0);
  const reportAccess = useCallback((next: Exclude<AdminAccess, "unknown">) => setAccess(next), []);
  const refreshModel = useCallback(() => setModelVersion((version) => version + 1), []);
  const value = useMemo(() => ({ access, reportAccess, modelVersion, refreshModel }), [access, reportAccess, modelVersion, refreshModel]);
  return <ShellContext.Provider value={value}>{children}</ShellContext.Provider>;
}
