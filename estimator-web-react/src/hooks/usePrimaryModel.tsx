// Modelo primario vigente para el indicador de la barra. Se consulta al cargar y tras guardar los ajustes.

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { getPrimaryModel } from "../api/settingsApi";

interface PrimaryModel {
  /** Vacío mientras carga o si el servicio no responde: el indicador se omite. */
  model: string;
  refresh: () => Promise<void>;
}

const PrimaryModelContext = createContext<PrimaryModel>({ model: "", refresh: async () => undefined });

export function usePrimaryModel(): PrimaryModel {
  return useContext(PrimaryModelContext);
}

export function PrimaryModelProvider({ children }: { children: ReactNode }) {
  const [model, setModel] = useState("");

  const refresh = useCallback(async () => {
    setModel(await getPrimaryModel());
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const value = useMemo(() => ({ model, refresh }), [model, refresh]);
  return <PrimaryModelContext.Provider value={value}>{children}</PrimaryModelContext.Provider>;
}
